import asyncio
import time
import json
from typing import List, Optional

from .analysis_agent import AnalysisAgent
from .risk_agent import RiskAgent
from .execution_agent import ExecutionAgent
from .audit_agent import AuditAgent

from ..models.agents import AgentStatus, TradeProposal
from ..models.market import MarketSnapshot, TradingPair
from ..services.coinmarketcap import fetch_market_pairs
from .polling_agent import poll_once
from ..services.portfolio import get_user_holdings, load_trades

class ControllerAgent:
    def __init__(self):
        self.analysis_agent = AnalysisAgent()
        self.risk_agent = RiskAgent()
        self.execution_agent = ExecutionAgent()
        self.audit_agent = AuditAgent()
        
        self.is_running = False
        self.last_run_time = 0
        self.current_step = "idle"
        self.polling_interval = 60 # seconds
        self.monitored_tokens = [
            "ETH", "WETH", "USDC", "VVV", "AERO",
            "SHIB", "DEGEN", "TOSHI",
            "VIRTUAL", "AVNT", "AIXBT",
            "TIBBIR", "ETHY",
            "ARB", "AAVE", "UNI", "LINK"
        ]
        self.user_holdings = {} # symbol -> amount
        self.last_trade_times = {} # symbol -> timestamp
        # Track position state: { "TOKEN": { "avg_entry": 0.0, "buy_step": 0 } }
        self.position_states = {}
        # Deterministic per-token quantities tracked from trade records only.
        # Used for avg_entry math so we never race with live wallet syncs
        # (user_holdings may already include tokens from a just-recorded trade).
        self.simulated_positions = {}
        
        self.proposals: List[TradeProposal] = []
        
        # Market Data Source
        self.market_data_source = None 
        self.injected_holdings = None # Initialize injected_holdings
        
        # Reconstruct state from past trades
        self._reconstruct_state_from_trades()

    def _reconstruct_state_from_trades(self):
        try:
            trades = load_trades()
            
            # Temporary holdings tracking just for reconstruction
            # We CANNOT rely on self.user_holdings (live wallet) because it includes current state
            simulated_holdings = {} 
            
            for trade in trades:
                try:
                    base, _ = trade.pair.split("/")
                except:
                    continue
                    
                token = base
                state = self.position_states.get(token, {"avg_entry": 0.0, "buy_step": 0})
                
                qty = 0.0
                price = trade.price
                
                if trade.action == "buy":
                    qty = trade.token_amount
                    current_amt = simulated_holdings.get(token, 0.0)
                    new_amt = qty
                    
                    total_val = (current_amt * state["avg_entry"]) + (new_amt * price)
                    total_amt = current_amt + new_amt
                    
                    if total_amt > 0:
                        state["avg_entry"] = total_val / total_amt
                        
                    simulated_holdings[token] = total_amt
                    state["buy_step"] = state.get("buy_step", 0) + 1
                    
                elif trade.action == "sell":
                    # Uniform standard: token_amount = base tokens sold.
                    # Legacy records (token == base) stored the sold qty in `amount`.
                    try:
                        _, quote = trade.pair.split("/")
                    except ValueError:
                        quote = ""
                    is_new_format = (trade.token == quote)
                    qty = trade.token_amount if is_new_format else trade.amount
                    current_amt = simulated_holdings.get(token, 0.0)
                    new_amt = max(0.0, current_amt - qty)
                    
                    if new_amt <= 0:
                        state["avg_entry"] = 0.0
                        state["buy_step"] = 0
                        
                    simulated_holdings[token] = new_amt
                
                self.position_states[token] = state
            
            # Persist the simulated quantities so live trade updates can
            # continue the reconstruction without consulting the wallet
            self.simulated_positions = dict(simulated_holdings)
            self.audit_agent.log("Controller", "State reconstructed from trades", data={"count": len(trades), "positions": {k: round(v, 6) for k, v in simulated_holdings.items() if v > 0}})
        except Exception as e:
            print(f"Failed to reconstruct state: {e}")

    async def start(self):
        if self.is_running:
            return
        self.is_running = True
        self.audit_agent.log("Controller", "Agent System Started")
        asyncio.create_task(self.run_loop())

    def stop(self):
        self.is_running = False
        self.audit_agent.log("Controller", "Agent System Stopped")

    def get_status(self) -> AgentStatus:
        return AgentStatus(
            running=self.is_running,
            current_step=self.current_step,
            last_run=self.last_run_time,
            monitored_tokens=self.monitored_tokens,
            user_holdings=self.user_holdings
        )

    def get_proposals(self) -> List[TradeProposal]:
        return self.proposals

    def update_proposal_status(self, proposal_id: str, status: str, tx_hash: Optional[str] = None):
        for p in self.proposals:
            if p.id == proposal_id:
                p.status = status
                if tx_hash:
                    # Log the execution
                    self.audit_agent.log("Controller", f"Proposal {status}: {p.token}", data={"tx_hash": tx_hash})
                    
                    # Update position state on successful execution
                    if status == "executed":
                        self._update_position_state(p)
                        # Record execution to persistent storage
                        self.execution_agent.record_execution(p, tx_hash)
                break
    
    def _update_position_state(self, proposal: TradeProposal):
        token = proposal.token
        state = self.position_states.get(token, {"avg_entry": 0.0, "buy_step": 0})
        
        if proposal.action == "buy":
            # Update average entry from simulated (trade-derived) quantities
            # to stay consistent with update_position_from_trade
            current_amt = self.simulated_positions.get(token, 0.0)
            # This is an approximation since we don't have the EXACT trade execution price/amount from chain yet,
            # but we use proposal values.
            new_amt = proposal.amount
            price = proposal.price
            
            total_val = (current_amt * state["avg_entry"]) + (new_amt * price)
            total_amt = current_amt + new_amt
            if total_amt > 0:
                state["avg_entry"] = total_val / total_amt
            self.simulated_positions[token] = total_amt
            
            # Update holdings in memory so subsequent analysis loops see the new balance
            self.user_holdings[token] = total_amt
            if self.injected_holdings is not None:
                self.injected_holdings[token] = total_amt
                # Also update the quote currency (USDC/ETH) to reflect spending
                # Assuming USDC for now as primary stablecoin
                cost = proposal.amount * proposal.price
                if "USDC" in self.injected_holdings:
                    self.injected_holdings["USDC"] = max(0.0, self.injected_holdings["USDC"] - cost)
                elif "ETH" in self.injected_holdings:
                    # Rough estimate if using ETH
                    # This is imperfect without knowing the exact pair, but better than nothing
                    pass
                
            # Increment buy step if it was a step buy
            # For now, just increment generic counter or logic could be smarter
            state["buy_step"] = state.get("buy_step", 0) + 1
            
        elif proposal.action == "sell":
            # Selling doesn't change avg entry price, but reduces amount
            # Reset buy step if we sold? Or keep it?
            # User logic: "Only buy if previous step filled". If we sell, we might reset steps.
            sim_amt = self.simulated_positions.get(token, 0.0)
            if proposal.amount >= sim_amt * 0.9: 
                # If sold almost everything, reset
                state["buy_step"] = 0
                state["avg_entry"] = 0.0
            
            # Update simulated quantities
            self.simulated_positions[token] = max(0.0, sim_amt - proposal.amount)
            
            # Update holdings in memory
            current_amt = self.user_holdings.get(token, 0.0)
            new_amt = max(0.0, current_amt - proposal.amount)
            self.user_holdings[token] = new_amt
            if self.injected_holdings is not None:
                self.injected_holdings[token] = new_amt
                # Update quote currency (USDC)
                proceeds = proposal.amount * proposal.price
                if "USDC" in self.injected_holdings:
                     self.injected_holdings["USDC"] = self.injected_holdings["USDC"] + proceeds
                
        self.position_states[token] = state

    def set_user_holdings(self, holdings: dict):
        """Update user holdings from external source"""
        self.injected_holdings = holdings
        self.user_holdings = holdings
        # Log full details to debug why execution agent sees 0
        self.audit_agent.log("Controller", f"User holdings updated: {json.dumps(holdings)}", data={"count": len(holdings), "keys": list(holdings.keys())})
    
    def update_position_from_trade(self, pair: str, action: str, token_amount: float, price: float):
        """Update internal position state based on a recorded trade"""
        try:
            base, _quote = pair.split("/")
        except ValueError:
            return
        token = base
        state = self.position_states.get(token, {"avg_entry": 0.0, "buy_step": 0})
        
        # Use simulated (trade-derived) quantities for avg_entry math.
        # user_holdings reflects the live wallet and may ALREADY include the
        # tokens from this trade (frontend syncs holdings before/after the
        # record POST), which would double-count them and dilute avg_entry
        # -> phantom profit -> spurious instant sell proposals.
        prev_amt = self.simulated_positions.get(token, 0.0)
        
        if action == "buy":
            new_amt = token_amount or 0.0
            total_val = (prev_amt * state.get("avg_entry", 0.0)) + (new_amt * (price or 0.0))
            total_amt = prev_amt + new_amt
            if total_amt > 0:
                state["avg_entry"] = total_val / total_amt
            self.simulated_positions[token] = total_amt
            state["buy_step"] = state.get("buy_step", 0) + 1
        elif action == "sell":
            remaining = max(0.0, prev_amt - (token_amount or 0.0))
            # Reset if position closed
            if remaining <= 0:
                state["buy_step"] = 0
                state["avg_entry"] = 0.0
            self.simulated_positions[token] = remaining
        
        self.position_states[token] = state
        # Refresh holdings snapshot post-trade
        try:
            self.user_holdings = get_user_holdings()
        except Exception:
            pass
        self.audit_agent.log("Controller", "Position updated from trade", data={"token": token, "action": action, "amount": token_amount, "price": price})

    async def run_loop(self):
        while self.is_running:
            try:
                self.current_step = "fetching_data"
                self.last_run_time = time.time()
                
                # 1. Fetch Data
                # Fetch real market data
                try:
                    # Use cached market data through polling agent
                    snapshot = await poll_once()
                    pairs = snapshot.pairs
                    
                    monitored_set = set(t.upper() for t in self.monitored_tokens)
                    holdings_set = set(t.upper() for t in self.user_holdings.keys())
                    allowed = monitored_set.union(holdings_set)
                    filtered_pairs = [p for p in pairs if p.base_symbol.upper() in allowed]
                    
                    snapshot = MarketSnapshot(timestamp=time.time(), pairs=filtered_pairs)
                    
                    print(f"[Controller] Snapshot: {len(filtered_pairs)} pairs. Symbols: {[p.base_symbol for p in filtered_pairs]}")
                    for p in filtered_pairs:
                        print(f"[Controller]   {p.base_symbol}: ${p.price:.4f} ({p.change_24h:+.2f}%)")
                    
                    # Seed avg_entry for existing holdings with zero baseline so sell proposals can trigger
                    market_prices = {p.base_symbol.upper(): p.price for p in filtered_pairs}
                    for token, amt in self.user_holdings.items():
                        if amt > 0:
                            state = self.position_states.get(token, {"avg_entry": 0.0, "buy_step": 0})
                            if not state.get("avg_entry"):
                                price = market_prices.get(token.upper())
                                if price:
                                    state["avg_entry"] = price
                                    self.position_states[token] = state
                except Exception as e:
                    self.audit_agent.log("Controller", f"Error fetching market data: {e}", level="ERROR")
                    print(f"[Controller] ERROR fetching market data: {e}")
                    await asyncio.sleep(10)
                    continue

                # Fetch real/calculated holdings
                if self.injected_holdings:
                    self.user_holdings = self.injected_holdings
                else:
                    self.user_holdings = get_user_holdings()
                print(f"[Controller] Holdings for analysis: {self.user_holdings}")
                print(f"[Controller] Position states: {self.position_states}")
                
                # 2. Analysis
                self.current_step = "analyzing"
                recommendations = self.analysis_agent.analyze(snapshot, self.position_states, self.user_holdings)
                print(f"[Controller] Analysis complete: {len(recommendations)} recommendations")
                for rec in recommendations:
                    print(f"[Controller]   REC: {rec.action.upper()} {rec.token} (conf={rec.confidence:.1f}, change={rec.pct_change:.1f}%, reason={rec.reason})")
                
                for rec in recommendations:
                    # Check for existing pending proposals to prevent duplicates
                    existing_pending = [p for p in self.proposals if p.token == rec.token and p.status == "pending"]
                    if existing_pending:
                        self.audit_agent.log("Controller", f"Skipping duplicate proposal for {rec.token} (already pending)")
                        continue

                    last_time = self.last_trade_times.get(rec.token, 0)
                    
                    # Cool-off for Buy signals (15 mins)
                    if rec.action == "buy" and time.time() - last_time < 900:
                        continue
                        
                    # Cool-off for Sell signals (5 mins) to prevent spamming if rejected
                    if rec.action == "sell" and time.time() - last_time < 300:
                        continue

                    self.audit_agent.log("Analysis", f"Recommendation: {rec.action} {rec.token}", data=rec.model_dump())
                    
                    # 3. Risk Check
                    self.current_step = "risk_check"
                    risk = self.risk_agent.validate(rec, self.user_holdings)
                    
                    if risk.approved:
                        self.audit_agent.log("Risk", f"Approved {rec.token}", data=risk.model_dump())
                        
                        # 4. Execution Proposal
                        self.current_step = "creating_proposal"
                        
                        # Create a price map for ExecutionAgent to calculate buying power
                        market_prices = {p.base_symbol: p.price for p in snapshot.pairs}
                        
                        proposal = self.execution_agent.create_proposal(rec, risk, self.user_holdings, market_prices)
                        self.proposals.append(proposal)
                        # Track trade time for BOTH buys and sells to enforce cool-off
                        self.last_trade_times[rec.token] = time.time()
                        self.audit_agent.log("Execution", f"Proposal Created: {proposal.id}", data=proposal.model_dump())
                        print(f"[Controller] PROPOSAL CREATED: {proposal.action.upper()} {proposal.token} amount={proposal.amount:.4f} status={proposal.status}")
                    else:
                        self.audit_agent.log("Risk", f"Rejected {rec.token}: {risk.reason}")
                        print(f"[Controller] REJECTED: {rec.action.upper()} {rec.token} - {risk.reason}")

                print(f"[Controller] Loop complete. Total proposals: {len(self.proposals)}. Pending: {len([p for p in self.proposals if p.status == 'pending'])}")
                self.current_step = "monitoring"
                await asyncio.sleep(self.polling_interval)
                
            except Exception as e:
                self.audit_agent.log("Controller", f"Error in loop: {str(e)}", level="ERROR")
                await asyncio.sleep(10) # Retry delay

    def _get_mock_snapshot(self) -> MarketSnapshot:
        # Generate some dummy data for the loop to process
        import random
        pairs = []
        tokens = self.monitored_tokens
        
        # Approximate prices for common tokens
        base_prices = {
            "ETH": 2500.0,
            "BTC": 65000.0,
            "SOL": 140.0,
            "BONK": 0.000025,
            "PEPE": 0.000008,
            "SHIB": 0.000018,
            "FLOKI": 0.00018,
            "USDC": 1.0,
            "USDT": 1.0
        }
        
        for t in tokens:
            change = random.uniform(-10, 10)
            
            # Get base price or default to 10.0 if unknown
            price = base_prices.get(t, 10.0)
            # Add some noise to the price
            price = price * (1 + random.uniform(-0.05, 0.05))
            
            pairs.append(TradingPair(
                base_symbol=t,
                quote_symbol="USDC",
                price=price,
                change_24h=change,
                volume_24h=1000000
            ))
        
        return MarketSnapshot(timestamp=time.time(), pairs=pairs)

# Global Instance
controller = ControllerAgent()
