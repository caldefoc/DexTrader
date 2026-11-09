"use client";
import { useEffect, useState, useRef } from "react";
import { useWallet } from "../context/WalletContext";
import { BrowserProvider, Contract, formatUnits } from "ethers";
import { SEPOLIA_TOKENS, MAINNET_TOKENS, BASE_TOKENS, BASE_TOKEN_DECIMALS, ARBITRUM_TOKENS } from "../constants/tokens";
import { useSettings } from "../context/SettingsContext";
import TradePreviewModal from "./TradePreviewModal";
import { AUTO_TRADE_TARGETS } from "../lib/autoTradeExecutor";
import { BACKEND_URL } from "../constants/config";

type AgentStatus = {
  running: boolean;
  current_step: string | null;
  last_run: number | null;
  monitored_tokens?: string[];
  halted?: boolean;
  halt_reason?: string | null;
  equity?: number | null;
  day_start_equity?: number | null;
  drawdown_pct?: number | null;
  trades_today?: number;
  max_daily_trades?: number;
};

type AuditLog = {
  timestamp: number;
  agent: string;
  message: string;
  level: "INFO" | "WARNING" | "ERROR";
  data: any;
};

type TradeProposal = {
  id: string;
  token: string;
  action: "buy" | "sell";
  amount: number;
  price: number;
  reason?: string;
  slippage: number;
  gas_limit: number;
  status: "pending" | "approved" | "rejected" | "executed";
  timestamp: number;
  pct_change?: number;
  auto_tradeable?: boolean;
  notional_usd?: number;
  exit_kind?: string | null;
  sell_fraction?: number | null;
};

