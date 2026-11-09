"use client";

import { useEffect, useState } from "react";
import { BACKEND_URL } from "@/constants/config";
import { useMarketData } from "@/context/MarketDataContext";

type Trade = {
  tx_hash: string;
  network: string;
  pair: string;
  action: string;
  amount: number;
  token: string;
  price?: number;
  token_amount?: number;
  price_usd?: number;
  network_fee: number;
  status: string;
  timestamp: number;
};

const PAGE_SIZE = 50;

export default function ReportsPage() {
  const { marketData } = useMarketData();
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);

  const ethPrice =
    marketData.find((pair) => pair.base_symbol.toUpperCase() === "ETH")?.price ?? 3000;

  useEffect(() => {
    async function fetchTrades() {
      setLoading(true);
      try {
        // Fetch all trades (large limit)
        const res = await fetch(`${BACKEND_URL}/portfolio/trades?limit=1000&_=${Date.now()}`);
        if (res.ok) {
          const json = await res.json();
          // Backend appends newest last; reverse for newest-first display.
          setTrades(json.reverse());
        }
      } catch (e) {
        console.error("Failed to fetch trades", e);
      } finally {
        setLoading(false);
      }
    }
    fetchTrades();
  }, []);

  const handleDownload = () => {
    window.open(
      `${BACKEND_URL}/portfolio/trades/export?eth_price=${ethPrice}`,
      "_blank"
    );
  };

  // Prefer the USD price captured at execution; fall back to live market data
  // and finally to the stablecoin table. ETH is no longer hardcoded.
  const convertToUSD = (amount: number, currency: string): number => {
    const stableRates: Record<string, number> = {
      USDC: 1,
      USDT: 1,
      DAI: 1,
    };
    const market = marketData.find(
      (pair) => pair.base_symbol.toUpperCase() === currency.toUpperCase()
    )?.price;
    const rate =
      market ??
      (currency.toUpperCase() === "ETH" || currency.toUpperCase() === "WETH"
        ? ethPrice
        : stableRates[currency.toUpperCase()]) ??
      1;
    return amount * rate;
  };

  const getTradeDisplay = (t: Trade) => {
    const [base, quote] = t.pair.split("/");
    const isBaseCurrency = ["ETH", "USDC", "USDT", "DAI", "WETH"].includes(base);
    const isQuoteCurrency = ["ETH", "USDC", "USDT", "DAI", "WETH", "USD"].includes(quote);
    
    // Determine the "Real" Asset and Currency
    // If base is a currency (e.g. ETH) and quote is NOT (e.g. PEPE), treat as inverted (Asset = PEPE).
    let inverted = false;
    let realAsset = base;
    let realCurrency = quote;

    if (isBaseCurrency && !isQuoteCurrency) {
       inverted = true;
       realAsset = quote;
       realCurrency = base;
    } else if (!isBaseCurrency && isQuoteCurrency) {
       // Normal case: PEPE/ETH -> Asset=PEPE, Currency=ETH
       realAsset = base;
       realCurrency = quote;
    } else {
       // Both are currencies or both are assets? Default to normal.
       // e.g. ETH/USDC -> Asset=ETH, Currency=USDC
       realAsset = base;
       realCurrency = quote;
    }

    let displayTokenAmount = 0; // Quantity of Real Asset
    let quoteAmount = 0;        // Cost/Proceeds in Real Currency
    let displayAction = t.action;
    
    // Uniform trade record standard:
    //   amount       = quantity of the pair's QUOTE currency (spent on buy, received on sell)
    //   token_amount = quantity of the pair's BASE token (received on buy, sold on sell)
    if (inverted) {
        // Inverted Pair: ETH/PEPE (Base: ETH = real currency, Quote: PEPE = real asset)
        // Selling the base (ETH) effectively buys the asset (PEPE), so flip the action.
        displayAction = t.action === "sell" ? "buy" : "sell";
        displayTokenAmount = t.amount || 0;       // quote qty = real asset
        quoteAmount = t.token_amount || 0;        // base qty = real currency
    } else {
        // Normal Pair: PEPE/ETH (Base: PEPE = real asset, Quote: ETH = real currency)
        displayTokenAmount = t.token_amount || 0; // base qty = real asset
        quoteAmount = t.amount || 0;              // quote qty = real currency
    }

    // Determine the actual currency for the quote amount (cost/proceeds)
    // The quote amount is always denominated in realCurrency (derived from the pair).
    let quoteCurrencyForConversion = realCurrency;

    // Per the uniform standard, `token` names the pair's quote currency. When it
    // is a known currency it confirms the conversion currency; for inverted pairs
    // the quote is the asset (not in this list), so realCurrency (the base) is used.
    if (["USDC", "USDT", "DAI", "ETH", "WETH"].includes(t.token)) {
        quoteCurrencyForConversion = t.token;
    }

    const amountUSD =
      t.price_usd && t.token_amount
        ? t.token_amount * t.price_usd
        : convertToUSD(quoteAmount, quoteCurrencyForConversion);
    const displayPrice = displayTokenAmount ? amountUSD / displayTokenAmount : 0;
    const feeUSD = t.network_fee || 0;
    const totalUSD = Math.max(amountUSD + feeUSD, 0);

    return {
      displayTokenAmount,
      displayPrice,
      displayCurrency: "USDC", // All prices converted to USD equiv
      amountUSD,
      feeUSD,
      totalUSD,
      displayAction
    };
  };

  const processedTrades = trades.map(t => ({...t, ...getTradeDisplay(t)}));

  const totalSpent = processedTrades
    .filter(t => t.displayAction === "buy")
    .reduce((acc, t) => acc + t.totalUSD, 0);

  const totalSold = processedTrades
    .filter(t => t.displayAction === "sell")
    .reduce((acc, t) => acc + t.totalUSD, 0);

  const formatTokenAmount = (value: number) => {
    if (!Number.isFinite(value)) {
      return "-";
    }
    if (Number.isInteger(value)) {
      return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
    }
    return value.toFixed(6);
  };

  const totalPages = Math.max(1, Math.ceil(processedTrades.length / PAGE_SIZE));
  const paginatedTrades = processedTrades.slice(
    (currentPage - 1) * PAGE_SIZE,
    currentPage * PAGE_SIZE
  );

  // Reset to page 1 when trades data changes
  useEffect(() => {
    setCurrentPage(1);
  }, [trades.length]);

  // Generate page numbers for pagination controls
  const getPageNumbers = () => {
    const pages: (number | string)[] = [];
    if (totalPages <= 7) {
      for (let i = 1; i <= totalPages; i++) pages.push(i);
    } else {
      pages.push(1);
      if (currentPage > 3) pages.push("...");
      for (let i = Math.max(2, currentPage - 1); i <= Math.min(totalPages - 1, currentPage + 1); i++) {
        pages.push(i);
      }
      if (currentPage < totalPages - 2) pages.push("...");
      pages.push(totalPages);
    }
    return pages;
  };

  return (
    <main className="min-h-screen bg-slate-950 text-white">
      <div className="container mx-auto p-6 space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Activity Reports</h1>
            <p className="text-gray-400 text-sm">
              Detailed log of all trading activity.
            </p>
          </div>
          <button
            onClick={handleDownload}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg font-medium transition-colors"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-5 h-5">
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3" />
            </svg>
            Export CSV
          </button>
        </div>

        {/* Summary Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="bg-slate-900 border border-slate-800 p-4 rounded-xl">
            <span className="text-gray-400 text-sm">Total Transactions</span>
            <p className="text-2xl font-bold mt-1">{trades.length}</p>
          </div>
          <div className="bg-slate-900 border border-slate-800 p-4 rounded-xl">
            <span className="text-gray-400 text-sm">Total Volume (Buy)</span>
            <p className="text-2xl font-bold mt-1 text-emerald-400">${totalSpent.toFixed(2)}</p>
          </div>
          <div className="bg-slate-900 border border-slate-800 p-4 rounded-xl">
            <span className="text-gray-400 text-sm">Total Volume (Sell)</span>
            <p className="text-2xl font-bold mt-1 text-blue-400">${totalSold.toFixed(2)}</p>
          </div>
        </div>

        {/* Table */}
        <div className="bg-slate-900/50 border border-slate-800 rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left text-gray-400">
              <thead className="text-xs uppercase bg-slate-900 text-gray-400">
                <tr>
                  <th scope="col" className="px-2 py-3 text-center">Date</th>
                  <th scope="col" className="px-2 py-3 text-center">Network</th>
                  
                  <th scope="col" className="px-2 py-3 text-center">Pair</th>
                  <th scope="col" className="px-2 py-3 text-center">Action</th>
                  <th scope="col" className="px-2 py-3 text-center">Price</th>
                  
                  <th scope="col" className="px-2 py-3 text-center">No. of Tokens</th>
                  <th scope="col" className="px-2 py-3 text-center">Amount</th>
                  <th scope="col" className="px-2 py-3 text-center">Fee</th>
                  <th scope="col" className="px-2 py-3 text-center">Total ($)</th>
                  <th scope="col" className="px-2 py-3 text-center">Status</th>
                  <th scope="col" className="px-2 py-3 min-w-[60px] text-center">Tx Hash</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {loading ? (
                  <tr>
                    <td colSpan={10} className="px-6 py-8 text-center text-gray-500">
                      Loading trades...
                    </td>
                  </tr>
                ) : trades.length === 0 ? (
                  <tr>
                    <td colSpan={10} className="px-6 py-8 text-center text-gray-500">
                      No activity recorded yet.
                    </td>
                  </tr>
                ) : (
                  paginatedTrades.map((t) => {
                    const {
                      displayTokenAmount,
                      displayPrice,
                      displayCurrency,
                      amountUSD,
                      feeUSD,
                      totalUSD,
                      displayAction
                    } = t;
                        
                    return (
                    <tr key={t.tx_hash} className={`hover:bg-slate-800/50 transition-colors ${t.status === "failed" || t.status === "cancelled" ? "opacity-50" : ""}`}>
                      <td className="px-6 py-4 whitespace-nowrap text-center">
                        <div className="flex flex-col">
                          <span className="text-white">
                            {new Date(t.timestamp * 1000).toLocaleDateString()}
                          </span>
                          <span className="text-xs text-gray-500">
                            {new Date(t.timestamp * 1000).toLocaleTimeString()}
                          </span>
                        </div>
                      </td>
                      <td className="px-6 py-4 text-gray-300 capitalize text-center">{t.network}</td>
                      <td className="px-6 py-4 font-medium text-white text-center">{t.pair}</td>
                      <td className="px-6 py-4 text-center">
                        <span className={`px-2 py-1 rounded text-xs font-medium ${
                          displayAction === "buy" 
                            ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                            : "bg-red-500/10 text-red-400 border border-red-500/20"
                        }`}>
                          {displayAction.toUpperCase()}
                        </span>
                      </td>
                      <td className="px-2 py-4 text-center text-gray-400">
                        {displayPrice ? (displayPrice < 0.0001 ? `${displayCurrency === "USDC" ? "$" : ""}${displayPrice.toFixed(10)}` : `${displayCurrency === "USDC" ? "$" : ""}${displayPrice.toFixed(6)}`) : "-"}
                      </td>
                      <td className="px-2 py-4 text-center text-gray-400">
                        {formatTokenAmount(displayTokenAmount)}
                      </td>
                      <td className="px-2 py-4 text-center text-gray-400">
                        ${amountUSD.toFixed(2)}
                      </td>
                      <td className="px-2 py-4 text-center font-medium text-white">
                        ${feeUSD >= 1 ? feeUSD.toFixed(2) : feeUSD.toFixed(4)}
                      </td>
                      <td className="px-2 py-4 text-center font-medium text-green-400">
                        ${totalUSD.toFixed(2)}
                      </td>
                      <td className="px-2 py-4 text-center">
                         <span className={`text-xs px-2 py-0.5 rounded ${
                             t.status === "failed" ? "bg-red-900 text-red-200" :
                             t.status === "cancelled" ? "bg-gray-700 text-gray-300" :
                             "bg-emerald-900 text-emerald-200"
                         }`}>
                             {t.status || "completed"}
                         </span>
                      </td>
                      <td className="px-2 py-4 text-center">
                        <a 
                          href={
                            t.network === "base" 
                              ? `https://basescan.org/tx/${t.tx_hash}`
                              : t.network === "sepolia"
                              ? `https://sepolia.etherscan.io/tx/${t.tx_hash}`
                              : `https://etherscan.io/tx/${t.tx_hash}`
                          }
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-blue-400 hover:text-blue-300 underline text-xs"
                        >
                          View
                        </a>
                      </td>
                    </tr>
                  )})
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Pagination Controls */}
        {!loading && processedTrades.length > PAGE_SIZE && (
          <div className="flex items-center justify-between bg-slate-900 border border-slate-800 rounded-xl px-4 py-3">
            <span className="text-sm text-gray-400">
              Showing {((currentPage - 1) * PAGE_SIZE) + 1}-{Math.min(currentPage * PAGE_SIZE, processedTrades.length)} of {processedTrades.length} transactions
            </span>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setCurrentPage(1)}
                disabled={currentPage === 1}
                className="px-2 py-1 text-xs rounded bg-slate-800 text-gray-400 hover:bg-slate-700 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                First
              </button>
              <button
                onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                disabled={currentPage === 1}
                className="px-2 py-1 text-xs rounded bg-slate-800 text-gray-400 hover:bg-slate-700 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Prev
              </button>
              {getPageNumbers().map((page, idx) =>
                typeof page === "string" ? (
                  <span key={`ellipsis-${idx}`} className="px-2 py-1 text-xs text-gray-500">...</span>
                ) : (
                  <button
                    key={page}
                    onClick={() => setCurrentPage(page)}
                    className={`px-3 py-1 text-xs rounded transition-colors ${
                      currentPage === page
                        ? "bg-blue-600 text-white font-bold"
                        : "bg-slate-800 text-gray-400 hover:bg-slate-700 hover:text-white"
                    }`}
                  >
                    {page}
                  </button>
                )
              )}
              <button
                onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                disabled={currentPage === totalPages}
                className="px-2 py-1 text-xs rounded bg-slate-800 text-gray-400 hover:bg-slate-700 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Next
              </button>
              <button
                onClick={() => setCurrentPage(totalPages)}
                disabled={currentPage === totalPages}
                className="px-2 py-1 text-xs rounded bg-slate-800 text-gray-400 hover:bg-slate-700 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Last
              </button>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
