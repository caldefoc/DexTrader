"use client";
import { useEffect, useState } from "react";

const backendUrl =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8000";

type Trade = {
  tx_hash: string;
  network: string;
  pair: string;
  action: string;
  amount: number;
  token: string;
  price?: number;
  token_amount?: number;
  timestamp: number;
};

export default function DailyReportSummary() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    async function fetchTrades() {
      setLoading(true);
      try {
        const res = await fetch(`${backendUrl}/portfolio/trades?limit=10`);
        if (res.ok) {
          const json = await res.json();
          setTrades(json);
        }
      } catch (e) {
        console.error("Failed to fetch trades", e);
      } finally {
        setLoading(false);
      }
    }
    
    // Poll every 10s to keep updated
    fetchTrades();
    const interval = setInterval(fetchTrades, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4 flex flex-col gap-3">
      <div>
        <h2 className="text-sm font-medium mb-1">Daily Activity</h2>
        <p className="text-xs text-gray-400">
          Summary of recent trading actions.
        </p>
      </div>
      
      {loading && trades.length === 0 ? (
        <p className="text-sm text-gray-500">Loading activity...</p>
      ) : trades.length === 0 ? (
        <p className="text-sm text-gray-400">
          No trades recorded yet today.
        </p>
      ) : (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
                <span className="text-sm text-gray-300">Total Trades:</span>
                <span className="text-sm font-bold text-white">{trades.length}</span>
            </div>
            <div className="space-y-2 mt-2 max-h-40 overflow-y-auto pr-1 custom-scrollbar">
                {[...trades].reverse().map(t => (
                    <div key={t.tx_hash} className="flex justify-between items-center text-xs p-2 rounded bg-slate-900 border border-slate-800">
                        <div className="flex flex-col">
                            <span className="font-medium text-gray-200">{t.pair}</span>
                            <span className="text-[10px] text-gray-500">{new Date(t.timestamp * 1000).toLocaleTimeString()} ({t.network})</span>
                        </div>
                        <div className={`flex flex-col items-end font-bold ${t.action === "buy" ? "text-emerald-400" : "text-red-400"}`}>
                            <span>{t.action.toUpperCase()} {t.amount.toFixed(4)} {t.token}</span>
                            {t.token_amount && t.price && (
                                <span className="text-[10px] text-gray-500 font-normal">
                                    {t.token_amount.toFixed(4)} @ {t.price.toFixed(6)}
                                </span>
                            )}
                        </div>
                    </div>
                ))}
            </div>
        </div>
      )}
    </div>
  );
}

