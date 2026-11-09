"use client";
import { useEffect, useState } from "react";
import { useMarketData } from "../context/MarketDataContext";
import type { MarketView } from "../app/dashboard/page";

type TradingPair = {
  base_symbol: string;
  quote_symbol: string;
  price: number;
  change_24h: number;
  volume_24h?: number | null;
  cmc_url?: string | null;
};

type Props = {
 view: MarketView;
 selectedPairs?: string[];
 onTogglePair?: (pair: string) => void;
};

export default function MarketTable(props: Props) {
  const { marketData, loading, error, lastUpdated, refreshMarketData } = useMarketData();
  const [rows, setRows] = useState<TradingPair[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  
  const [sortConfig, setSortConfig] = useState<{
    key: keyof TradingPair | "pair" | null;
    direction: "asc" | "desc";
  }>({ key: null, direction: "desc" });

  const handleSort = (key: keyof TradingPair | "pair") => {
    let direction: "asc" | "desc" = "desc";
    if (sortConfig.key === key && sortConfig.direction === "desc") {
      direction = "asc";
    }
    setSortConfig({ key, direction });
  };

  // Filter and sort the market data based on view and search
  useEffect(() => {
    let filteredRows = [...marketData];
    
    // Apply search filter
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      filteredRows = filteredRows.filter(row => 
        row.base_symbol.toLowerCase().includes(q) || 
        row.quote_symbol.toLowerCase().includes(q)
      );
    }

    // Apply view filter
    if (props.view === "tracked") {
      if (!props.selectedPairs || props.selectedPairs.length === 0) {
        filteredRows = [];
      } else {
        filteredRows = filteredRows.filter(row => 
          props.selectedPairs?.includes(`${row.base_symbol}/${row.quote_symbol}`)
        );
      }
    } else if (props.view === "volume") {
      // Sort by volume for volume view
      filteredRows.sort((a, b) => (b.volume_24h || 0) - (a.volume_24h || 0));
    } else if (props.view === "gainers" || props.view === "losers") {
      // For gainers/losers, we need to sort by change_24h
      filteredRows.sort((a, b) => b.change_24h - a.change_24h);
      if (props.view === "losers") {
        filteredRows.reverse();
      }
      // Take top 10
      filteredRows = filteredRows.slice(0, 10);
    }

    // Apply user sorting
    if (sortConfig.key) {
      const sortKey = sortConfig.key;
      filteredRows.sort((a, b) => {
        let valA: any, valB: any;
        
        if (sortKey === "pair") {
            valA = `${a.base_symbol}/${a.quote_symbol}`;
            valB = `${b.base_symbol}/${b.quote_symbol}`;
        } else {
            valA = a[sortKey];
            valB = b[sortKey];
        }
        
        // Handle undefined/null
        if (valA === undefined || valA === null) valA = -Infinity;
        if (valB === undefined || valB === null) valB = -Infinity;

        if (valA < valB) {
          return sortConfig.direction === "asc" ? -1 : 1;
        }
        if (valA > valB) {
          return sortConfig.direction === "asc" ? 1 : -1;
        }
        return 0;
      });
    }

    setRows(filteredRows);
  }, [marketData, props.view, props.selectedPairs, searchQuery, sortConfig]);

  const handleManualRefresh = async () => {
    await refreshMarketData();
  };

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/60">
      <div className="p-4 border-b border-slate-800 flex items-center justify-between">
        <input
          type="text"
          placeholder="Search tokens..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full max-w-xs bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-blue-500 transition-colors"
        />
        <div className="flex items-center gap-2">
          {lastUpdated && (
            <span className="text-xs text-gray-500">
              Updated: {new Date(lastUpdated).toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={handleManualRefresh}
            disabled={loading}
            className="bg-slate-800 hover:bg-slate-700 border border-slate-700 text-gray-400 hover:text-gray-200 rounded-lg px-3 py-2 text-sm transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
              <path fillRule="evenodd" d="M15.312 11.424a5.5 5.5 0 0 1-9.201 2.466l-.312-.311h2.433a.75.75 0 0 0 0-1.5H3.989a.75.75 0 0 0-.75.75v4.242a.75.75 0 0 0 1.5 0v-2.43l.31.31a7 7 0 0 0 11.712-3.138.75.75 0 0 0-1.449-.39Zm1.23-3.723a.75.75 0 0 0 .219-.53V2.929a.75.75 0 0 0-1.5 0V5.36l-.31-.31A7 7 0 0 0 3.239 8.188a.75.75 0 1 0 1.448.389A5.5 5.5 0 0 1 13.89 6.11l.311.31h-2.432a.75.75 0 0 0 0 1.5h4.243a.75.75 0 0 0 .53-.219Z" clipRule="evenodd" />
            </svg>
            Refresh
          </button>
        </div>
      </div>
      
      {loading && (
        <div className="p-8 text-center text-gray-500">
          Loading market data...
        </div>
      )}
      
      {error && (
        <div className="p-4 bg-red-900/20 border border-red-800/50 text-red-400 text-sm">
          Error: {error}
        </div>
      )}
      
      {!loading && !error && rows.length === 0 && (
        <div className="p-8 text-center text-gray-500">
          No market data available
        </div>
      )}
      
      {!loading && !error && rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-900">
              <tr>
                <th className="px-4 py-2 w-8 text-center"></th>
                <th 
                  className="px-4 py-2 text-left font-medium text-gray-300 cursor-pointer hover:text-white select-none"
                  onClick={() => handleSort("pair")}
                >
                  Pair {sortConfig.key === "pair" && (sortConfig.direction === "asc" ? "↑" : "↓")}
                </th>
                 <th 
                  className="px-4 py-2 text-right font-medium text-gray-300 cursor-pointer hover:text-white select-none"
                  onClick={() => handleSort("price")}
                 >
                  Price ($) {sortConfig.key === "price" && (sortConfig.direction === "asc" ? "↑" : "↓")}
                </th>
                <th 
                  className="px-4 py-2 text-right font-medium text-gray-300 cursor-pointer hover:text-white select-none"
                  onClick={() => handleSort("change_24h")}
                >
                  24h % {sortConfig.key === "change_24h" && (sortConfig.direction === "asc" ? "↑" : "↓")}
                </th>
                <th 
                  className="px-4 py-2 text-right font-medium text-gray-300 cursor-pointer hover:text-white select-none"
                  onClick={() => handleSort("volume_24h" as any)}
                >
                  Volume {sortConfig.key === "volume_24h" as any && (sortConfig.direction === "asc" ? "↑" : "↓")}
                </th>
                <th className="px-4 py-2 text-right font-medium text-gray-300">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {rows.map((row, index) => (
                <tr key={index} className="hover:bg-slate-900/50 transition-colors">
                  <td className="px-4 py-3 text-center">
                    {props.onTogglePair && (
                      <input
                        type="checkbox"
                        checked={props.selectedPairs?.includes(`${row.base_symbol}/${row.quote_symbol}`) || false}
                        onChange={() => props.onTogglePair?.(`${row.base_symbol}/${row.quote_symbol}`)}
                        className="rounded border-slate-700 text-blue-500 focus:ring-blue-500"
                      />
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className="w-6 h-6 rounded-full bg-slate-700 flex items-center justify-center text-xs font-medium">
                        {row.base_symbol[0]}
                      </div>
                      <span className="font-medium text-gray-200">
                        {row.base_symbol}
                      </span>
                      <span className="text-gray-500">/</span>
                      <span className="text-gray-500">{row.quote_symbol}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-gray-300">
                    {row.price.toLocaleString(undefined, {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 6,
                    })}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <span
                      className={`font-mono ${
                        row.change_24h >= 0
                          ? "text-emerald-400"
                          : "text-red-400"
                      }`}
                    >
                      {row.change_24h >= 0 ? "+" : ""}
                      {row.change_24h.toFixed(2)}%
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-gray-400">
                    {row.volume_24h
                      ? `$${Math.round(row.volume_24h).toLocaleString()}`
                      : "-"}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {row.cmc_url && (
                      <a
                        href={row.cmc_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-blue-400 hover:text-blue-300 transition-colors"
                      >
                        CMC
                      </a>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}