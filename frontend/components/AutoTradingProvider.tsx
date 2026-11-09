"use client";

import { useAutoTrading } from "../hooks/useAutoTrading";

export default function AutoTradingProvider({ children }: { children: React.ReactNode }) {
  useAutoTrading();
  return <>{children}</>;
}
