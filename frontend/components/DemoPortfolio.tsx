"use client";
import { useEffect, useState } from "react";
import { BACKEND_URL } from "../constants/config";

type DemoPosition = {
  token: string;
  quantity: number;
  avg_entry: number;
  price: number;
  value_usd: number;
  unrealized_usd: number;
};

type DemoSummary = {
  cash: number;
  positions: DemoPosition[];
  equity: number;
  starting_cash: number;
  pnl_usd: number;
  pnl_pct: number;
  fills: number;
  prices_available: boolean;
};

export default function DemoPortfolio() {
  const [summary, setSummary] = useState<DemoSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await fetch(`${BACKEND_URL}/portfolio/demo`);
        if (!res.ok) throw new Error(`Backend returned ${res.status}`);
        const data = await res.json();
        if (!cancelled) {
          setSummary(data);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load demo portfolio");
      }
    }
    load();
    const timer = setInterval(load, 5000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  if (error) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 text-sm text-red-400">
        {error}
      </div>
    );
  }

  if (!summary) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 text-sm text-gray-400">
        Loading virtual portfolio…
      </div>
    );
  }

  const pnlPositive = summary.pnl_usd >= 0;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 flex flex-col gap-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold">Virtual portfolio</h2>
          <p className="text-xs text-gray-500">
            Simulated fills at proposal price · {summary.fills} fill{summary.fills === 1 ? "" : "s"}
            {summary.prices_available ? "" : " · prices unavailable, showing cost basis"}
          </p>
        </div>
        <div className="text-right">
          <div className="text-2xl font-mono">${summary.equity.toLocaleString(undefined, { maximumFractionDigits: 2 })}</div>
          <div className={`text-sm font-mono ${pnlPositive ? "text-emerald-400" : "text-red-400"}`}>
            {pnlPositive ? "+" : ""}${summary.pnl_usd.toFixed(2)} ({summary.pnl_pct.toFixed(2)}%)
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 text-xs">
        <div className="bg-slate-950/60 border border-slate-800 rounded p-3">
          <span className="text-gray-500 uppercase block">Cash</span>
          <span className="font-mono text-gray-200">${summary.cash.toFixed(2)}</span>
        </div>
        <div className="bg-slate-950/60 border border-slate-800 rounded p-3">
          <span className="text-gray-500 uppercase block">Starting capital</span>
          <span className="font-mono text-gray-200">${summary.starting_cash.toFixed(2)}</span>
        </div>
      </div>

      {summary.positions.length === 0 ? (
        <p className="text-sm text-gray-500">
          No open positions. Start the agents on the Agents page and simulate a
          proposal to fill one.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-gray-500 border-b border-slate-800">
                <th className="py-2 pr-4">Token</th>
                <th className="py-2 pr-4 text-right">Quantity</th>
                <th className="py-2 pr-4 text-right">Avg entry</th>
                <th className="py-2 pr-4 text-right">Price</th>
                <th className="py-2 pr-4 text-right">Value</th>
                <th className="py-2 text-right">Unrealised</th>
              </tr>
            </thead>
            <tbody>
              {summary.positions.map(position => (
                <tr key={position.token} className="border-b border-slate-800/60">
                  <td className="py-2 pr-4 font-medium">{position.token}</td>
                  <td className="py-2 pr-4 text-right font-mono">{position.quantity.toLocaleString(undefined, { maximumFractionDigits: 6 })}</td>
                  <td className="py-2 pr-4 text-right font-mono text-gray-400">${position.avg_entry.toFixed(4)}</td>
                  <td className="py-2 pr-4 text-right font-mono">${position.price.toFixed(4)}</td>
                  <td className="py-2 pr-4 text-right font-mono">${position.value_usd.toFixed(2)}</td>
                  <td className={`py-2 text-right font-mono ${position.unrealized_usd >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {position.unrealized_usd >= 0 ? "+" : ""}${position.unrealized_usd.toFixed(2)}
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
