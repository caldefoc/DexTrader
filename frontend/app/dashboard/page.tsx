"use client";
import { useState, useEffect } from "react";
import MarketTable from "../../components/MarketTable";
import GainersLosersToggle from "../../components/GainersLosersToggle";
import SignalsPanel from "../../components/SignalsPanel";

export type MarketView = "all" | "gainers" | "losers" | "tracked" | "volume";

const STORAGE_KEY = "dexTraderTrackedPairs";

export default function DashboardPage() {
  const [view, setView] = useState<MarketView>("all");
  const [selectedPairs, setSelectedPairs] = useState<string[]>([]);
  const [isLoaded, setIsLoaded] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed)) {
          setSelectedPairs(parsed);
        }
      }
    } catch {
      // ignore
    } finally {
      setIsLoaded(true);
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined" || !isLoaded) {
      return;
    }
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(selectedPairs));
    } catch {
      // ignore
    }
  }, [selectedPairs, isLoaded]);

  const togglePair = (pairStr: string) => {
    if (selectedPairs.includes(pairStr)) {
      setSelectedPairs(selectedPairs.filter(p => p !== pairStr));
    } else {
      setSelectedPairs([...selectedPairs, pairStr]);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <h1 className="text-2xl font-semibold">Market Dashboard</h1>
      </div>
      <div className="grid gap-6 md:grid-cols-[2fr,1fr]">
        <div className="flex flex-col gap-4">
          <div className="flex items-center justify-between gap-4">
            <h2 className="text-sm font-medium text-gray-400">Market Overview</h2>
            <GainersLosersToggle view={view} onChange={setView} />
          </div>
          <MarketTable
            view={view}
            selectedPairs={selectedPairs}
            onTogglePair={togglePair}
          />
        </div>
        <SignalsPanel />
      </div>
    </div>
  );
}
