"use client";
import { useEffect, useState, useMemo, useRef } from "react";
import { BrowserProvider, Contract, formatEther, formatUnits } from "ethers";
import { useWallet } from "../context/WalletContext";
import { useSettings, Network } from "../context/SettingsContext";
import { useMarketData } from "../context/MarketDataContext";
import TradePreviewModal from "./TradePreviewModal";
import { SEPOLIA_TOKENS, MAINNET_TOKENS, BASE_TOKENS, BASE_TOKEN_DECIMALS, ARBITRUM_TOKENS } from "../constants/tokens";
import { BACKEND_URL } from "../constants/config";
import { formatCompactUsd } from "../lib/marketFormatting";

type Holding = {
  token: string;
  balance: string;
  price: string;
  value: string;
  pnl: string;
  volume: number | null;
  volumeAddress: string | null;
};

const CHAIN_NETWORKS: Partial<Record<number, Network>> = {
  1: "mainnet", 8453: "base", 42161: "arbitrum", 11155111: "sepolia",
};
const NETWORK_TOKENS = { mainnet: MAINNET_TOKENS, base: BASE_TOKENS, arbitrum: ARBITRUM_TOKENS, sepolia: SEPOLIA_TOKENS };
const NETWORK_LABELS = { mainnet: "Ethereum Mainnet", base: "Base", arbitrum: "Arbitrum One", sepolia: "Sepolia Testnet" };

