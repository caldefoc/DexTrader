"use client";
import { useState, useEffect } from "react";
import { useSettings } from "../context/SettingsContext";
import { useMarketData } from "../context/MarketDataContext";
import { MAINNET_TOKENS, BASE_TOKENS, SEPOLIA_TOKENS } from "../constants/tokens";

type Pair = {
  base_symbol: string;
  quote_symbol: string;
};

const backendUrl =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8000";

type Props = {
  selectedPairs: string[];
  onTogglePair: (pair: string) => void;
};

export default function PairSelector({ selectedPairs, onTogglePair }: Props) {
  const { network } = useSettings();
  const { marketData } = useMarketData();
  const [availablePairs, setAvailablePairs] = useState<Pair[]>([]);
  const [isEditing, setIsEditing] = useState(false);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    if (isEditing && availablePairs.length === 0 && marketData.length > 0) {
      setLoading(true);
      try {
        const fetchedPairs: Pair[] = marketData.map(pair => ({
          base_symbol: pair.base_symbol,
          quote_symbol: pair.quote_symbol
        }));
        
        // Ensure all static tokens are available to select
        const existingBases = new Set(fetchedPairs.map(p => p.base_symbol));
        const tokens = network === "mainnet" ? MAINNET_TOKENS : network === "base" ? BASE_TOKENS : SEPOLIA_TOKENS;
        const staticTokens = Object.keys(tokens);
        const missingPairs = staticTokens
            .filter(t => !existingBases.has(t))
            .map(t => ({
                base_symbol: t,
                quote_symbol: "USD"
            }));
        
        setAvailablePairs([...fetchedPairs, ...missingPairs]);
      } catch (e) {
        console.error("Failed to process pairs", e);
      } finally {
        setLoading(false);
      }
    }
  }, [isEditing, availablePairs.length, network, marketData]);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <div>
          <p className="text-sm font-medium">Tracked Pairs</p>
          <p className="text-xs text-gray-400">
            Configure which pairs the agents focus on.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setIsEditing(!isEditing)}
          className="px-3 py-1.5 rounded-md text-xs bg-secondary text-secondary-foreground hover:bg-slate-800"
        >
          {isEditing ? "Done" : "Edit"}
        </button>
      </div>

      {isEditing && (
        <div className="p-3 border border-slate-800 rounded-md bg-slate-900/50 mb-2">
          <p className="text-xs text-gray-400 mb-2">Select pairs to track:</p>
          <input
            type="text"
            placeholder="Search..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full mb-2 bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs text-gray-200 focus:outline-none focus:border-blue-500"
          />
          {loading && <p className="text-xs text-gray-500">Loading pairs...</p>}
          <div className="flex flex-wrap gap-2 max-h-40 overflow-y-auto">
            {!loading && availablePairs
                .filter(p => {
                    if (!searchQuery) return true;
                    const q = searchQuery.toLowerCase();
                    return p.base_symbol.toLowerCase().includes(q) || p.quote_symbol.toLowerCase().includes(q);
                })
                .map(p => {
              const pairStr = `${p.base_symbol}/${p.quote_symbol}`;
              const isSelected = selectedPairs.includes(pairStr);
              return (
                <button
                  key={pairStr}
                  onClick={() => onTogglePair(pairStr)}
                  className={`text-[10px] px-2 py-1 rounded border ${
                    isSelected
                      ? "bg-primary/20 border-primary text-primary"
                      : "bg-slate-950 border-slate-700 text-gray-400"
                  }`}
                >
                  {pairStr}
                </button>
              );
            })}
          </div>
        </div>
      )}

      <div className="flex flex-wrap gap-2 text-xs">
        {selectedPairs.length === 0 && !isEditing && (
          <span className="text-gray-400">
            No pairs selected. All pairs will be considered.
          </span>
        )}
        {selectedPairs.map(pair => (
          <span
            key={pair}
            className="px-2 py-1 rounded bg-slate-800 text-gray-300 border border-slate-700"
          >
            {pair}
          </span>
        ))}
      </div>
    </div>
  );
}

