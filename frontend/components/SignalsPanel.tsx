"use client";
import { useState } from "react";
import TradePreviewModal from "./TradePreviewModal";
import { useSignals, Signal } from "../context/SignalsContext";

export default function SignalsPanel() {
  const { signals, loading, error, refresh, lastUpdated } = useSignals();
  const [selectedSignal, setSelectedSignal] = useState<Signal | null>(null);
  const [tradeOpen, setTradeOpen] = useState(false);

  const orderedSignals = [...signals].sort((a, b) => {
    const aHold = a.action === "hold" ? 1 : 0;
    const bHold = b.action === "hold" ? 1 : 0;
    if (aHold !== bHold) {
      return aHold - bHold;
    }
    return b.confidence - a.confidence;
  });

  const headerSource = (() => {
    const first = signals[0];
    if (!first || !first.source) {
      return "Signals";
    }
    return first.source === "llm" ? "LLM agent" : "Rule-based agent";
  })();

  function handleSignalClick(signal: Signal) {
    if (signal.action === "hold") {
      return;
    }
    setSelectedSignal(signal);
    setTradeOpen(true);
  }

  function handleCloseTrade() {
    setTradeOpen(false);
    setSelectedSignal(null);
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/60 flex flex-col h-full">
      <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
        <h2 className="text-sm font-medium">Signals</h2>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400">{headerSource}</span>
          <button
            type="button"
            onClick={refresh}
            disabled={loading}
            className="px-2 py-1 rounded-md text-[10px] border border-slate-700 bg-slate-950 text-gray-200 hover:bg-slate-900 disabled:opacity-50"
          >
            Refresh
          </button>
        </div>
      </div>
      <div className="flex-1 px-4 py-4 space-y-3 overflow-y-auto">
        {loading && (
          <p className="text-sm text-gray-400">Loading signals...</p>
        )}
        {!loading && error && (
          <p className="text-sm text-red-400">{error}</p>
        )}
        {!loading && !error && orderedSignals.length === 0 && (
          <div className="text-center py-4 space-y-2">
            <p className="text-sm text-gray-400">
              No signals available yet.
            </p>
            <p className="text-xs text-gray-500">
              Click Refresh to update signals.
            </p>
            {lastUpdated && (
              <p className="text-[10px] text-gray-600">
                Last checked: {lastUpdated.toLocaleTimeString()}
              </p>
            )}
          </div>
        )}
        {!loading &&
          !error &&
          orderedSignals.map(signal => {
            const color =
              signal.action === "buy"
                ? "text-emerald-400 border-emerald-500/40"
                : signal.action === "sell"
                ? "text-red-400 border-red-500/40"
                : "text-gray-300 border-slate-600";
            const label =
              signal.action === "buy"
                ? "BUY"
                : signal.action === "sell"
                ? "SELL"
                : "HOLD";
            const sourceLabel =
              signal.source === "llm"
                ? "LLM"
                : signal.source === "rules"
                ? "Rules"
                : "";
            const isActionable = signal.action !== "hold";
            return (
              <button
                key={signal.pair + signal.action}
                type="button"
                onClick={() => handleSignalClick(signal)}
                className={`w-full text-left flex items-start justify-between rounded-lg border px-3 py-2 bg-slate-950/80 ${
                  isActionable ? "cursor-pointer hover:bg-slate-900" : ""
                } ${color}`}
              >
                <div>
                  <p className="text-xs text-gray-400">{signal.pair}</p>
                  {signal.explanation && (
                    <p className="mt-1 text-xs text-gray-300">
                      {signal.explanation}
                    </p>
                  )}
                  {sourceLabel && (
                    <p className="mt-1 text-[10px] text-gray-500">
                      Source: {sourceLabel}
                      {signal.created_at && (
                        <span className="ml-2 border-l border-gray-700 pl-2">
                          {new Date(signal.created_at * 1000).toLocaleTimeString()}
                        </span>
                      )}
                    </p>
                  )}
                </div>
                <div className="text-right">
                  <div className="text-xs font-semibold">{label}</div>
                  <div className="text-[10px] text-gray-400">
                    {(signal.confidence * 100).toFixed(0)}%
                  </div>
                </div>
              </button>
            );
          })}
      </div>
      <TradePreviewModal
        open={tradeOpen}
        onClose={handleCloseTrade}
        signal={
          selectedSignal && selectedSignal.action !== "hold"
            ? {
                pair: selectedSignal.pair,
                action: selectedSignal.action,
                confidence: selectedSignal.confidence,
              }
            : null
        }
      />
    </div>
  );
}