export default function PortfolioTable() {
  const { address, chainId } = useWallet();
  const { format, currency, network, setNetwork } = useSettings();
  const { marketData } = useMarketData();
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [tradeOpen, setTradeOpen] = useState(false);
  const [tradeToken, setTradeToken] = useState<string | null>(null);
  const [addedTokens, setAddedTokens] = useState<string[]>([]);
  const [holdingsSource, setHoldingsSource] = useState("");
  const holdingsRequest = useRef(0);
  const volumeController = useRef<AbortController | null>(null);
  const walletKey = `${address}:${chainId}`;
  const walletNetwork = chainId === null ? undefined : CHAIN_NETWORKS[chainId];
  const walletTokens = walletNetwork ? NETWORK_TOKENS[walletNetwork] : {};
  const volumeSupported = chainId === 1 || chainId === 8453 || chainId === 42161;
  const networkMismatch = !!address && chainId !== null && walletNetwork !== network;
  const [loading, setLoading] = useState(false);

  // New state for calculated totals
  const [totalValue, setTotalValue] = useState<string>("0.00");
  const [buyingPower, setBuyingPower] = useState<string>("0.00");
  const [sortConfig, setSortConfig] = useState<{ key: keyof Holding; direction: "asc" | "desc" } | null>(null);

  useEffect(() => {
    try {
      const stored = localStorage.getItem("addedTokens");
      if (stored) {
        setAddedTokens(JSON.parse(stored));
      }
    } catch (e) {
      console.error("Failed to load added tokens", e);
    }
  }, []);

  // useEffect(() => { ... }) for local storage reading is no longer needed here as context handles it.

  async function fetchVolumes(rows: Holding[], requestedChainId: number, requestId: number, signal: AbortSignal) {
    const addresses = Array.from(new Set(rows.flatMap(row => row.volumeAddress ? [row.volumeAddress] : [])));
    if (!volumeSupported || addresses.length === 0) return;
    try {
      const params = new URLSearchParams({ chain_id: String(requestedChainId), addresses: addresses.join(",") });
      const response = await fetch(`${BACKEND_URL}/market/token-volumes?${params}`, { signal });
      if (!response.ok) return;
      const data = await response.json();
      if (signal.aborted || requestId !== holdingsRequest.current || data?.chain_id !== requestedChainId || !data.volumes) return;
      setHoldings(rows.map(row => {
        const volume = row.volumeAddress ? data.volumes[row.volumeAddress] : null;
        return { ...row, volume: typeof volume === "number" && Number.isFinite(volume) && volume >= 0 ? volume : null };
      }));
    } catch {
      // Missing network data must never fall back to global volume.
    }
  }

  async function fetchHoldings() {
    const requestId = ++holdingsRequest.current;
    volumeController.current?.abort();
    if (!address || chainId === null || typeof window === "undefined" || !(window as any).ethereum) {
      setHoldings([]);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    volumeController.current = controller;
    setHoldings(rows => rows.map(row => ({ ...row, volume: null })));
    setLoading(true);
    try {
      const provider = new BrowserProvider((window as any).ethereum);
      const networkDetails = await provider.getNetwork();
      if (Number(networkDetails.chainId) !== chainId || requestId !== holdingsRequest.current) return;

      const balance = await provider.getBalance(address);
      const ethBalanceNumeric = parseFloat(formatEther(balance));

      // Use market data from context instead of direct API call
      const marketPairs = marketData;

      const getPriceChange = (symbol: string) => {
      if (symbol === "WETH") symbol = "ETH";
  
        // Force stablecoins to $1.00
        if (symbol === "USDC" || symbol === "DAI" || symbol === "USDT") {
          return { price: 1.0, change: 0 };
        }

      // Symbol mapping for tokens that might have different names in market data
      // Ensure we're checking the uppercase version
      const symbolMapping: Record<string, string> = {
        "Degen": "DEGEN",
        "Toshi": "TOSHI", 
        "Brett": "BRETT",
        "FLOKI": "FLOKI",
        "BONK": "BONK",
        "AERO": "AERO",
        "AVNT": "AVNT",
        "CLANKER": "CLANKER",
        "AIXBT": "AIXBT",
        "TIBBIR": "TIBBIR",
        "LUNA": "LUNA",
        "ETHY": "ETHY",
        "DEGEN": "DEGEN",
        "BRETT": "BRETT",
        "TOSHI": "TOSHI"
      };
  
      const marketSymbol = symbolMapping[symbol] || symbol;
      const p = marketPairs.find((x: any) => x.base_symbol === marketSymbol);
      
      // Debug logging for missing tokens
      if (!p) {
        console.log(`Missing market data for token: ${symbol} (looking for: ${marketSymbol})`);
        console.log('Available market symbols:', marketPairs.map((x: any) => x.base_symbol));
      }
      
      return p ? { price: p.price, change: p.change_24h } : { price: 0, change: 0 };
  };

      // formatCurrency removed, using format from context

      const holdingsList: Holding[] = [];
      let calculatedTotalValue = 0;
      let calculatedBuyingPower = 0;

      if (ethBalanceNumeric > 0) {
        const { price, change } = getPriceChange("ETH");
        const ethVal = ethBalanceNumeric * (price || 0);
        calculatedTotalValue += ethVal;
        calculatedBuyingPower += ethVal;

        const value =
          price > 0
            ? format(ethVal)
            : "-";
        const priceStr = price > 0 ? format(price) : "-";
        const pnl =
          change !== 0
            ? `${change > 0 ? "+" : ""}${change.toFixed(2)}%`
            : "-";
        holdingsList.push({
          token: "ETH",
          balance: ethBalanceNumeric.toFixed(4),
          price: priceStr,
          value,
          pnl,
          volume: null,
          volumeAddress: walletTokens.WETH?.toLowerCase() ?? null,
        });
      }

      const knownDecimals: Record<string, number> = {
        USDC: 6,
        USDT: 6,
        WBTC: 8,
        WETH: 18,
        DAI: 18,
        LINK: 18,
        UNI: 18,
        ...(walletNetwork === "base" ? BASE_TOKEN_DECIMALS : {}),
      };

      const rawHoldings: Record<string, number> = {};
      if (ethBalanceNumeric > 0) rawHoldings["ETH"] = ethBalanceNumeric;

      for (const [symbol, tokenAddress] of Object.entries(walletTokens)) {
        if (requestId !== holdingsRequest.current) return;
        // Skip placeholder tokens on Sepolia that don't have real contracts
        if (walletNetwork === "sepolia" && ["FLOKI", "PEPE", "SHIB", "MATIC", "CRV", "GRT", "BONK"].includes(symbol)) {
          continue;
        }
        
        try {
          const contract = new Contract(
            tokenAddress,
            ["function balanceOf(address) view returns (uint256)", "function decimals() view returns (uint8)"],
            provider
          );
          
          // Verify we are on the correct chain for this read? 
          // BrowserProvider queries the connected chain. If mismatch, we get 0.
          
          const raw: bigint = await contract.balanceOf(address);
          
          if (raw > BigInt(0)) {
            let decimals = knownDecimals[symbol];
            
            if (decimals === undefined) {
                try {
                  decimals = Number(await contract.decimals());
                } catch (err) {
                  decimals = 18;
                }
            }
            
            const balNumeric = parseFloat(formatUnits(raw, decimals));
            
            if (balNumeric > 0) {
                rawHoldings[symbol] = balNumeric;
            }
            
            // If balance is very small but > 0, show < 0.0001
            const balanceDisplay = balNumeric === 0 && raw > BigInt(0) 
                ? "< 0.0001" 
                : balNumeric.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 4 });

            const { price, change } = getPriceChange(symbol);
            const holdingVal = balNumeric * (price || 0);

            calculatedTotalValue += holdingVal;
            if (symbol === "USDC" || symbol === "WETH") {
              calculatedBuyingPower += holdingVal;
            }

            const value =
              price > 0
                ? format(holdingVal)
                : "-";
            const priceStr = price > 0 ? format(price) : "-";
            const pnl =
              change !== 0
                ? `${change > 0 ? "+" : ""}${change.toFixed(2)}%`
                : "-";
            
            holdingsList.push({
              token: symbol,
              balance: balanceDisplay,
              price: priceStr,
              value,
              pnl,
              volume: null,
              volumeAddress: tokenAddress.toLowerCase(),
            });
          }
        } catch (e) {
          console.warn(`Failed to fetch balance for ${symbol}`, e);
        }
      }

      if (requestId !== holdingsRequest.current) return;
      setHoldingsSource(walletKey);
      setHoldings(holdingsList);
      setTotalValue(format(calculatedTotalValue));
      setBuyingPower(format(calculatedBuyingPower));
      void fetchVolumes(holdingsList, chainId, requestId, controller.signal);

      // Agents use the app network; do not send another chain's balances.
      if (walletNetwork !== network) return;
      try {
        await fetch(`${BACKEND_URL}/portfolio/holdings`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(rawHoldings)
        });
      } catch (e) {
          console.error("Failed to sync holdings", e);
      }
      
    } catch (e) {
      console.error("Failed to load portfolio", e);
    } finally {
      if (requestId === holdingsRequest.current) setLoading(false);
    }
  }

  useEffect(() => {
    fetchHoldings();
    return () => {
      ++holdingsRequest.current;
      volumeController.current?.abort();
    };
  }, [address, chainId, currency, network, marketData]);

  useEffect(() => {
    setTradeOpen(false);
    setTradeToken(null);
  }, [address, chainId]);

  function handleTradeClick(token: string) {
    setTradeToken(token);
    setTradeOpen(true);
  }

  function handleCloseTrade() {
    setTradeOpen(false);
    setTradeToken(null);
  }

  const tradeSignal = useMemo(() => 
    tradeToken
      ? {
          pair: `${tradeToken}/USD`,
          action: "sell" as const,
          confidence: 1.0,
        }
      : null,
    [tradeToken]
  );

  const sortedHoldings = useMemo(() => {
    if (!address || holdingsSource !== walletKey) return [];
    if (!sortConfig) return holdings;
    return [...holdings].sort((a, b) => {
      let aVal: string | number = a[sortConfig.key] ?? -1;
      let bVal: string | number = b[sortConfig.key] ?? -1;

      // Convert to number for value/pnl/balance/price sorting
      if (sortConfig.key === "value") {
        aVal = parseFloat(a.value.replace(/[^0-9.-]+/g, "")) || 0;
        bVal = parseFloat(b.value.replace(/[^0-9.-]+/g, "")) || 0;
      } else if (sortConfig.key === "price") {
        aVal = parseFloat(a.price.replace(/[^0-9.-]+/g, "")) || 0;
        bVal = parseFloat(b.price.replace(/[^0-9.-]+/g, "")) || 0;
      } else if (sortConfig.key === "pnl") {
        aVal = parseFloat(a.pnl.replace(/[^0-9.-]+/g, "")) || 0;
        bVal = parseFloat(b.pnl.replace(/[^0-9.-]+/g, "")) || 0;
      } else if (sortConfig.key === "balance") {
        aVal = parseFloat(a.balance.replace(/[^0-9.-]+/g, "")) || 0;
        bVal = parseFloat(b.balance.replace(/[^0-9.-]+/g, "")) || 0;
      }

      if (aVal < bVal) return sortConfig.direction === "asc" ? -1 : 1;
      if (aVal > bVal) return sortConfig.direction === "asc" ? 1 : -1;
      return 0;
    });
  }, [address, holdings, holdingsSource, walletKey, sortConfig]);

  const requestSort = (key: keyof Holding) => {
    let direction: "asc" | "desc" = "desc"; // Default to desc (highest value first)
    if (sortConfig && sortConfig.key === key && sortConfig.direction === "desc") {
      direction = "asc";
    }
    setSortConfig({ key, direction });
  };

  const SortIcon = ({ column }: { column: keyof Holding }) => {
    if (sortConfig?.key !== column) return <span className="ml-1 text-gray-600">↕</span>;
    return sortConfig.direction === "asc" ? <span className="ml-1 text-blue-400">↑</span> : <span className="ml-1 text-blue-400">↓</span>;
  };

  async function addToMetaMask(tokenSymbol: string) {
    if (typeof window === "undefined" || !(window as any).ethereum) return;
    const tokenAddress = walletTokens[tokenSymbol];
    if (!tokenAddress) return;

    try {
       const decimals = tokenSymbol === "USDC" ? 6 : walletNetwork === "base" ? BASE_TOKEN_DECIMALS[tokenSymbol] ?? 18 : 18;
       let image = ""; // Optional URL
       
       await (window as any).ethereum.request({
        method: "wallet_watchAsset",
        params: {
          type: "ERC20",
          options: {
            address: tokenAddress,
            symbol: tokenSymbol,
            decimals: decimals,
            image: image,
          },
        },
      });

      const newSet = new Set([...addedTokens, tokenSymbol]);
      const newList = Array.from(newSet);
      setAddedTokens(newList);
      localStorage.setItem("addedTokens", JSON.stringify(newList));
    } catch (error) {
      console.error(error);
    }
  }

  return (
    <div className="min-w-0 rounded-xl border border-slate-800 bg-slate-950/60">
      <div className="flex flex-wrap justify-between items-center gap-3 mb-4 px-4 pt-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-200">Holdings</h2>
          <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-sm">
            <div className="text-gray-400">
              Total Value: <span className="text-green-400 font-mono">{address && holdingsSource === walletKey ? totalValue : format(0)}</span>
            </div>
            <div className="text-gray-400">
              Buying Power (ETH+WETH+USDC): <span className="text-blue-400 font-mono">{address && holdingsSource === walletKey ? buyingPower : format(0)}</span>
            </div>
          </div>
          {address && chainId !== null && (
            <p className="mt-2 text-xs text-slate-400">
              {volumeSupported && walletNetwork
                ? `24h DEX volume on ${NETWORK_LABELS[walletNetwork]} · ETH uses WETH volume`
                : "DEX volume unavailable on this network"}
            </p>
          )}
        </div>
        <div className="flex items-center gap-4">
          {network === "base" && (
            <a
              href="https://superbridge.app/base"
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1 border border-blue-500/30 px-2 py-1 rounded bg-blue-500/10"
            >
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-3 h-3">
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
              </svg>
              Bridge to Base
            </a>
          )}
          {network === "arbitrum" && (
            <a
              href="https://bridge.arbitrum.io/"
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1 border border-blue-500/30 px-2 py-1 rounded bg-blue-500/10"
            >
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-3 h-3">
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
              </svg>
              Bridge to Arbitrum
            </a>
          )}
          <button
            onClick={() => fetchHoldings()}
            className="text-xs text-gray-400 hover:text-white flex items-center gap-1"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-3 h-3">
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99" />
            </svg>
            Refresh
          </button>
        </div>
      </div>

      {networkMismatch && (
        <div className="mb-4 mx-4 px-4 py-3 bg-amber-500/10 border border-amber-500/20 rounded-lg flex items-center gap-3">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-5 h-5 text-amber-500 flex-shrink-0">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
          </svg>
          <div className="text-sm text-amber-200 flex-1">
            <p>
            Network mismatch: Holdings follow your wallet, but trading uses the app network.
            Switch your wallet to <span className="font-bold">{NETWORK_LABELS[network]}</span> to enable trading.
            </p>
            {walletNetwork && (
               <div className="mt-2">
                 <button
                   onClick={() => setNetwork(walletNetwork)}
                   className="underline font-bold hover:text-amber-100"
                 >
                   Or Switch App to {NETWORK_LABELS[walletNetwork]}
                 </button>
               </div>
            )}
          </div>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-900">
            <tr>
              <th 
                className="px-4 py-2 text-left font-medium text-gray-300 cursor-pointer hover:bg-slate-800 transition-colors"
                onClick={() => requestSort("token")}
              >
                Token <SortIcon column="token" />
              </th>
              <th 
                className="px-4 py-2 text-right font-medium text-gray-300 cursor-pointer hover:bg-slate-800 transition-colors"
                onClick={() => requestSort("balance")}
              >
                Balance <SortIcon column="balance" />
              </th>
              <th 
                className="px-4 py-2 text-right font-medium text-gray-300 cursor-pointer hover:bg-slate-800 transition-colors"
                onClick={() => requestSort("price")}
              >
                Price <SortIcon column="price" />
              </th>
              <th 
                className="px-4 py-2 text-right font-medium text-gray-300 cursor-pointer hover:bg-slate-800 transition-colors"
                onClick={() => requestSort("value")}
              >
                Value <SortIcon column="value" />
              </th>
              <th 
                className="px-4 py-2 text-right font-medium text-gray-300 cursor-pointer hover:bg-slate-800 transition-colors"
                onClick={() => requestSort("pnl")}
              >
                24h PnL <SortIcon column="pnl" />
              </th>
              <th
                className="px-4 py-2 text-right font-medium text-gray-300 hover:bg-slate-800 transition-colors"
                aria-sort={sortConfig?.key === "volume" ? (sortConfig.direction === "asc" ? "ascending" : "descending") : "none"}
              >
                <button
                  type="button"
                  onClick={() => requestSort("volume")}
                  title={volumeSupported && walletNetwork ? `24-hour DEX trading volume on ${NETWORK_LABELS[walletNetwork]} (USD)` : "Network DEX volume unavailable"}
                  className="whitespace-nowrap focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
                >
                  Volume <SortIcon column="volume" />
                </button>
              </th>
              <th className="px-4 py-2 text-right font-medium text-gray-300">
                Trade
              </th>
            </tr>
          </thead>
          <tbody>
            {!address && (
              <tr>
                <td
                  className="px-4 py-6 text-center text-gray-400"
                  colSpan={7}
                >
                  Connect a wallet to view holdings.
                </td>
              </tr>
            )}
            {address && sortedHoldings.length === 0 && !loading && (
              <tr>
                <td
                  className="px-4 py-6 text-center text-gray-400"
                  colSpan={7}
                >
                  No holdings found. Bridge funds or buy tokens to get started.
                </td>
              </tr>
            )}
            {loading && sortedHoldings.length === 0 && (
              <tr>
                <td
                  className="px-4 py-6 text-center text-gray-400"
                  colSpan={7}
                >
                  Loading holdings...
                </td>
              </tr>
            )}
            {sortedHoldings.map((row) => (
                <tr
                  key={row.token}
                  className="border-t border-slate-800/50 hover:bg-slate-900/50"
                >
                  <td className="px-4 py-3 font-medium text-white">
                    {row.token}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-300">
                    {row.balance}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-300 font-mono">
                    {row.price}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-300">
                    {row.value}
                  </td>
                  <td
                    className={`px-4 py-3 text-right ${
                      row.pnl.startsWith("+")
                        ? "text-emerald-400"
                        : row.pnl.startsWith("-")
                        ? "text-red-400"
                        : "text-gray-300"
                    }`}
                  >
                    {row.pnl}
                  </td>
                  <td
                    className="px-4 py-3 text-right text-gray-300 font-mono whitespace-nowrap"
                    title={row.volume != null && Number.isFinite(row.volume) && row.volume >= 0
                      ? `${row.volume.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 })}${row.token === "ETH" ? " · WETH volume proxy" : ""}`
                      : "Volume unavailable"}
                  >
                    {formatCompactUsd(row.volume)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        type="button"
                        className="px-3 py-1 rounded-md text-[11px] bg-blue-600 text-white hover:bg-blue-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        disabled={networkMismatch || !walletNetwork}
                        onClick={() => handleTradeClick(row.token)}
                      >
                        Trade
                      </button>
                      <button
                        onClick={() => {
                          if (row.token !== "ETH" && !addedTokens.includes(row.token)) {
                             addToMetaMask(row.token);
                          }
                        }}
                        title={
                          row.token === "ETH" 
                             ? "Native Token (Already in Wallet)" 
                             : addedTokens.includes(row.token)
                             ? "Already Added to MetaMask"
                             : "Add to MetaMask"
                        }
                        className={`p-1 transition-colors ${
                          row.token === "ETH" || addedTokens.includes(row.token)
                            ? "text-slate-700 cursor-default opacity-50"
                            : "text-gray-400 hover:text-orange-400"
                        }`}
                      >
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5">
                          <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 15h-2v-2h2v2zm0-4h-2V7h2v6z" fill="none" />
                          <path d="M21 12l-4.37-4.37c-.39-.39-1.03-.39-1.42 0-.39.39-.39 1.03 0 1.42L17.83 11H12c-.55 0-1 .45-1 1s.45 1 1 1h5.83l-2.62 1.95c-.39.39-.39 1.03 0 1.42.39.39 1.03.39 1.42 0L21 12z" />
                          <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 15h-2v-2h2v2zm0-4h-2V7h2v6z" opacity=".3" />
                          <path d="M11.5 21a9.5 9.5 0 1 0 0-19 9.5 9.5 0 0 0 0 19ZM11.5 13v6h1v-6h-1Zm0-8h1v6h-1V5Z" />
                        </svg>
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
      <TradePreviewModal
        open={tradeOpen}
        onClose={() => setTradeOpen(false)}
        onSuccess={() => {
          fetchHoldings();
        }}
        signal={tradeSignal}
      />
    </div>
  );
}