export default function AgentsControlPanel() {
  const { address } = useWallet();
  const { network, autoTrading } = useSettings();
  const currentNetworkTokens = network === "mainnet" ? MAINNET_TOKENS : network === "base" ? BASE_TOKENS : network === "arbitrum" ? ARBITRUM_TOKENS : SEPOLIA_TOKENS;

  // Fetch holdings logic duplicated from Portfolio for now, or just send what we have
  const [holdingsMap, setHoldingsMap] = useState<Record<string, number>>({});
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [proposals, setProposals] = useState<TradeProposal[]>([]);
  const [loading, setLoading] = useState(false);
  const [tokensInput, setTokensInput] = useState("ETH, WETH, VVV, SHIB, DEGEN, TOSHI, VIRTUAL, AVNT, AERO, AIXBT, TIBBIR, ARB");
  
  const [previewOpen, setPreviewOpen] = useState(false);
  const [selectedProposal, setSelectedProposal] = useState<TradeProposal | null>(null);
  
  const pollTimer = useRef<NodeJS.Timeout | null>(null);

  // Fetch holdings to send to agents
  useEffect(() => {
      async function loadHoldings() {
          if (!address || typeof window === "undefined" || !(window as any).ethereum) {
              setHoldingsMap({});
              return;
          }
          try {
              const provider = new BrowserProvider((window as any).ethereum);
              const tokens = network === "mainnet" ? MAINNET_TOKENS : network === "base" ? BASE_TOKENS : network === "arbitrum" ? ARBITRUM_TOKENS : SEPOLIA_TOKENS;
              
              const map: Record<string, number> = {};
              
              // Add ETH
              const ethBal = await provider.getBalance(address);
              if (ethBal > BigInt(0)) {
                  map["ETH"] = parseFloat(formatUnits(ethBal, 18));
              }

              // Check other tokens
              for (const [symbol, addr] of Object.entries(tokens)) {
                  // Skip if address is invalid or not string
                  if (!addr || typeof addr !== 'string') continue;
                  
                  try {
                      const c = new Contract(addr, ["function balanceOf(address) view returns (uint256)", "function decimals() view returns (uint8)"], provider);
                      const bal = await c.balanceOf(address);
                      if (bal > BigInt(0)) {
                          let decimals = network === "base" ? BASE_TOKEN_DECIMALS[symbol] ?? 18 : 18;
                          try { decimals = Number(await c.decimals()); } catch {}
                          map[symbol] = parseFloat(formatUnits(bal, decimals));
                      }
                  } catch (e) {
                      console.warn(`Failed to fetch balance for ${symbol}`, e);
                  }
              }
              console.log("Loaded holdings map:", map);
              setHoldingsMap(map);
          } catch (e) {
              console.error("Agent panel failed to load holdings", e);
          }
      }
      loadHoldings();
  }, [address, network]);

  // Sync holdings to backend whenever they change (ensures agents always have current wallet balances)
  useEffect(() => {
      async function syncHoldingsToBackend() {
          // Only sync if we have holdings data
          if (Object.keys(holdingsMap).length === 0) return;
          
          try {
              console.log("Syncing holdings to agents:", holdingsMap);
              await fetch(`${BACKEND_URL}/agents/holdings`, {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify(holdingsMap)
              });
          } catch (e) {
              console.error("Failed to sync holdings to agents", e);
          }
      }
      syncHoldingsToBackend();
  }, [holdingsMap]);

  const fetchStatus = async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/agents/status`);
      if (res.ok) {
        const s = await res.json();
        setStatus(s);
        // Only sync input from backend if agents are currently running
        if (s.running && s.monitored_tokens && s.monitored_tokens.length > 0) {
             setTokensInput(s.monitored_tokens.join(", "));
        }
      }
      
      const logsRes = await fetch(`${BACKEND_URL}/agents/logs`);
      if (logsRes.ok) setLogs(await logsRes.json());
      
      const propRes = await fetch(`${BACKEND_URL}/agents/proposals`);
      if (propRes.ok) {
          const fetchedProposals = await propRes.json();
          setProposals(fetchedProposals);
          // Debug logging to console to help troubleshoot why proposals aren't showing
          console.log("Fetched proposals:", fetchedProposals);
      }
      
    } catch (e) {
      console.error("Failed to fetch agent status", e);
    }
  };

  useEffect(() => {
    fetchStatus();
    pollTimer.current = setInterval(fetchStatus, 2000); // Poll every 2s
    return () => {
      if (pollTimer.current) clearInterval(pollTimer.current);
    };
  }, []);

  const toggleAgents = async () => {
    setLoading(true);
    try {
      const endpoint = status?.running ? "stop" : "start";
      
      let body: any = {};
      if (!status?.running) {
         // Log the holdings being sent for debugging
         console.log("Starting agents with holdings:", holdingsMap);
         
         body = { 
             interval_seconds: 60, // 1 minute samples for RSI/VWAP warm-up
             monitored_tokens: tokensInput.split(",").map(t => t.trim()).filter(t => t.length > 0),
             user_holdings: holdingsMap
         };
      }
      
      await fetch(`${BACKEND_URL}/agents/${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      
      await fetchStatus();
    } catch (e) {
      console.error("Failed to toggle agents", e);
    } finally {
      setLoading(false);
    }
  };

  const executeProposal = async (proposal: TradeProposal) => {
    if (!address) {
        alert("Please connect wallet first");
        return;
    }
    setSelectedProposal(proposal);
    setPreviewOpen(true);
  };

  const toggleHalt = async () => {
    try {
      const endpoint = status?.halted ? "resume" : "halt";
      await fetch(`${BACKEND_URL}/agents/${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: "Kill switch from dashboard" }),
      });
      await fetchStatus();
    } catch (e) {
      console.error("Failed to toggle kill switch", e);
    }
  };

  const handleTradeSuccess = async (txHash?: string) => {
      if (selectedProposal) {
          try {
              await fetch(`${BACKEND_URL}/agents/proposals/${selectedProposal.id}/complete`, {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ tx_hash: txHash })
              });
              // Refresh status
              fetchStatus();
          } catch (e) {
              console.error("Failed to update proposal status", e);
          }
      }
      // Do not close immediately, let the modal show success screen
      // setPreviewOpen(false);
      // setSelectedProposal(null);
  };

  const rejectProposal = async (proposalId: string) => {
      try {
          await fetch(`${BACKEND_URL}/agents/proposals/${proposalId}/reject`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({})
          });
          fetchStatus();
      } catch (e) {
          console.error("Failed to reject proposal", e);
      }
  };

  const initialAmount = selectedProposal 
    ? (selectedProposal.action === "buy" 
        // For BUY: We want to spend Quote currency (approx USD value)
        ? (selectedProposal.amount * selectedProposal.price).toFixed(6)
        // For SELL: We are selling the Token amount
        : selectedProposal.amount.toString())
    : "";
    
  // Map proposal to signal
  const tradeSignal = selectedProposal ? {
      pair: `${selectedProposal.token}/USDC`, // Base/Quote
      action: selectedProposal.action,
      confidence: 1.0
  } : null;

  const activeProposals = proposals.filter(p => p.status === "pending" || p.status === "approved");

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 h-[calc(100vh-7rem)]">
      {/* Left Column: Controller (Narrower ~25%) */}
      <div className="lg:col-span-3 h-full min-h-0">
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 h-full flex flex-col overflow-hidden">
          <h2 className="text-xl font-bold mb-4 shrink-0">Controller</h2>
          
          <div className="flex items-center justify-between mb-4 shrink-0">
            <span className="text-gray-400">Status</span>
            <div className={`flex items-center gap-2 px-3 py-1 rounded-full text-sm font-medium ${status?.running ? "bg-emerald-500/20 text-emerald-400" : "bg-gray-700/50 text-gray-400"}`}>
              <div className={`w-2 h-2 rounded-full ${status?.running ? "bg-emerald-400 animate-pulse" : "bg-gray-400"}`} />
              {status?.running ? "Running" : "Stopped"}
            </div>
          </div>

          {autoTrading && (
            <div className="flex items-center justify-between mb-4 shrink-0 px-3 py-2 rounded-lg bg-purple-500/10 border border-purple-500/20">
              <span className="text-purple-400 text-sm">Auto-Trading</span>
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-purple-400 animate-pulse" />
                <span className="text-xs text-purple-300">Active</span>
              </div>
            </div>
          )}
          <p className="text-xs text-gray-400 mb-4 shrink-0">
            Automated targets (Base only): {AUTO_TRADE_TARGETS.join(", ")}. USDC is settlement only.
          </p>

          <div className="space-y-4 flex-1 overflow-y-auto custom-scrollbar pr-2">
             <div>
                <span className="text-xs text-gray-500 uppercase">Current Step</span>
                <p className="font-mono text-sm text-gray-200 capitalize">{status?.current_step || "Idle"}</p>
             </div>
             <div>
                <span className="text-xs text-gray-500 uppercase">Last Run</span>
                <p className="font-mono text-sm text-gray-200">
                    {status?.last_run ? new Date(status.last_run * 1000).toLocaleTimeString() : "Never"}
                </p>
             </div>

             <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="bg-slate-950/60 border border-slate-800 rounded p-2">
                    <span className="text-gray-500 uppercase block">Equity</span>
                    <span className="font-mono text-gray-200">
                        {status?.equity != null ? `$${status.equity.toFixed(2)}` : "—"}
                    </span>
                </div>
                <div className="bg-slate-950/60 border border-slate-800 rounded p-2">
                    <span className="text-gray-500 uppercase block">Day P&L</span>
                    <span className={`font-mono ${
                        (status?.drawdown_pct ?? 0) < 0 ? "text-red-400" : "text-emerald-400"
                    }`}>
                        {status?.drawdown_pct != null
                            ? `${(status.drawdown_pct * 100).toFixed(2)}%`
                            : "—"}
                    </span>
                </div>
                <div className="bg-slate-950/60 border border-slate-800 rounded p-2 col-span-2">
                    <span className="text-gray-500 uppercase block">Trades today</span>
                    <span className="font-mono text-gray-200">
                        {status?.trades_today ?? 0} / {status?.max_daily_trades ?? 20}
                    </span>
                </div>
             </div>

             {status?.halted && (
                <div className="rounded border border-red-500/40 bg-red-500/10 p-2 text-xs text-red-300">
                    <span className="font-bold block">Trading halted</span>
                    {status.halt_reason}
                </div>
             )}
          

            <div className="mt-6">
                <label className="text-xs text-gray-500 uppercase block mb-2">Monitored Tokens</label>
                <textarea
                    value={tokensInput}
                    onChange={(e) => setTokensInput(e.target.value)}
                    disabled={status?.running || loading}
                    className="w-full bg-slate-950 border border-slate-800 rounded p-2 text-sm text-gray-200 focus:outline-none focus:border-blue-500 disabled:opacity-50"
                    rows={8}
                    placeholder="ETH, BTC, SOL..."
                />
                <p className="text-[10px] text-gray-500 mt-1">Comma-separated list of symbols.</p>
            </div>
          </div>

          <button
            onClick={toggleAgents}
            disabled={loading || status === null}
            className={`w-full mt-6 py-3 rounded-lg font-bold transition-colors shrink-0 ${
              status === null
                ? "bg-slate-800 text-slate-500 cursor-not-allowed"
                : status.running 
                  ? "bg-red-500/10 text-red-400 hover:bg-red-500/20 border border-red-500/50" 
                  : "bg-emerald-500 text-slate-900 hover:bg-emerald-400"
            }`}
          >
            {loading || status === null ? "Processing..." : status.running ? "Stop Agents" : "Start Agents"}
          </button>

          <button
            onClick={toggleHalt}
            disabled={status === null}
            className={`w-full mt-2 py-2 rounded-lg text-sm font-medium border transition-colors shrink-0 ${
              status?.halted
                ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/40 hover:bg-emerald-500/20"
                : "bg-orange-500/10 text-orange-300 border-orange-500/40 hover:bg-orange-500/20"
            }`}
          >
            {status?.halted ? "Resume Trading" : "Kill Switch (Halt)"}
          </button>
        </div>
      </div>

      {/* Middle Column: Live Logs (Wider ~42%) */}
      <div className="lg:col-span-5 h-full min-h-0">
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 h-full flex flex-col overflow-hidden">
            <h2 className="text-xl font-bold mb-4 flex items-center gap-2 shrink-0">
                <span>System Logs</span>
                <span className="text-xs font-normal text-gray-500 bg-slate-800 px-2 py-0.5 rounded-full">{logs.length} events</span>
            </h2>
            
            <div className="flex-1 overflow-y-auto font-mono text-xs space-y-1 p-2 bg-slate-950 rounded border border-slate-800 custom-scrollbar">
                {logs.length === 0 && <div className="text-gray-500 p-4 text-center">No logs available</div>}
                {logs.map((log, i) => (
                    <div key={i} className="flex gap-2 hover:bg-slate-900/50 p-1 rounded">
                        <span className="text-gray-500 shrink-0 w-20">
                            {new Date(log.timestamp * 1000).toLocaleTimeString()}
                        </span>
                        <span className={`shrink-0 w-24 font-bold ${
                            log.agent === "Risk" ? "text-orange-400" :
                            log.agent === "Execution" ? "text-purple-400" :
                            log.agent === "Analysis" ? "text-blue-400" :
                            "text-gray-300"
                        }`}>
                            [{log.agent}]
                        </span>
                        <span className={`${
                            log.level === "ERROR" ? "text-red-500 font-bold" :
                            log.level === "WARNING" ? "text-yellow-400" :
                            "text-gray-300"
                        }`}>
                            {log.message}
                        </span>
                        {log.data && (
                            <details className="text-gray-600 cursor-pointer">
                                <summary>data</summary>
                                <pre className="mt-1 p-2 bg-black rounded text-[10px] text-gray-400 overflow-x-auto">
                                    {JSON.stringify(log.data, null, 2)}
                                </pre>
                            </details>
                        )}
                    </div>
                ))}
            </div>
        </div>
      </div>

      {/* Right Column: Active Proposals (Standard ~33%) */}
      <div className="lg:col-span-4 h-full min-h-0">
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 h-full flex flex-col overflow-hidden">
            <h2 className="text-lg font-bold mb-4 shrink-0 flex justify-between items-center">
                <span>Active Proposals</span>
                <span className="text-xs font-normal text-gray-500 bg-slate-800 px-2 py-0.5 rounded-full">{activeProposals.length} active</span>
            </h2>
            {proposals.length > 0 && activeProposals.length === 0 && (
                <div className="mb-4 p-2 bg-slate-950/50 border border-slate-800 rounded text-xs text-gray-500">
                    <p>No active proposals. Check System Logs for rejected proposals.</p>
                </div>
            )}
            {activeProposals.length === 0 ? (
                <p className="text-sm text-gray-500">No pending trade proposals.</p>
            ) : (
                <div className="space-y-3 flex-1 overflow-y-auto custom-scrollbar pr-2">
                    {[...activeProposals]
                        .reverse()
                        .map(p => {
                            const isWrongNetwork = !currentNetworkTokens[p.token] && p.token !== "ETH";
                            return (
                        <div key={p.id} className={`p-3 rounded border ${isWrongNetwork ? 'bg-slate-900/50 border-yellow-900/30' : 'bg-slate-950/50 border-slate-800'}`}>
                            <div className="flex justify-between items-center mb-2">
                                <span className={`font-bold ${p.action === "buy" ? "text-emerald-400" : "text-red-400"}`}>
                                    {p.action.toUpperCase()} {p.token}
                                </span>
                                {p.auto_tradeable === false && (
                                    <span className="text-[9px] uppercase tracking-wide text-yellow-500 border border-yellow-700/50 rounded px-1 py-0.5">
                                        manual only
                                    </span>
                                )}
                                <span className="text-xs text-gray-500">{new Date(p.timestamp * 1000).toLocaleTimeString()}</span>
                            </div>
                            {isWrongNetwork && (
                                <div className="mb-2 text-[10px] text-yellow-500 flex items-center gap-1">
                                    <span>⚠️ Different Network</span>
                                </div>
                            )}
                            <div className="text-xs text-gray-300 mb-3 flex items-center gap-2">
                                <span>Amount: {p.amount.toLocaleString(undefined, { maximumFractionDigits: 4 })}</span>
                                <span className="text-gray-500">|</span>
                                <span>Price: {
                                    p.price < 0.01 
                                    ? `$${p.price.toFixed(8)}` 
                                    : `$${p.price.toFixed(2)}`
                                }</span>
                                {p.pct_change !== undefined && (
                                    <>
                                        <span className="text-gray-500">|</span>
                                        <span className={`${p.pct_change >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                                            Change {p.pct_change > 0 ? "+" : ""}{p.pct_change.toFixed(2)}%
                                        </span>
                                    </>
                                )}
                            </div>
                            {p.reason && (
                                <div className="text-[11px] text-gray-400 mb-3 bg-slate-900/50 p-1 rounded border border-slate-800">
                                    {p.reason}
                                </div>
                            )}
                            <div className="flex gap-2">
                                <button 
                                    onClick={() => executeProposal(p)}
                                    className="w-[60%] py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs rounded font-medium"
                                >
                                    Review & Sign
                                </button>
                                <button
                                    onClick={() => rejectProposal(p.id)}
                                    className="flex-1 py-1.5 bg-red-500/10 hover:bg-red-500/20 text-red-400 text-xs rounded font-medium border border-red-500/20 transition-colors"
                                    title="Reject Proposal"
                                >
                                    Reject
                                </button>
                            </div>
                        </div>
                        ); })}
                </div>
            )}
        </div>
      </div>

      <TradePreviewModal 
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        signal={tradeSignal}
        initialAmount={initialAmount}
        initialSlippage={selectedProposal?.slippage}
        onSuccess={handleTradeSuccess}
      />
    </div>
  );
}
