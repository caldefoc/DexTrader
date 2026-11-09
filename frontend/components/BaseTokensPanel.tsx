"use client";

import { useEffect, useRef, useState } from "react";
import { BACKEND_URL } from "../constants/config";
import { formatCompactUsd } from "../lib/marketFormatting";

type RankBy = "market_cap" | "volume_24h";

type BaseToken = {
  id: string;
  name: string;
  symbol: string;
  price: number;
  change_24h: number | null;
  volume_24h: number | null;
  market_cap: number | null;
};

const usdPrice = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumSignificantDigits: 6,
});

export default function BaseTokensPanel() {
  const [tokens, setTokens] = useState<BaseToken[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshCount, setRefreshCount] = useState(0);
  const [sortBy, setSortBy] = useState<RankBy>("market_cap");
  const activeRequest = useRef<AbortController | null>(null);
  const rankingLabel = sortBy === "market_cap" ? "market cap" : "24hr volume";

  useEffect(() => {
    const controller = new AbortController();
    activeRequest.current = controller;

    async function loadTokens() {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch(`${BACKEND_URL}/market/base-tokens?sort_by=${sortBy}`, {
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("Unable to load Base tokens. Try refreshing.");
        const data: { tokens: BaseToken[] } = await response.json();
        if (!controller.signal.aborted) setTokens(data.tokens);
      } catch {
        if (!controller.signal.aborted) {
          setError("Unable to load Base tokens. Try refreshing.");
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }

    loadTokens();
    return () => controller.abort();
  }, [sortBy, refreshCount]);

  return (
    <section className="min-w-0 self-start rounded-xl border border-slate-800 bg-slate-950/60">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 px-4 py-3">
        <div>
          <h2 className="text-sm font-medium">Top 50 Base Tokens</h2>
          <p className="mt-1 text-[11px] text-gray-400">Base ecosystem · Ranked by {rankingLabel}</p>
        </div>
        <button
          type="button"
          aria-label="Refresh Base tokens"
          disabled={loading}
          onClick={() => setRefreshCount(count => count + 1)}
          className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-[10px] text-gray-200 hover:bg-slate-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400 disabled:opacity-50"
        >
          {loading ? "Loading…" : "Refresh"}
        </button>
        <select
          aria-label="Rank Base tokens"
          value={sortBy}
          onChange={event => {
            // Clear and abort immediately so old results never use the new label.
            activeRequest.current?.abort();
            setTokens([]);
            setError(null);
            setLoading(true);
            setSortBy(event.target.value as RankBy);
          }}
          className="w-full min-w-0 rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-gray-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
        >
          <option value="market_cap">Rank by Market Cap</option>
          <option value="volume_24h">Rank by 24hr Volume</option>
        </select>
      </div>
      {error && <p role="alert" className="px-4 py-3 text-sm text-red-400">{error}</p>}
      {loading && tokens.length === 0 && (
        <p role="status" className="px-4 py-6 text-sm text-gray-400">Loading Base tokens...</p>
      )}
      {!loading && !error && tokens.length === 0 && (
        <p className="px-4 py-6 text-sm text-gray-400">No Base tokens available. Try refreshing.</p>
      )}
      {tokens.length > 0 && (
        <div
          key={sortBy}
          role="region"
          aria-label={`Base tokens ranked by ${rankingLabel}`}
          aria-busy={loading}
          tabIndex={0}
          className="max-h-[600px] overflow-y-auto overscroll-contain focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
        >
          <ol className="divide-y divide-slate-800/60">
            {tokens.map((token, index) => (
              <li key={token.id} className="px-4 py-3 hover:bg-slate-900/50">
                <div className="flex items-start gap-3">
                  <span className="w-5 shrink-0 pt-0.5 text-right font-mono text-xs text-gray-500">{index + 1}</span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-xs font-medium text-gray-200" title={token.name}>{token.name}</p>
                        <p className="mt-1 truncate text-[10px] text-gray-500">{token.symbol.toUpperCase()}</p>
                      </div>
                      <div className="shrink-0 text-right font-mono">
                        <p className="text-xs text-gray-200">{usdPrice.format(token.price)}</p>
                        <p className={`mt-1 text-[10px] ${token.change_24h == null || token.change_24h === 0 ? "text-gray-400" : token.change_24h > 0 ? "text-emerald-400" : "text-red-400"}`}>
                          {token.change_24h == null ? "—" : `${token.change_24h > 0 ? "+" : ""}${token.change_24h.toFixed(2)}%`} <span className="text-gray-500">24h</span>
                        </p>
                      </div>
                    </div>
                    <div className="mt-2 flex flex-wrap justify-between gap-x-3 gap-y-1 text-[10px] text-gray-500">
                      <span>Cap <span className="font-mono text-gray-300">{formatCompactUsd(token.market_cap)}</span></span>
                      <span>Vol (24h) <span className="font-mono text-gray-300">{formatCompactUsd(token.volume_24h)}</span></span>
                    </div>
                  </div>
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}
      <p className="border-t border-slate-800 px-4 py-2 text-[10px] text-gray-500">
        GeckoTerminal · Base-only DEX metrics · Cached for 5 min
      </p>
    </section>
  );
}
