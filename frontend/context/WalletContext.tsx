"use client";
import React, { createContext, useContext, useState, useEffect, useRef, ReactNode } from "react";

interface WalletContextType {
  address: string | null;
  chainId: number | null;
  connecting: boolean;
  error: string | null;
  connect: () => Promise<void>;
  disconnect: () => void;
}

const WalletContext = createContext<WalletContextType | undefined>(undefined);

function parseChainId(value: unknown): number | null {
  if (typeof value !== "string" || !/^0x[0-9a-f]+$/i.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

export function WalletProvider({ children }: { children: ReactNode }) {
  const [address, setAddress] = useState<string | null>(null);
  const [chainId, setChainId] = useState<number | null>(null);
  const chainRevision = useRef(0);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function readChainId(ethereum: any) {
    const revision = ++chainRevision.current;
    try {
      const value = await ethereum.request({ method: "eth_chainId" });
      if (revision === chainRevision.current) setChainId(parseChainId(value));
    } catch {
      if (revision === chainRevision.current) setChainId(null);
    }
  }

  useEffect(() => {
    if (typeof window !== "undefined" && (window as any).ethereum) {
      const ethereum = (window as any).ethereum;
      
      // Check if already connected
      ethereum.request({ method: "eth_accounts" }).then((accounts: string[]) => {
        if (accounts.length > 0) {
          setAddress(accounts[0]);
        }
      }).catch(() => {
        // Ignore error on initial check
      });

      const handleAccountsChanged = (accounts: string[]) => {
        if (accounts.length > 0) {
          setAddress(accounts[0]);
        } else {
          setAddress(null);
        }
      };
      
      const handleChainChanged = (value: string) => {
        ++chainRevision.current;
        setChainId(parseChainId(value));
      };
      readChainId(ethereum);
      ethereum.on("accountsChanged", handleAccountsChanged);
      ethereum.on("chainChanged", handleChainChanged);
      return () => {
        ++chainRevision.current;
        ethereum.removeListener("accountsChanged", handleAccountsChanged);
        ethereum.removeListener("chainChanged", handleChainChanged);
      };
    }
  }, []);

  async function connect() {
    const ethereum = (window as any).ethereum;
    if (!ethereum) {
      setError("No injected wallet detected");
      return;
    }
    try {
      setError(null);
      setConnecting(true);
      const accounts = await ethereum.request({
        method: "eth_requestAccounts"
      });
      const account = Array.isArray(accounts) ? accounts[0] : null;
      if (account) {
        setAddress(account);
        await readChainId(ethereum);
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to connect wallet"
      );
    } finally {
      setConnecting(false);
    }
  }

  function disconnect() {
    setAddress(null);
  }

  return (
    <WalletContext.Provider value={{ address, chainId, connecting, error, connect, disconnect }}>
      {children}
    </WalletContext.Provider>
  );
}

export function useWallet() {
  const context = useContext(WalletContext);
  if (context === undefined) {
    throw new Error("useWallet must be used within a WalletProvider");
  }
  return context;
}
