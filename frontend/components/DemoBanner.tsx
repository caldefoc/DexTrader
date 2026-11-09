"use client";
import { useState } from "react";
import { BACKEND_URL, DEMO_MODE } from "../constants/config";

/**
 * Fixed strip at the top of every page in demo builds.  It exists to make the
 * simulated nature of the deployment impossible to miss, and to expose the
 * one action a visitor may want: resetting the virtual portfolio.
 */
export default function DemoBanner() {
  const [resetting, setResetting] = useState(false);

  if (!DEMO_MODE) return null;

  async function reset() {
    if (!confirm("Reset the demo portfolio to $1,000 cash?")) return;
    setResetting(true);
    try {
      await fetch(`${BACKEND_URL}/portfolio/demo/reset`, { method: "POST" });
    } catch (e) {
      console.error("Failed to reset demo portfolio", e);
    } finally {
      setResetting(false);
    }
  }

  return (
    <div className="bg-amber-500/15 border-b border-amber-500/30 text-amber-200">
      <div className="container mx-auto px-4 py-1.5 flex items-center justify-between gap-4 text-xs">
        <span>
          <strong className="font-semibold">Demo</strong> — simulated portfolio,
          live market data, no wallet and no real funds. Proposals execute
          virtually at their quoted price.
        </span>
        <button
          onClick={reset}
          disabled={resetting}
          className="shrink-0 rounded border border-amber-500/40 px-2 py-0.5 hover:bg-amber-500/20 disabled:opacity-50"
        >
          {resetting ? "Resetting…" : "Reset portfolio"}
        </button>
      </div>
    </div>
  );
}
