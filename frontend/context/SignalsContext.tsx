"use client";
import {
  createContext,
  useContext,
  useEffect,
  useState,
  ReactNode,
  useRef
} from "react";
import { useSettings } from "./SettingsContext";
import { BACKEND_URL } from "../constants/config";

export type Signal = {
  pair: string;
  action: "buy" | "sell" | "hold";
  confidence: number;
  explanation?: string | null;
  source?: "llm" | "rules";
  created_at?: number;
};

type SignalsContextType = {
  signals: Signal[];
  loading: boolean;
  error: string | null;
  lastUpdated: Date | null;
  refresh: () => Promise<void>;
};

const SignalsContext = createContext<SignalsContextType | undefined>(
  undefined
);

export function SignalsProvider({ children }: { children: ReactNode }) {
  const { pollingInterval } = useSettings();
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [initialized, setInitialized] = useState(false);
  const timerRef = useRef<NodeJS.Timeout | null>(null);

  async function refresh() {
    try {
      setLoading(true);
      setError(null);
      const res = await fetch(`${BACKEND_URL}/signals?limit=200`);
      if (!res.ok) {
        throw new Error("Failed to load signals");
      }
      const json = await res.json();
      setSignals(json ?? []);
      setLastUpdated(new Date());
    } catch (err) {
      setSignals([]);
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
      setInitialized(true);
    }
  }

  useEffect(() => {
    if (!initialized && pollingInterval > 0) {
      refresh();
    }
  }, [initialized, pollingInterval]);

  useEffect(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
    }
    if (pollingInterval > 0) {
      timerRef.current = setInterval(() => {
        refresh();
      }, pollingInterval * 1000);
    }
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
    };
  }, [pollingInterval]);

  return (
    <SignalsContext.Provider value={{ signals, loading, error, refresh, lastUpdated }}>
      {children}
    </SignalsContext.Provider>
  );
}

export function useSignals() {
  const ctx = useContext(SignalsContext);
  if (!ctx) {
    throw new Error("useSignals must be used within a SignalsProvider");
  }
  return ctx;
}

