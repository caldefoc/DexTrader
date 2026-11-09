"use client";
import { useState, useEffect } from "react";
import { useSettings } from "../context/SettingsContext";
import { BACKEND_URL } from "../constants/config";

type TradeExecution = {
  tx_hash: string;
  network: string;
  pair: string;
  action: string;
  amount: number;
  token: string;
  price: number;
  token_amount: number;
  price_usd?: number;
  network_fee: number;
  status: string;
  timestamp: number;
};

// Uniform trade record standard: `amount` is always denominated in the pair's
// quote currency, and `token` names that currency. Convert to USD for display.
const QUOTE_USD_RATES: Record<string, number> = {
  ETH: 3000, WETH: 3000, USDC: 1, USDT: 1, DAI: 1,
};
const tradeAmountUSD = (t: TradeExecution) =>
  t.price_usd && t.token_amount
    ? t.token_amount * t.price_usd
    : t.amount * (QUOTE_USD_RATES[t.token] ?? 1);

export default function SettingsForm() {
  const { 
    currency, setCurrency, rate, 
    network, setNetwork,
    pollingInterval, setPollingInterval, 
    marketRefreshInterval, setMarketRefreshInterval,
    agentCacheDuration, setAgentCacheDuration,
    autoTrading, setAutoTrading,
    autoTradingInterval, setAutoTradingInterval 
  } = useSettings();

  const [agentStatus, setAgentStatus] = useState<{ running: boolean } | null>(null);
  const [showReportModal, setShowReportModal] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [reportData, setReportData] = useState<TradeExecution[]>([]);
  const [filters, setFilters] = useState({
    network: "all",
    action: "all",
    startDate: "",
    endDate: ""
  });

  useEffect(() => {
    fetch(`${BACKEND_URL}/agents/status`)
      .then(res => res.json())
      .then(data => setAgentStatus(data))
      .catch(console.error);
  }, []);

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-white">Settings</h2>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* General Settings Card */}
        <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800 h-full">
          <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-5 h-5 text-blue-400">
              <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 6h9.75M10.5 6a1.5 1.5 0 1 1-3 0m3 0a1.5 1.5 0 1 0-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m-9.75 0h9.75" />
            </svg>
            General
          </h3>
          
          <div className="space-y-6">
            {/* Network Selection */}
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-3">
                Blockchain Network
              </label>
              <div className="flex gap-3">
                <button
                  onClick={() => setNetwork("sepolia")}
                  className={`flex-1 py-2.5 rounded-lg border text-sm font-medium transition-all ${
                    network === "sepolia"
                      ? "bg-purple-600 border-purple-500 text-white shadow-lg shadow-purple-900/20"
                      : "bg-slate-800 border-slate-700 text-gray-400 hover:bg-slate-700 hover:text-gray-200"
                  }`}
                >
                  Sepolia (Testnet)
                </button>
                <button
                  onClick={() => setNetwork("mainnet")}
                  className={`flex-1 py-2.5 rounded-lg border text-sm font-medium transition-all ${
                    network === "mainnet"
                      ? "bg-green-600 border-green-500 text-white shadow-lg shadow-green-900/20"
                      : "bg-slate-800 border-slate-700 text-gray-400 hover:bg-slate-700 hover:text-gray-200"
                  }`}
                >
                  Ethereum
                </button>
                <button
                  onClick={() => setNetwork("base")}
                  className={`flex-1 py-2.5 rounded-lg border text-sm font-medium transition-all ${
                    network === "base"
                      ? "bg-blue-600 border-blue-500 text-white shadow-lg shadow-blue-900/20"
                      : "bg-slate-800 border-slate-700 text-gray-400 hover:bg-slate-700 hover:text-gray-200"
                  }`}
                >
                  Base
                </button>
                <button
                  onClick={() => setNetwork("arbitrum")}
                  className={`flex-1 py-2.5 rounded-lg border text-sm font-medium transition-all ${
                    network === "arbitrum"
                      ? "bg-cyan-600 border-cyan-500 text-white shadow-lg shadow-cyan-900/20"
                      : "bg-slate-800 border-slate-700 text-gray-400 hover:bg-slate-700 hover:text-gray-200"
                  }`}
                >
                  Arbitrum
                </button>
              </div>
              <p className="text-xs text-gray-500 mt-2">
                {network === "mainnet" || network === "base" || network === "arbitrum"
                  ? `⚠️ Warning: You are on ${network === "base" ? "Base" : network === "arbitrum" ? "Arbitrum" : "Mainnet"}. Real funds will be used.` 
                  : "Safe environment for testing strategies without real funds."}
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-400 mb-3">
                Display Currency
              </label>
              <div className="flex gap-3">
                <button
                  onClick={() => setCurrency("USD")}
                  className={`flex-1 py-2.5 rounded-lg border text-sm font-medium transition-all ${
                    currency === "USD"
                      ? "bg-blue-600 border-blue-500 text-white shadow-lg shadow-blue-900/20"
                      : "bg-slate-800 border-slate-700 text-gray-400 hover:bg-slate-700 hover:text-gray-200"
                  }`}
                >
                  USD ($)
                </button>
                <button
                  onClick={() => setCurrency("EUR")}
                  className={`flex-1 py-2.5 rounded-lg border text-sm font-medium transition-all ${
                    currency === "EUR"
                      ? "bg-blue-600 border-blue-500 text-white shadow-lg shadow-blue-900/20"
                      : "bg-slate-800 border-slate-700 text-gray-400 hover:bg-slate-700 hover:text-gray-200"
                  }`}
                >
                  EUR (€)
                </button>
              </div>
              {currency === "EUR" && (
                <div className="mt-3 p-3 bg-slate-800/50 rounded-lg border border-slate-700/50">
                  <p className="text-xs text-gray-400 flex justify-between">
                    <span>Exchange Rate:</span>
                    <span className="font-mono text-gray-300">1 USD ≈ {rate.toFixed(4)} EUR</span>
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Agent Configuration Card */}
        <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800 h-full">
          <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-5 h-5 text-purple-400">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.456-2.456L14.25 6l1.035-.259a3.375 3.375 0 0 0 2.456-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 0 0-2.456 2.456ZM16.894 20.567 16.5 21.75l-.394-1.183a2.25 2.25 0 0 0-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 0 0 1.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 0 0 1.423 1.423l1.183.394-1.183.394a2.25 2.25 0 0 0-1.423 1.423Z" />
            </svg>
            Agent Configuration
          </h3>
          
          <div className="space-y-6">
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-2">
                Polling Interval
              </label>
              <div className="flex items-center gap-4">
                 <div className="relative flex-1">
                    <input
                      type="number"
                      min={0}
                      max={3600}
                      value={pollingInterval}
                      onChange={(e) => setPollingInterval(Math.max(0, Number(e.target.value)))}
                      className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-4 pr-12 py-2.5 text-white focus:outline-none focus:border-purple-500 transition-colors"
                    />
                    <span className="absolute right-4 top-2.5 text-gray-500 text-sm">sec</span>
                 </div>
                 <button
                    onClick={() => setPollingInterval(pollingInterval === 0 ? 300 : 0)}
                    className={`px-4 py-2.5 rounded-lg border text-sm font-medium transition-colors ${
                       pollingInterval === 0 
                        ? "bg-red-500/10 border-red-500/30 text-red-400 hover:bg-red-500/20"
                        : "bg-slate-800 border-slate-700 text-gray-400 hover:bg-slate-700"
                    }`}
                 >
                    {pollingInterval === 0 ? "Disabled" : "Disable"}
                 </button>
              </div>
              <p className="text-xs text-gray-500 mt-2">
                Frequency of agent analysis updates (0 to disable auto-refresh)
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-400 mb-2">
                Market Data Refresh
              </label>
              <div className="flex items-center gap-4">
                 <div className="relative flex-1">
                    <input
                      type="number"
                      min={0}
                      max={3600}
                      value={marketRefreshInterval}
                      onChange={(e) => setMarketRefreshInterval(Math.max(0, Number(e.target.value)))}
                      className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-4 pr-12 py-2.5 text-white focus:outline-none focus:border-purple-500 transition-colors"
                    />
                    <span className="absolute right-4 top-2.5 text-gray-500 text-sm">sec</span>
                 </div>
                 <button
                    onClick={() => setMarketRefreshInterval(marketRefreshInterval === 0 ? 300 : 0)}
                    className={`px-4 py-2.5 rounded-lg border text-sm font-medium transition-colors ${
                       marketRefreshInterval === 0 
                        ? "bg-red-500/10 border-red-500/30 text-red-400 hover:bg-red-500/20"
                        : "bg-slate-800 border-slate-700 text-gray-400 hover:bg-slate-700"
                    }`}
                 >
                    {marketRefreshInterval === 0 ? "Disabled" : "Disable"}
                 </button>
              </div>
              <p className="text-xs text-gray-500 mt-2">
                Frequency of CoinMarketCap API calls (0 to disable auto-refresh)
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-400 mb-2">
                Agent Cache Duration
              </label>
              <div className="flex items-center gap-4">
                 <div className="relative flex-1">
                    <input
                      type="number"
                      min={60}
                      max={86400}
                      value={agentCacheDuration}
                      onChange={(e) => {
                        const newValue = Math.max(60, Number(e.target.value));
                        setAgentCacheDuration(newValue);
                        if (typeof window !== "undefined") {
                          localStorage.setItem("dexTrader_agentCacheDuration", newValue.toString());
                          
                          // Send the setting to the backend
                          fetch(`${BACKEND_URL}/agents/config/cache-duration`, {
                            method: "POST",
                            headers: {
                              "Content-Type": "application/json",
                            },
                            body: JSON.stringify({ duration: newValue }),
                          }).catch(error => {
                            console.error("Failed to update agent cache duration on backend:", error);
                          });
                        }
                      }}
                      className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-4 pr-12 py-2.5 text-white focus:outline-none focus:border-purple-500 transition-colors"
                    />
                    <span className="absolute right-4 top-2.5 text-gray-500 text-sm">sec</span>
                 </div>
                 <button
                    onClick={() => {
                      const newValue = agentCacheDuration === 300 ? 3600 : 300;
                      setAgentCacheDuration(newValue);
                      if (typeof window !== "undefined") {
                        localStorage.setItem("dexTrader_agentCacheDuration", newValue.toString());
                        
                        // Send the setting to the backend
                        fetch(`${BACKEND_URL}/agents/config/cache-duration`, {
                          method: "POST",
                          headers: {
                            "Content-Type": "application/json",
                          },
                          body: JSON.stringify({ duration: newValue }),
                        }).catch(error => {
                          console.error("Failed to update agent cache duration on backend:", error);
                        });
                      }
                    }}
                    className={`px-4 py-2.5 rounded-lg border text-sm font-medium transition-colors ${
                       agentCacheDuration === 300 
                        ? "bg-purple-600 border-purple-500 text-white"
                        : "bg-slate-800 border-slate-700 text-gray-400 hover:bg-slate-700"
                    }`}
                 >
                    {agentCacheDuration === 300 ? "5 min" : "1 hr"}
                 </button>
              </div>
              <p className="text-xs text-gray-500 mt-2">
                How long agents use cached market data (minimum 60 seconds)
              </p>
            </div>

            <div className="pt-4 border-t border-slate-800">
              <div className="flex items-center justify-between mb-2">
                <label className="text-sm font-medium text-gray-400">
                  Automatic Trading
                </label>
                <button
                  onClick={() => setAutoTrading(!autoTrading)}
                  className={`w-11 h-6 rounded-full transition-colors relative ${
                    autoTrading ? "bg-purple-600" : "bg-slate-700"
                  }`}
                >
                  <div className={`absolute top-1 left-1 w-4 h-4 rounded-full bg-white transition-transform ${
                    autoTrading ? "translate-x-5" : ""
                  }`} />
                </button>
              </div>
              <p className="text-xs text-gray-500">
                Automatically execute high-confidence signals
              </p>

              {autoTrading && (
                <div className="mt-3 pt-3 border-t border-slate-800/50">
                  <div className="flex items-center justify-between mb-2">
                    <label className="text-xs text-gray-500">
                      Check Interval
                    </label>
                    <select
                      value={autoTradingInterval}
                      onChange={(e) => setAutoTradingInterval(Number(e.target.value))}
                      className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-gray-300 focus:outline-none focus:border-blue-500"
                    >
                      <option value={60}>1 minute</option>
                      <option value={300}>5 minutes</option>
                      <option value={600}>10 minutes</option>
                      <option value={900}>15 minutes</option>
                      <option value={1800}>30 minutes</option>
                    </select>
                  </div>
                  <p className="text-[10px] text-gray-600">
                    How often to check for new trade proposals
                  </p>
                </div>
              )}
            </div>

            {agentStatus && (
              <div className="pt-4 border-t border-slate-800">
                <div className="flex items-center justify-between mb-2">
                  <label className="text-sm font-medium text-gray-400">
                    Agent Process
                  </label>
                  <span className={`text-sm font-medium ${agentStatus.running ? "text-emerald-400" : "text-gray-500"}`}>
                    {agentStatus.running ? "Running" : "Stopped"}
                  </span>
                </div>
                <p className="text-xs text-gray-500">
                  Status of the background market analysis agent
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Reports Card */}
        <div className="md:col-span-2 bg-slate-900/50 p-6 rounded-xl border border-slate-800">
          <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-5 h-5 text-emerald-400">
              <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
            </svg>
            Daily Reports
          </h3>
          
          <div className="flex items-center justify-between gap-6">
            <p className="text-sm text-gray-400 max-w-lg">
              Generate a summary of trading performance, including PnL analysis and execution history for the current session.
            </p>
            <button
              onClick={() => setShowReportModal(true)}
              className="whitespace-nowrap bg-slate-800 hover:bg-slate-700 border border-slate-700 text-emerald-400 hover:text-emerald-300 rounded-lg px-6 py-2.5 transition-colors font-medium text-sm flex items-center gap-2"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                <path fillRule="evenodd" d="M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm.75-11.25a.75.75 0 0 0-1.5 0v2.5h-2.5a.75.75 0 0 0 0 1.5h2.5v2.5a.75.75 0 0 0 1.5 0v-2.5h2.5a.75.75 0 0 0 0-1.5h-2.5v-2.5Z" clipRule="evenodd" />
              </svg>
              Generate Report
            </button>
          </div>
        </div>
      </div>

      {/* Report Modal */}
      {showReportModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-4xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden">
            {/* Modal Header */}
            <div className="p-6 border-b border-slate-800 flex justify-between items-center bg-slate-900/50">
              <h3 className="text-xl font-bold text-white flex items-center gap-2">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-6 h-6 text-emerald-400">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
                </svg>
                Trading Report Generator
              </h3>
              <button 
                onClick={() => {
                  setShowReportModal(false);
                  setReportData([]);
                }}
                className="text-gray-500 hover:text-white transition-colors"
              >
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-6 h-6">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-6 overflow-y-auto flex-1 space-y-6">
              {/* Filters Section */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 bg-slate-800/30 p-4 rounded-xl border border-slate-700/50">
                <div className="space-y-2">
                  <label className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Network</label>
                  <select 
                    value={filters.network}
                    onChange={(e) => setFilters({...filters, network: e.target.value})}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-emerald-500 transition-colors"
                  >
                    <option value="all">All Networks</option>
                    <option value="mainnet">Ethereum</option>
                    <option value="base">Base</option>
                    <option value="arbitrum">Arbitrum</option>
                    <option value="sepolia">Sepolia</option>
                  </select>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Action</label>
                  <select 
                    value={filters.action}
                    onChange={(e) => setFilters({...filters, action: e.target.value})}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-emerald-500 transition-colors"
                  >
                    <option value="all">All Actions</option>
                    <option value="buy">Buy Only</option>
                    <option value="sell">Sell Only</option>
                  </select>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Start Date</label>
                  <input 
                    type="date"
                    value={filters.startDate}
                    onChange={(e) => setFilters({...filters, startDate: e.target.value})}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-emerald-500 transition-colors [color-scheme:dark]"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold text-gray-400 uppercase tracking-wider">End Date</label>
                  <input 
                    type="date"
                    value={filters.endDate}
                    onChange={(e) => setFilters({...filters, endDate: e.target.value})}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-emerald-500 transition-colors [color-scheme:dark]"
                  />
                </div>
              </div>

              <div className="flex justify-center">
                <button
                  disabled={isGenerating}
                  onClick={async () => {
                    setIsGenerating(true);
                    try {
                      const params = new URLSearchParams();
                      if (filters.network !== "all") params.append("network", filters.network);
                      if (filters.action !== "all") params.append("action", filters.action);
                      if (filters.startDate) params.append("start_date", Math.floor(new Date(filters.startDate).getTime() / 1000).toString());
                      if (filters.endDate) params.append("end_date", Math.floor(new Date(filters.endDate).getTime() / 1000 + 86399).toString());
                      
                      const res = await fetch(`${BACKEND_URL}/portfolio/trades?${params.toString()}`);
                      if (!res.ok) throw new Error("Failed to fetch report data");
                      const data = await res.json();
                      setReportData(data);
                    } catch (e) {
                      alert("Error: " + (e instanceof Error ? e.message : "Unknown error"));
                    } finally {
                      setIsGenerating(false);
                    }
                  }}
                  className={`px-8 py-3 rounded-xl font-bold text-white transition-all transform hover:scale-105 active:scale-95 shadow-lg ${
                    isGenerating ? "bg-slate-700 cursor-not-allowed" : "bg-emerald-600 hover:bg-emerald-500 shadow-emerald-900/20"
                  }`}
                >
                  {isGenerating ? "Processing..." : "Run Analysis"}
                </button>
              </div>

              {/* Report Preview */}
              {reportData.length > 0 && (
                <div id="report-content" className="space-y-6">
                  <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 bg-slate-800/50 p-6 rounded-xl border border-slate-700 shadow-inner">
                    <div className="grid grid-cols-2 gap-x-8 gap-y-2 w-full sm:w-auto">
                      <span className="text-gray-400 text-sm">Total Trades:</span>
                      <span className="text-white font-bold text-sm text-right sm:text-left">{reportData.length}</span>
                      <span className="text-gray-400 text-sm">Session PnL:</span>
                      <span className={`font-bold text-sm text-right sm:text-left ${
                        reportData.reduce((acc, t) => acc + (t.action === "sell" ? t.amount : -t.amount), 0) >= 0 
                          ? "text-emerald-400" : "text-red-400"
                      }`}>
                        ${reportData.reduce((acc, t) => acc + (t.action === "sell" ? t.amount : -t.amount), 0).toFixed(2)}
                      </span>
                    </div>
                    <div className="flex gap-2 w-full sm:w-auto">
                      <button 
                        onClick={() => {
                          const content = document.getElementById("report-content");
                          if (!content) return;
                          
                          const printWindow = window.open("", "_blank");
                          if (!printWindow) return;
                          
                          printWindow.document.write(`
                            <html>
                              <head>
                                <title>Trading Report</title>
                                <style>
                                  body { font-family: sans-serif; padding: 40px; color: #333; }
                                  h1 { color: #059669; margin-bottom: 20px; }
                                  table { width: 100%; border-collapse: collapse; margin-top: 20px; }
                                  th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
                                  th { background-color: #f3f4f6; }
                                  .buy { color: #059669; font-weight: bold; }
                                  .sell { color: #dc2626; font-weight: bold; }
                                  .header-info { margin-bottom: 30px; display: grid; grid-template-cols: 1fr 1fr; gap: 20px; }
                                  .box { padding: 15px; border: 1px solid #ddd; border-radius: 8px; }
                                </style>
                              </head>
                              <body>
                                <h1>DexTrader Session Report</h1>
                                <div class="header-info">
                                  <div class="box">
                                    <strong>Report Date:</strong> ${new Date().toLocaleDateString()}<br>
                                    <strong>Filters:</strong> ${filters.network} / ${filters.action}
                                  </div>
                                  <div class="box">
                                    <strong>Total Trades:</strong> ${reportData.length}<br>
                                    <strong>Volume:</strong> $${reportData.reduce((acc, t) => acc + tradeAmountUSD(t), 0).toFixed(2)}
                                  </div>
                                </div>
                                <table>
                                  <thead>
                                    <tr>
                                      <th>Date</th>
                                      <th>Network</th>
                                      <th>Pair</th>
                                      <th>Action</th>
                                      <th>Amount (USD)</th>
                                      <th>Token Amount</th>
                                      <th>Price</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    ${reportData.map(t => `
                                      <tr>
                                        <td>${new Date(t.timestamp * 1000).toLocaleString()}</td>
                                        <td>${t.network}</td>
                                        <td>${t.pair}</td>
                                        <td class="${t.action}">${t.action.toUpperCase()}</td>
                                        <td>$${tradeAmountUSD(t).toFixed(2)}</td>
                                        <td>${t.token_amount.toFixed(6)}</td>
                                        <td>$${t.price.toFixed(6)}</td>
                                      </tr>
                                    `).join("")}
                                  </tbody>
                                </table>
                              </body>
                            </html>
                          `);
                          printWindow.document.close();
                          printWindow.print();
                        }}
                        className="flex-1 sm:flex-none bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-lg text-xs font-bold transition-colors flex items-center justify-center gap-2"
                      >
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                          <path fillRule="evenodd" d="M5 4v3H4a2 2 0 0 0-2 2v3a2 2 0 0 0 2 2h1v2a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2v-2h1a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-1V4a2 2 0 0 0-2-2H7a2 2 0 0 0-2 2Zm8 0H7v3h6V4Zm0 8H7v4h6v-4Z" clipRule="evenodd" />
                        </svg>
                        Print PDF
                      </button>
                      <button 
                        onClick={() => {
                          const text = reportData.map(t => 
                            `${new Date(t.timestamp * 1000).toLocaleString()} | ${t.network} | ${t.pair} | ${t.action.toUpperCase()} | $${tradeAmountUSD(t).toFixed(2)} | ${t.token_amount.toFixed(6)} | $${t.price.toFixed(6)}`
                          ).join("\n");
                          
                          const blob = new Blob([`DexTrader Report - ${new Date().toLocaleString()}\n\n${text}`], { type: "text/plain" });
                          const url = URL.createObjectURL(blob);
                          const a = document.createElement("a");
                          a.href = url;
                          a.download = `trade_report_${Date.now()}.txt`;
                          a.click();
                        }}
                        className="flex-1 sm:flex-none bg-slate-700 hover:bg-slate-600 text-white px-4 py-2 rounded-lg text-xs font-bold transition-colors flex items-center justify-center gap-2"
                      >
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                          <path fillRule="evenodd" d="M4.5 2A1.5 1.5 0 0 0 3 3.5v13A1.5 1.5 0 0 0 4.5 18h11a1.5 1.5 0 0 0 1.5-1.5V7.621a1.5 1.5 0 0 0-.44-1.06l-4.12-4.122A1.5 1.5 0 0 0 11.378 2H4.5Zm2.25 8.5a.75.75 0 0 0 0 1.5h6.5a.75.75 0 0 0 0-1.5h-6.5Zm0 3a.75.75 0 0 0 0 1.5h6.5a.75.75 0 0 0 0-1.5h-6.5Z" clipRule="evenodd" />
                        </svg>
                        Export Text
                      </button>
                    </div>
                  </div>

                  <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-950/40">
                    <table className="w-full text-left border-collapse">
                      <thead>
                        <tr className="bg-slate-900/80">
                          <th className="px-4 py-3 text-xs font-bold text-gray-400 uppercase tracking-wider">Date</th>
                          <th className="px-4 py-3 text-xs font-bold text-gray-400 uppercase tracking-wider">Network</th>
                          <th className="px-4 py-3 text-xs font-bold text-gray-400 uppercase tracking-wider">Pair</th>
                          <th className="px-4 py-3 text-xs font-bold text-gray-400 uppercase tracking-wider">Action</th>
                          <th className="px-4 py-3 text-xs font-bold text-gray-400 uppercase tracking-wider text-right">Amount (USD)</th>
                          <th className="px-4 py-3 text-xs font-bold text-gray-400 uppercase tracking-wider text-right">Price</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800">
                        {reportData.map((t, i) => (
                          <tr key={t.tx_hash + i} className="hover:bg-slate-800/30 transition-colors">
                            <td className="px-4 py-3 text-xs text-gray-300 font-mono">{new Date(t.timestamp * 1000).toLocaleDateString()}</td>
                            <td className="px-4 py-3 text-xs text-gray-300 capitalize">{t.network}</td>
                            <td className="px-4 py-3 text-xs text-white font-semibold">{t.pair}</td>
                            <td className="px-4 py-3 text-xs">
                              <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                                t.action === "buy" ? "bg-emerald-500/10 text-emerald-400" : "bg-red-500/10 text-red-400"
                              }`}>
                                {t.action.toUpperCase()}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-xs text-right text-gray-300 font-mono">${t.amount.toFixed(2)}</td>
                            <td className="px-4 py-3 text-xs text-right text-gray-400 font-mono">${t.price.toFixed(4)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {reportData.length === 0 && !isGenerating && (
                <div className="flex flex-col items-center justify-center py-12 text-gray-500 bg-slate-800/20 rounded-xl border border-dashed border-slate-700">
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-12 h-12 mb-4 opacity-20">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v6m3-3H9m12 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
                  </svg>
                  <p className="text-sm">Configure filters and run analysis to view results</p>
                </div>
              )}
            </div>

            {/* Modal Footer */}
            <div className="p-4 border-t border-slate-800 bg-slate-900/50 flex justify-end">
              <button 
                onClick={() => {
                  setShowReportModal(false);
                  setReportData([]);
                }}
                className="bg-slate-800 hover:bg-slate-700 text-gray-300 px-6 py-2 rounded-lg text-sm font-semibold transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
