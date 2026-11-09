"use client";
import React, { createContext, useContext, useState, useEffect } from "react";

type Currency = "USD" | "EUR";
export type Network = "sepolia" | "mainnet" | "base" | "arbitrum";

interface SettingsContextType {
  currency: Currency;
  setCurrency: (c: Currency) => void;
  network: Network;
  setNetwork: (n: Network) => void;
  pollingInterval: number; // in seconds
  setPollingInterval: (n: number) => void;
  marketRefreshInterval: number; // in seconds
  setMarketRefreshInterval: (n: number) => void;
  agentCacheDuration: number; // in seconds
  setAgentCacheDuration: (n: number) => void;
  autoTrading: boolean;
  setAutoTrading: (b: boolean) => void;
  autoTradingInterval: number; // in seconds
  setAutoTradingInterval: (n: number) => void;
  rate: number; // USD to EUR rate
  format: (usdValue: number) => string;
}

const SettingsContext = createContext<SettingsContextType | undefined>(undefined);

export function SettingsProvider({ children }: { children: React.ReactNode }) {
  const [currency, setCurrency] = useState<Currency>("USD");
  const [network, setNetwork] = useState<Network>("base");
  const [pollingInterval, setPollingInterval] = useState<number>(30); // Default to 30s
  const [marketRefreshInterval, setMarketRefreshInterval] = useState<number>(60); // Default to 60s
  const [agentCacheDuration, setAgentCacheDuration] = useState<number>(300); // Default to 300s (5 minutes)
  const [autoTrading, setAutoTrading] = useState<boolean>(false);
  const [autoTradingInterval, setAutoTradingInterval] = useState<number>(300); // Default to 300s (5 minutes)
  const [rate, setRate] = useState(0.85); // Default fallback

  useEffect(() => {
    if (typeof window !== "undefined") {
      // Load currency
      const savedCurrency = localStorage.getItem("dexTrader_currency");
      if (savedCurrency === "EUR" || savedCurrency === "USD") {
        setCurrency(savedCurrency);
      }

      // Load network
      const savedNetwork = localStorage.getItem("dexTrader_network");
      if (savedNetwork === "mainnet" || savedNetwork === "sepolia" || savedNetwork === "base" || savedNetwork === "arbitrum") {
        setNetwork(savedNetwork);
      }

      // Load polling interval
      const savedInterval = localStorage.getItem("dexTrader_pollingInterval");
      if (savedInterval) {
        const val = parseInt(savedInterval, 10);
        if (!isNaN(val) && val > 0) {
          setPollingInterval(val);
        }
      }

      // Load market refresh interval
      const savedMarketInterval = localStorage.getItem("dexTrader_marketRefreshInterval");
      if (savedMarketInterval) {
        const val = parseInt(savedMarketInterval, 10);
        if (!isNaN(val) && val > 0) {
          setMarketRefreshInterval(val);
        }
      }

      // Load agent cache duration
      const savedAgentCache = localStorage.getItem("dexTrader_agentCacheDuration");
      if (savedAgentCache) {
        const val = parseInt(savedAgentCache, 10);
        if (!isNaN(val) && val > 0) {
          setAgentCacheDuration(val);
        }
      }

      // Load auto trading
      const savedAuto = localStorage.getItem("dexTrader_autoTrading");
      if (savedAuto === "true") {
        setAutoTrading(true);
      }

      // Load auto trading interval
      const savedAutoInterval = localStorage.getItem("dexTrader_autoTradingInterval");
      if (savedAutoInterval) {
        const val = parseInt(savedAutoInterval, 10);
        if (!isNaN(val) && val >= 30) {
          setAutoTradingInterval(val);
        }
      }
    }

    // Fetch rate from a free API
    fetch("https://api.exchangerate-api.com/v4/latest/USD")
      .then((res) => res.json())
      .then((data) => {
        if (data && data.rates && data.rates.EUR) {
          setRate(data.rates.EUR);
        }
      })
      .catch((err) => console.error("Failed to fetch rates, using default", err));
  }, []);

  const updateCurrency = (c: Currency) => {
    setCurrency(c);
    if (typeof window !== "undefined") {
      localStorage.setItem("dexTrader_currency", c);
    }
  };

  const updateNetwork = (n: Network) => {
    setNetwork(n);
    if (typeof window !== "undefined") {
      localStorage.setItem("dexTrader_network", n);
    }
  };

  const updatePollingInterval = (n: number) => {
    setPollingInterval(n);
    if (typeof window !== "undefined") {
      localStorage.setItem("dexTrader_pollingInterval", n.toString());
    }
  };

  const updateMarketRefreshInterval = (n: number) => {
    setMarketRefreshInterval(n);
    if (typeof window !== "undefined") {
      localStorage.setItem("dexTrader_marketRefreshInterval", n.toString());
    }
  };

  const updateAgentCacheDuration = (n: number) => {
    setAgentCacheDuration(n);
    if (typeof window !== "undefined") {
      localStorage.setItem("dexTrader_agentCacheDuration", n.toString());
    }
  };

  const updateAutoTrading = (b: boolean) => {
    setAutoTrading(b);
    if (typeof window !== "undefined") {
      localStorage.setItem("dexTrader_autoTrading", b.toString());
    }
  };

  const updateAutoTradingInterval = (n: number) => {
    setAutoTradingInterval(n);
    if (typeof window !== "undefined") {
      localStorage.setItem("dexTrader_autoTradingInterval", n.toString());
    }
  };

  const format = (usdValue: number) => {
    if (currency === "EUR") {
      return `€${(usdValue * rate).toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })}`;
    }
    return `$${usdValue.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`;
  };

  return (
    <SettingsContext.Provider 
      value={{ 
        currency, 
        setCurrency: updateCurrency, 
        network,
        setNetwork: updateNetwork,
        pollingInterval, 
        setPollingInterval: updatePollingInterval,
        marketRefreshInterval,
        setMarketRefreshInterval: updateMarketRefreshInterval,
        agentCacheDuration,
        setAgentCacheDuration: updateAgentCacheDuration,
        autoTrading,
        setAutoTrading: updateAutoTrading,
        autoTradingInterval,
        setAutoTradingInterval: updateAutoTradingInterval,
        rate, 
        format 
      }}
    >
      {children}
    </SettingsContext.Provider>
  );
}

export const useSettings = () => {
  const context = useContext(SettingsContext);
  if (!context) {
    throw new Error("useSettings must be used within SettingsProvider");
  }
  return context;
};
