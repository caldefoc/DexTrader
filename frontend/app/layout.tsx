import "./globals.css";
import type { ReactNode } from "react";
import type { Metadata } from "next";
import Navbar from "../components/Navbar";
import DemoBanner from "../components/DemoBanner";
import { WalletProvider } from "../context/WalletContext";
import { SignalsProvider } from "../context/SignalsContext";
import { SettingsProvider } from "../context/SettingsContext";
import { MarketDataProvider } from "../context/MarketDataContext";
import AutoTradingProvider from "../components/AutoTradingProvider";

const SITE_URL = "https://dextrader.caldefoc.com/";
const DESCRIPTION = "Non-custodial DEX trading assistant";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: "DexTrader",
  description: DESCRIPTION,
  icons: {
    icon: [
      { url: "/dextrader-favicon.svg", type: "image/svg+xml" },
      { url: "/dextrader-favicon-32.png", sizes: "32x32", type: "image/png" },
      { url: "/dextrader-favicon-48.png", sizes: "48x48", type: "image/png" },
      { url: "/dextrader-icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: "/dextrader-apple-touch-icon.png",
    shortcut: "/dextrader.ico",
  },
  manifest: "/manifest.webmanifest",
  openGraph: {
    title: "DexTrader",
    description: DESCRIPTION,
    url: SITE_URL,
    siteName: "DexTrader",
    images: [{ url: "/dextrader-og-image.png", width: 1200, height: 630 }],
  },
  twitter: {
    card: "summary_large_image",
    title: "DexTrader",
    description: DESCRIPTION,
    images: ["/dextrader-og-image.png"],
  },
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
                    <DemoBanner />
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
