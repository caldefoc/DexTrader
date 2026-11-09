import { useEffect, useRef, useCallback } from "react";
import { useWallet } from "../context/WalletContext";
import { useSettings } from "../context/SettingsContext";
import { AUTO_TRADE_TARGETS, executeAutoSwap, isAutoTradeEligible } from "../lib/autoTradeExecutor";
import { BACKEND_URL } from "../constants/config";

interface TradeProposal {
  id: string;
  token: string;
  action: "buy" | "sell";
  amount: number;
  price: number;
  pct_change?: number;
  reason?: string;
  status: "pending" | "approved" | "rejected" | "executed";
  slippage: number;
  timestamp: number;
  auto_tradeable?: boolean;
}

export function useAutoTrading() {
  const { address } = useWallet();
  const { autoTrading, network, autoTradingInterval } = useSettings();
  const isRunningRef = useRef(false);
  const processedIdsRef = useRef<Set<string>>(new Set());
  const pollCountRef = useRef(0);

  const executeProposal = useCallback(async (proposal: TradeProposal) => {
    console.log("[AutoTrading] ==========================================");
    console.log("[AutoTrading] EXECUTING PROPOSAL:");
    console.log(`[AutoTrading]   ID: ${proposal.id}`);
    console.log(`[AutoTrading]   Token: ${proposal.token}`);
    console.log(`[AutoTrading]   Action: ${proposal.action}`);
    console.log(`[AutoTrading]   Amount: ${proposal.amount}`);
    console.log(`[AutoTrading]   Price: $${proposal.price}`);
    console.log(`[AutoTrading]   Reason: ${proposal.reason}`);

    // Determine input/output based on action
    let tokenIn: string;
    let tokenOut: string;
    let amountIn: string;

    if (proposal.action === "buy") {
      tokenIn = "USDC";
      tokenOut = proposal.token;
      amountIn = (proposal.amount * proposal.price).toFixed(6);
      console.log(`[AutoTrading]   Trade: Buy ${proposal.token} with ${amountIn} USDC`);
    } else {
      tokenIn = proposal.token;
      tokenOut = "USDC";
      amountIn = proposal.amount.toFixed(6);
      console.log(`[AutoTrading]   Trade: Sell ${amountIn} ${proposal.token} for USDC`);
    }

    // Check eligibility
    if (!isAutoTradeEligible(tokenIn, tokenOut)) {
      console.log(`[AutoTrading] SKIPPED: ${tokenIn} -> ${tokenOut} not in allowed auto-trade pairs`);
      console.log("[AutoTrading] ==========================================");
      return;
    }

    console.log("[AutoTrading] Submitting swap...");
    const result = await executeAutoSwap({
      tokenIn,
      tokenOut,
      amountIn,
      slippage: proposal.slippage?.toString() || "0.5",
      gasPriceGwei: "0.01"
    });

    if (result.success && result.txHash) {
      console.log(`[AutoTrading] SUCCESS! TxHash: ${result.txHash}`);
      try {
        await fetch(`${BACKEND_URL}/agents/proposals/${proposal.id}/complete`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tx_hash: result.txHash }),
        });
        console.log("[AutoTrading] Proposal status updated to 'executed'");
      } catch (e) {
        console.warn("[AutoTrading] Warning: Failed to update proposal status on backend:", e);
      }
    } else {
      console.error("[AutoTrading] FAILED:", result.error);
    }
    console.log("[AutoTrading] ==========================================");
  }, []);

  useEffect(() => {
    console.log("[AutoTrading] Hook mounted. Checking conditions...");
    console.log(`[AutoTrading]   autoTrading: ${autoTrading}`);
    console.log(`[AutoTrading]   address: ${address || "not connected"}`);
    console.log(`[AutoTrading]   network: ${network}`);

    if (!autoTrading) {
      console.log("[AutoTrading] DISABLED - toggle is off");
      isRunningRef.current = false;
      return;
    }
    if (!address) {
      console.log("[AutoTrading] DISABLED - wallet not connected");
      isRunningRef.current = false;
      return;
    }
    if (network !== "base") {
      console.log(`[AutoTrading] DISABLED - wrong network (${network}), need 'base'`);
      isRunningRef.current = false;
      return;
    }

    console.log("[AutoTrading] ENABLED - Starting polling loop");
    console.log(`[AutoTrading] Poll interval: ${autoTradingInterval} seconds`);
    isRunningRef.current = true;
    pollCountRef.current = 0;

    const poll = async () => {
      if (!isRunningRef.current) return;
      pollCountRef.current++;
      const pollNum = pollCountRef.current;

      try {
        console.log(`[AutoTrading] Poll #${pollNum}: Fetching proposals...`);
        const res = await fetch(`${BACKEND_URL}/agents/proposals`);
        if (!res.ok) {
          console.warn(`[AutoTrading] Poll #${pollNum}: Backend returned ${res.status}`);
          return;
        }

        const proposals: TradeProposal[] = await res.json();
        console.log(`[AutoTrading] Poll #${pollNum}: Total proposals: ${proposals.length}`);

        // Staleness guard: after laptop sleep/wake, queued proposals can be
        // hours old. Executing them fires surprise MetaMask popups for trades
        // whose market context is long gone. Drop anything older than
        // max(2x poll interval, 10 minutes).
        const nowSec = Date.now() / 1000;
        const maxAgeSec = Math.max(autoTradingInterval * 2, 600);

        const pending = proposals.filter(
          p => p.status === "pending" && !processedIdsRef.current.has(p.id)
        );
        console.log(`[AutoTrading] Poll #${pollNum}: New pending proposals: ${pending.length}`);

        const fresh: TradeProposal[] = [];
        for (const p of pending) {
          const ageSec = nowSec - p.timestamp;
          if (ageSec > maxAgeSec) {
            processedIdsRef.current.add(p.id);
            console.warn(
              `[AutoTrading] SKIPPED STALE: ${p.action.toUpperCase()} ${p.token} — ` +
              `proposal age ${Math.round(ageSec / 60)} min > ${Math.round(maxAgeSec / 60)} min ` +
              `(likely queued during sleep; market context outdated)`
            );
          } else {
            fresh.push(p);
          }
        }

        if (fresh.length > 0) {
          fresh.forEach((p, i) => {
            console.log(`[AutoTrading]   [${i + 1}] ${p.action.toUpperCase()} ${p.token} - $${(p.amount * p.price).toFixed(2)}`);
          });
        }

        for (const proposal of fresh) {
          processedIdsRef.current.add(proposal.id);

          // USDC is settlement, not a strategy target.  The backend also marks
          // proposals it knows the browser executor cannot fill.
          if (
            proposal.auto_tradeable === false ||
            !AUTO_TRADE_TARGETS.includes(proposal.token.toUpperCase())
          ) {
            console.log(`[AutoTrading] SKIPPED: ${proposal.token} not in auto-trade targets`);
            continue;
          }

          await executeProposal(proposal);
        }
      } catch (e) {
        console.warn("[AutoTrading] Poll error:", e);
      }
    };

    // Poll immediately then on interval (convert seconds to ms)
    poll();
    const intervalMs = autoTradingInterval * 1000;
    console.log(`[AutoTrading] Next poll in ${autoTradingInterval} seconds`);
    const interval = setInterval(poll, intervalMs);

    return () => {
      console.log("[AutoTrading] Stopping polling loop");
      isRunningRef.current = false;
      clearInterval(interval);
    };
  }, [autoTrading, address, network, autoTradingInterval, executeProposal]);

  return null;
}
