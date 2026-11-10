"use client";
import React, { createContext, useContext, useState, useEffect } from "react";
import { BACKEND_URL } from "../constants/config";

type TradingPair = {
  base_symbol: string;
  quote_symbol: string;
  price: number;
  change_24h: number;
  volume_24h?: number | null;
  cmc_url?: string | null;
};

interface MarketDataContextType {
  marketData: TradingPair[];
  loading: boolean;
  error: string | null;
  lastUpdated: number | null;
  refreshMarketData: () => Promise<void>;
}

const MarketDataContext = createContext<MarketDataContextType | undefined>(undefined);

// LocalStorage keys
const MARKET_DATA_KEY = "dexTrader_marketData";
const LAST_UPDATED_KEY = "dexTrader_marketDataLastUpdated";

// AbortSignal.timeout() is missing on older mobile browsers (Chrome < 103),
// where calling it throws inside the request path. Fall back to a controller.
function timeoutSignal(ms: number): AbortSignal {
  const factory = (AbortSignal as any)?.timeout;
  if (typeof factory === "function") {
    try {
      return factory.call(AbortSignal, ms);
    } catch {
      // fall through
    }
  }
  const controller = new AbortController();
  setTimeout(() => controller.abort(), ms);
  return controller.signal;
}

export function MarketDataProvider({ children }: { children: React.ReactNode }) {
  const [marketData, setMarketData] = useState<TradingPair[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);

  // Auto-fetch market data on mount (after loading from localStorage for instant display)
  useEffect(() => {
    const loadAndFetch = async () => {
      // First load from localStorage for instant display
      try {
        const storedData = localStorage.getItem(MARKET_DATA_KEY);
        const storedTimestamp = localStorage.getItem(LAST_UPDATED_KEY);
        
        if (storedData && storedTimestamp) {
          const parsedData = JSON.parse(storedData);
          const parsedTimestamp = parseInt(storedTimestamp, 10);
          
          if (Array.isArray(parsedData) && !isNaN(parsedTimestamp)) {
            setMarketData(parsedData);
            setLastUpdated(parsedTimestamp);
          }
        }
      } catch (err) {
        console.error("Failed to load market data from storage:", err);
      }

      // Then always fetch fresh data from the API
      try {
        await fetchMarketData();
      } catch (err) {
        console.error("Failed to fetch fresh market data:", err);
      }
    };

    loadAndFetch();
  }, []);

  const fetchMarketData = async (): Promise<TradingPair[]> => {
    setLoading(true);
    setError(null);
    
    try {
      // First check if backend is ready
      const healthCheck = await fetch(`${BACKEND_URL}/health`, { 
        method: 'GET',
        // Short timeout for health check
        signal: timeoutSignal(3000)
      });
      
      if (!healthCheck.ok) {
        throw new Error('Backend not ready');
      }
      
      // Backend is ready, fetch market data
      const response = await fetch(`${BACKEND_URL}/market/?limit=500`);
      if (!response.ok) {
        throw new Error(`Failed to fetch market data: ${response.status}`);
      }
      
      const data = await response.json();
      const pairs = data.pairs || [];
      const now = Date.now();
      
      // Save to localStorage
      try {
        localStorage.setItem(MARKET_DATA_KEY, JSON.stringify(pairs));
        localStorage.setItem(LAST_UPDATED_KEY, now.toString());
      } catch (storageError) {
        console.error("Failed to save market data to storage:", storageError);
      }
      
      setMarketData(pairs);
      setLastUpdated(now);
      setLoading(false);
      
      return pairs;
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : "Unknown error";
      // Provide clearer error for backend not ready
      const displayError = errorMsg.includes('Backend not ready') 
        ? "Backend starting up... Please wait a moment and try again."
        : errorMsg;
      setError(displayError);
      setLoading(false);
      
      // Return stored data if available, even if API call failed
      if (marketData.length > 0) {
        return marketData;
      }
      
      throw err;
    }
  };

  const refreshMarketData = async () => {
    await fetchMarketData();
  };

  // Auto-fetch on mount is handled by the useEffect above

  return (
    <MarketDataContext.Provider
      value={{
        marketData,
        loading,
        error,
        lastUpdated,
        refreshMarketData,
      }}
    >
      {children}
    </MarketDataContext.Provider>
  );
}

export const useMarketData = () => {
  const context = useContext(MarketDataContext);
  if (!context) {
    throw new Error("useMarketData must be used within MarketDataProvider");
  }
  return context;
};