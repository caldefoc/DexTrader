import "./globals.css";
import type { ReactNode } from "react";
import Navbar from "../components/Navbar";
import { WalletProvider } from "../context/WalletContext";
import { SignalsProvider } from "../context/SignalsContext";
import { SettingsProvider } from "../context/SettingsContext";
import { MarketDataProvider } from "../context/MarketDataContext";
import AutoTradingProvider from "../components/AutoTradingProvider";

export const metadata = {
  title: "DexTrader",
  description: "Non-custodial DEX trading assistant"
};

export default function RootLayout(props: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <WalletProvider>
          <SettingsProvider>
            <MarketDataProvider>
              <SignalsProvider>
                <AutoTradingProvider>
                  <div className="min-h-screen flex flex-col">
                    <Navbar />
                    <main className="flex-1 container mx-auto px-4 py-6">
                      {props.children}
                    </main>
                  </div>
                </AutoTradingProvider>
              </SignalsProvider>
            </MarketDataProvider>
          </SettingsProvider>
        </WalletProvider>
      </body>
    </html>
  );
}
