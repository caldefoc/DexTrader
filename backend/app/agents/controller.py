import asyncio
import json
import time
from typing import List, Optional

from .analysis_agent import AnalysisAgent
from .risk_agent import RiskAgent
from .execution_agent import ExecutionAgent
from .audit_agent import AuditAgent

from ..models.agents import AgentStatus, TradeProposal
from ..models.market import MarketSnapshot
from ..core.config import DEMO_MODE
from ..services.demo_portfolio import DemoPortfolio
from ..services.gas import get_gas_price_gwei
from ..services.guardrails import Guardrails
from ..services.market_history import MarketHistory
from ..services.policy import STABLECOINS
from ..services.portfolio import get_user_holdings, load_trades
from ..services.state_store import JsonStateStore
from .polling_agent import poll_once


class ControllerAgent:
    def __init__(self):
        self.analysis_agent = AnalysisAgent()
        self.risk_agent = RiskAgent()
        self.execution_agent = ExecutionAgent()
        self.audit_agent = AuditAgent()

        self.is_running = False
        self.last_run_time = 0
        self.current_step = "idle"
        self.polling_interval = 60
        self.monitored_tokens = [
            "ETH", "WETH", "USDC", "VVV", "AERO",
            "SHIB", "DEGEN", "TOSHI",
            "VIRTUAL", "AVNT", "AIXBT",
            "TIBBIR", "ETHY",
            "ARB", "AAVE", "UNI", "LINK"
        ]
        self.user_holdings = {}
        self.last_trade_times = {}
        self.position_states = {}
        self.simulated_positions = {}

        self.proposals: List[TradeProposal] = []

        self.state_store = JsonStateStore(name="agent_state.json")
        self.history = MarketHistory()
        self.guardrails = Guardrails()
        self.analysis_agent.history = self.history

        self.demo = DEMO_MODE
        self.demo_portfolio = DemoPortfolio() if self.demo else None
        self.last_prices: dict = {}

        self._last_proposal_times = {}
        self._applied_tx_hashes: set = set()
        self._counted_tx_hashes: set = set()
        self._last_halt_log = ""
        self._last_equity: Optional[float] = None

        self.market_data_source = None
        self.injected_holdings = None

        self._stored_state = self.state_store.load()
        if self.demo:
            self._reconstruct_demo_state()
        else:
            self._reconstruct_state_from_trades()
        self._restore_agent_state()

    # ----------------------------------------------------------- persistence
    def _restore_agent_state(self) -> None:
        data = self._stored_state or {}
        stored_positions = data.get("positions") or {}
        for token, stored in stored_positions.items():
            if not isinstance(stored, dict):
                continue
            token = token.upper()
            state = self.position_states.setdefault(
                token, {"avg_entry": 0.0, "buy_step": 0}
            )
            # Average entry is reconstructed from the trade ledger; only the
            # strategy fields are restored so they cannot drift from trades.
            for key in (
                "peak_price", "tranches_sold", "cumulative_sold",
                "last_exit_price", "last_exit_ts", "last_exit_kind",
            ):
                if key in stored and stored[key] is not None:
                    state[key] = stored[key]
            self.position_states[token] = state

        self.proposals = []
        for raw in (data.get("proposals") or [])[-200:]:
            try:
                self.proposals.append(TradeProposal(**raw))
            except Exception:
                continue

        for token, timestamp in (data.get("last_trade_times") or {}).items():
            try:
                self.last_trade_times[token] = float(timestamp)
            except (TypeError, ValueError):
                continue

        self.guardrails = Guardrails.from_dict(data.get("guardrails"))
        if self.proposals:
            self.audit_agent.log(
                "Controller",
                f"Restored {len(self.proposals)} proposals from disk",
                data={"pending": len([p for p in self.proposals if p.status == "pending"])},
            )

    def _persist_state(self) -> None:
        self._stored_state = {
            "positions": self.position_states,
            "proposals": [p.model_dump() for p in self.proposals[-200:]],
            "last_trade_times": self.last_trade_times,
            "guardrails": self.guardrails.to_dict(),
        }
        self.state_store.save(self._stored_state)

    # --------------------------------------------------------- reconstruction
    def _reconstruct_state_from_trades(self):
        try:
            trades = load_trades()
            simulated_holdings = {}

            for trade in trades:
                try:
                    base, _ = trade.pair.split("/")
                except Exception:
                    continue

                token = base
                state = self.position_states.get(token, {"avg_entry": 0.0, "buy_step": 0})

                if trade.action == "buy":
                    qty = trade.token_amount
                    current_amt = simulated_holdings.get(token, 0.0)
                    total_val = (current_amt * state["avg_entry"]) + (qty * trade.price)
                    total_amt = current_amt + qty
                    if total_amt > 0:
                        state["avg_entry"] = total_val / total_amt
                    simulated_holdings[token] = total_amt
                    state["buy_step"] = state.get("buy_step", 0) + 1
                elif trade.action == "sell":
                    try:
                        _, quote = trade.pair.split("/")
                    except ValueError:
                        quote = ""
                    is_new_format = trade.token == quote
                    qty = trade.token_amount if is_new_format else trade.amount
                    current_amt = simulated_holdings.get(token, 0.0)
                    new_amt = max(0.0, current_amt - qty)
                    if new_amt <= 0:
                        state["avg_entry"] = 0.0
                        state["buy_step"] = 0
                    simulated_holdings[token] = new_amt

                state.setdefault("peak_price", 0.0)
                state.setdefault("tranches_sold", [])
                state.setdefault("cumulative_sold", 0.0)
                self.position_states[token] = state

            self.simulated_positions = dict(simulated_holdings)
            self.audit_agent.log(
                "Controller",
                "State reconstructed from trades",
                data={
                    "count": len(trades),
                    "positions": {k: round(v, 6) for k, v in simulated_holdings.items() if v > 0},
                },
            )
        except Exception as exc:
            print(f"Failed to reconstruct state: {exc}")

    # --------------------------------------------------------- demo portfolio
    def _reconstruct_demo_state(self) -> None:
        """Seed holdings, average entries and buy steps from demo fills."""
        if self.demo_portfolio is None:
            return
        self.user_holdings = self.demo_portfolio.holdings()
        buys: dict = {}
        for fill in self.demo_portfolio.fills:
            if fill.get("action") == "buy":
                token = str(fill.get("token", "")).upper()
                buys[token] = buys.get(token, 0) + 1

        for token, position in self.demo_portfolio.positions.items():
            state = self.position_states.setdefault(
                token, {"avg_entry": 0.0, "buy_step": 0}
            )
            state["avg_entry"] = float(position.get("avg_entry") or 0.0)
            state["buy_step"] = min(4, int(buys.get(token, 0)))
            state.setdefault("peak_price", 0.0)
            state.setdefault("tranches_sold", [])
            state.setdefault("cumulative_sold", 0.0)
            self.position_states[token] = state

        self.simulated_positions = {
            token: float(position.get("qty") or 0.0)
            for token, position in self.demo_portfolio.positions.items()
        }
        self.audit_agent.log(
            "Controller",
            "Demo portfolio restored",
            data={
                "cash": round(self.demo_portfolio.cash, 2),
                "positions": len(self.demo_portfolio.positions),
                "fills": len(self.demo_portfolio.fills),
            },
        )

    # -------------------------------------------------------------- lifecycle
    async def start(self):
        if self.is_running:
            return
        self.is_running = True
        self.audit_agent.log("Controller", "Agent System Started")
        asyncio.create_task(self.run_loop())

    def stop(self):
        self.is_running = False
        self.audit_agent.log("Controller", "Agent System Stopped")

    def halt(self, reason: str = "Manual kill switch") -> None:
        self.guardrails.halt(reason)
        self.audit_agent.log("Controller", f"Trading halted: {reason}", level="WARNING")
        self._persist_state()

    def resume(self) -> None:
        self.guardrails.resume()
        self.audit_agent.log("Controller", "Trading resumed manually")
        self._persist_state()

    def get_status(self) -> AgentStatus:
        rails = self.guardrails.status(self._last_equity)
        return AgentStatus(
            running=self.is_running,
            current_step=self.current_step,
            last_run=self.last_run_time,
            monitored_tokens=self.monitored_tokens,
            user_holdings=self.user_holdings,
            halted=rails["halted"],
            halt_reason=rails["halt_reason"],
            equity=rails["equity"],
            day_start_equity=rails["day_start_equity"],
            drawdown_pct=rails["drawdown_pct"],
            trades_today=rails["trades_today"],
            max_daily_trades=rails["max_daily_trades"],
        )

    def get_proposals(self) -> List[TradeProposal]:
        return self.proposals

    def get_guardrail_status(self) -> dict:
        return self.guardrails.status(self._last_equity)

    # --------------------------------------------------------------- proposals
    def _apply_demo_fill(self, proposal: TradeProposal) -> None:
        """Fill a proposal against the virtual portfolio (demo mode only)."""
        if self.demo_portfolio is None:
            return
        fill = self.demo_portfolio.apply_fill(proposal)
        if not fill:
            self.audit_agent.log(
                "Execution",
                f"Demo fill skipped for {proposal.token} (no cash or holdings)",
                level="WARNING",
            )
            return
        # Keep the proposal and the position state in step with the fill that
        # actually happened (a buy can be clipped by the available cash).
        proposal.amount = fill["quantity"]
        proposal.notional_usd = fill["value_usd"]
        self.audit_agent.log(
            "Execution",
            f"Demo fill: {fill['action'].upper()} {proposal.token} "
            f"{fill['quantity']:.6f} @ {fill['price']}",
            data=fill,
        )
        self._update_position_state(proposal)
        self.guardrails.record_trade(proposal.token)
        self.last_trade_times[proposal.token] = time.time()
        self.user_holdings = self.demo_portfolio.holdings()

    def update_proposal_status(
        self,
        proposal_id: str,
        status: str,
        tx_hash: Optional[str] = None,
    ):
        for proposal in self.proposals:
            if proposal.id != proposal_id:
                continue
            if status == "executed" and proposal.status == "executed":
                break  # idempotent: a repeat call must not fill twice
            proposal.status = status
            if status == "executed":
                if self.demo:
                    self._apply_demo_fill(proposal)
                    self._persist_state()
                    break
                self.audit_agent.log(
                    "Controller",
                    f"Proposal executed: {proposal.token}",
                    data={"tx_hash": tx_hash},
                )
                already_applied = bool(tx_hash and tx_hash in self._applied_tx_hashes)
                if not already_applied:
                    if tx_hash:
                        self._applied_tx_hashes.add(tx_hash)
                    self._update_position_state(proposal)
                if not tx_hash or tx_hash not in self._counted_tx_hashes:
                    if tx_hash:
                        self._counted_tx_hashes.add(tx_hash)
                    self.guardrails.record_trade(proposal.token)
                    self.last_trade_times[proposal.token] = time.time()
                if tx_hash and not already_applied:
                    self.execution_agent.record_execution(proposal, tx_hash)
            self._persist_state()
            break

    def _update_position_state(self, proposal: TradeProposal):
        token = proposal.token.upper()
        state = self.position_states.get(
            token,
            {"avg_entry": 0.0, "buy_step": 0, "peak_price": 0.0,
             "tranches_sold": [], "cumulative_sold": 0.0},
        )
        state.setdefault("peak_price", 0.0)
        state.setdefault("cumulative_sold", 0.0)

        if proposal.action == "buy":
            current_amt = self.simulated_positions.get(token, 0.0)
            new_amt = proposal.amount
            price = proposal.price
            total_val = (current_amt * state.get("avg_entry", 0.0)) + (new_amt * price)
            total_amt = current_amt + new_amt
            if total_amt > 0:
                state["avg_entry"] = total_val / total_amt
            self.simulated_positions[token] = total_amt
            state["peak_price"] = max(state.get("peak_price", 0.0), price)
            state["buy_step"] = min(4, state.get("buy_step", 0) + 1)

            self.user_holdings[token] = total_amt
            if self.injected_holdings is not None:
                self.injected_holdings[token] = total_amt
                cost = proposal.amount * proposal.price
                for stable in STABLECOINS:
                    if stable in self.injected_holdings:
                        self.injected_holdings[stable] = max(
                            0.0, self.injected_holdings[stable] - cost
                        )
                        break

        elif proposal.action == "sell":
            previous_amt = self.simulated_positions.get(token, 0.0)
            fraction = proposal.sell_fraction
            if fraction is None:
                fraction = (
                    proposal.amount / previous_amt if previous_amt > 0 else 1.0
                )
            fraction = max(0.0, min(1.0, fraction))
            previous_cumulative = float(state.get("cumulative_sold", 0.0) or 0.0)
            state["cumulative_sold"] = min(
                1.0, previous_cumulative + fraction * (1.0 - previous_cumulative)
            )
            state["last_exit_kind"] = proposal.exit_kind
            state["last_exit_price"] = proposal.price
            state["last_exit_ts"] = time.time()

            self.simulated_positions[token] = max(0.0, previous_amt - proposal.amount)
            current_amt = self.user_holdings.get(token, 0.0)
            new_amt = max(0.0, current_amt - proposal.amount)
            self.user_holdings[token] = new_amt
            if self.injected_holdings is not None:
                self.injected_holdings[token] = new_amt
                proceeds = proposal.amount * proposal.price
                for stable in STABLECOINS:
                    if stable in self.injected_holdings:
                        self.injected_holdings[stable] += proceeds
                        break

            if self.simulated_positions[token] <= 0:
                state["avg_entry"] = 0.0
                state["buy_step"] = 0
                state["cumulative_sold"] = 0.0
                state["peak_price"] = 0.0

        self.position_states[token] = state

    def set_user_holdings(self, holdings: dict):
        if self.demo:
            # The demo owns its portfolio; a browser cannot inject balances.
            self.user_holdings = self.demo_portfolio.holdings() if self.demo_portfolio else {}
            return
        self.injected_holdings = holdings
        self.user_holdings = holdings
        self.audit_agent.log(
            "Controller",
            f"User holdings updated: {json.dumps(holdings)}",
            data={"count": len(holdings), "keys": list(holdings.keys())},
        )

    def update_position_from_trade(
        self,
        pair: str,
        action: str,
        token_amount: float,
        price: float,
        tx_hash: Optional[str] = None,
    ):
        """Update internal position state based on a recorded trade."""
        if tx_hash and tx_hash in self._applied_tx_hashes:
            return
        if tx_hash:
            self._applied_tx_hashes.add(tx_hash)
            if len(self._applied_tx_hashes) > 1000:
                self._applied_tx_hashes = set(list(self._applied_tx_hashes)[-500:])

        try:
            base, _quote = pair.split("/")
        except ValueError:
            return
        token = base.upper()
        if not tx_hash or tx_hash not in self._counted_tx_hashes:
            if tx_hash:
                self._counted_tx_hashes.add(tx_hash)
            self.guardrails.record_trade(token)
            self.last_trade_times[token] = time.time()
        state = self.position_states.get(token, {"avg_entry": 0.0, "buy_step": 0})
        previous_amt = self.simulated_positions.get(token, 0.0)

        if action == "buy":
            new_amt = token_amount or 0.0
            total_val = (previous_amt * state.get("avg_entry", 0.0)) + (new_amt * (price or 0.0))
            total_amt = previous_amt + new_amt
            if total_amt > 0:
                state["avg_entry"] = total_val / total_amt
            self.simulated_positions[token] = total_amt
            state["buy_step"] = min(4, state.get("buy_step", 0) + 1)
            state["peak_price"] = max(state.get("peak_price", 0.0), price or 0.0)
        elif action == "sell":
            remaining = max(0.0, previous_amt - (token_amount or 0.0))
            if previous_amt > 0:
                fraction = min(1.0, (token_amount or 0.0) / previous_amt)
                cumulative = float(state.get("cumulative_sold", 0.0) or 0.0)
                state["cumulative_sold"] = min(1.0, cumulative + fraction * (1.0 - cumulative))
            state["last_exit_price"] = price or 0.0
            state["last_exit_ts"] = time.time()
            if remaining <= 0:
                state["buy_step"] = 0
                state["avg_entry"] = 0.0
                state["cumulative_sold"] = 0.0
                state["peak_price"] = 0.0
            self.simulated_positions[token] = remaining

        self.position_states[token] = state
        try:
            self.user_holdings = get_user_holdings()
        except Exception:
            pass
        self.audit_agent.log(
            "Controller",
            "Position updated from trade",
            data={"token": token, "action": action, "amount": token_amount, "price": price},
        )
        self._persist_state()

    def _equity(self, holdings: dict, market_prices: dict) -> Optional[float]:
        if not holdings:
            return None
        stable = 0.0
        tokens = 0.0
        for symbol, amount in holdings.items():
            if not amount or amount <= 0:
                continue
            upper = symbol.upper()
            if upper in STABLECOINS:
                stable += amount
            else:
                price = market_prices.get(upper)
                if price:
                    tokens += amount * price
        total = stable + tokens
        return total if total > 0 else None

    # --------------------------------------------------------------- main loop
    async def run_loop(self):
        while self.is_running:
            try:
                self.current_step = "fetching_data"
                self.last_run_time = time.time()

                try:
                    snapshot = await poll_once()
                    pairs = snapshot.pairs

                    monitored_set = {t.upper() for t in self.monitored_tokens}
                    holdings_set = {t.upper() for t in self.user_holdings.keys()}
                    allowed = monitored_set.union(holdings_set)
                    filtered_pairs = [p for p in pairs if p.base_symbol.upper() in allowed]
                    snapshot = MarketSnapshot(
                        pairs=filtered_pairs,
                        timestamp=getattr(snapshot, "timestamp", None) or time.time(),
                    )

                    print(
                        f"[Controller] Snapshot: {len(filtered_pairs)} pairs. "
                        f"Symbols: {[p.base_symbol for p in filtered_pairs]}"
                    )
                    for pair in filtered_pairs:
                        print(
                            f"[Controller]   {pair.base_symbol}: ${pair.price:.4f} "
                            f"({pair.change_24h:+.2f}%)"
                        )

                    self.history.record(snapshot)

                    market_prices = {p.base_symbol.upper(): p.price for p in filtered_pairs}
                    self.last_prices = market_prices
                    for token, amount in self.user_holdings.items():
                        if amount > 0:
                            state = self.position_states.get(
                                token, {"avg_entry": 0.0, "buy_step": 0}
                            )
                            if not state.get("avg_entry"):
                                price = market_prices.get(token.upper())
                                if price:
                                    state["avg_entry"] = price
                                    self.position_states[token] = state
                except Exception as exc:
                    self.audit_agent.log(
                        "Controller", f"Error fetching market data: {exc}", level="ERROR"
                    )
                    print(f"[Controller] ERROR fetching market data: {exc}")
                    await asyncio.sleep(10)
                    continue

                if self.demo and self.demo_portfolio is not None:
                    self.user_holdings = self.demo_portfolio.holdings()
                elif self.injected_holdings:
                    self.user_holdings = self.injected_holdings
                else:
                    self.user_holdings = get_user_holdings()
                print(f"[Controller] Holdings for analysis: {self.user_holdings}")
                print(f"[Controller] Position states: {self.position_states}")

                equity = self._equity(self.user_holdings, market_prices)
                self._last_equity = equity
                rails = self.guardrails.begin_cycle(equity)
                if rails["halted"]:
                    message = rails.get("halt_reason") or "Trading halted"
                    if message != self._last_halt_log:
                        self.audit_agent.log(
                            "Risk", f"Trading halted: {message}", level="WARNING"
                        )
                        self._last_halt_log = message
                    self.current_step = "halted"
                    self._persist_state()
                    await asyncio.sleep(self.polling_interval)
                    continue
                self._last_halt_log = ""

                # 2. Analysis
                self.current_step = "analyzing"
                recommendations = self.analysis_agent.analyze(
                    snapshot, self.position_states, self.user_holdings
                )
                print(f"[Controller] Analysis complete: {len(recommendations)} recommendations")
                for rec in recommendations:
                    print(
                        f"[Controller]   REC: {rec.action.upper()} {rec.token} "
                        f"(conf={rec.confidence:.2f}, change={rec.pct_change:.1f}%, "
                        f"rsi={rec.rsi}, reason={rec.reason})"
                    )

                gas_gwei = await get_gas_price_gwei()
                market_prices.setdefault(
                    "ETH", market_prices.get("WETH", 3000.0)
                )
                available_cash = sum(
                    self.user_holdings.get(symbol, 0.0) for symbol in STABLECOINS
                ) + (
                    self.user_holdings.get("ETH", 0.0)
                    + self.user_holdings.get("WETH", 0.0)
                ) * market_prices.get("ETH", 3000.0)

                for rec in recommendations:
                    existing_pending = [
                        p for p in self.proposals
                        if p.token == rec.token and p.status in ("pending", "approved")
                    ]
                    if existing_pending:
                        self.audit_agent.log(
                            "Controller",
                            f"Skipping duplicate proposal for {rec.token} (already pending)",
                        )
                        continue

                    last_time = self._last_proposal_times.get(rec.token, 0)
                    if rec.action == "buy" and time.time() - last_time < 600:
                        continue
                    if rec.action == "sell" and time.time() - last_time < 300:
                        continue

                    self.audit_agent.log(
                        "Analysis",
                        f"Recommendation: {rec.action} {rec.token}",
                        data=rec.model_dump(),
                    )

                    # 3. Risk check
                    self.current_step = "risk_check"
                    risk = self.risk_agent.validate(
                        rec,
                        self.user_holdings,
                        market_prices=market_prices,
                        gas_gwei=gas_gwei,
                        portfolio_value=equity,
                        guardrails=self.guardrails,
                        available_cash=available_cash,
                    )

                    if not risk.approved:
                        self.audit_agent.log(
                            "Risk", f"Rejected {rec.token}: {risk.reason}",
                            data=risk.model_dump(),
                        )
                        print(f"[Controller] REJECTED: {rec.action.upper()} {rec.token} - {risk.reason}")
                        continue

                    self.audit_agent.log("Risk", f"Approved {rec.token}", data=risk.model_dump())

                    # 4. Execution proposal
                    self.current_step = "creating_proposal"
                    proposal = self.execution_agent.create_proposal(
                        rec,
                        risk,
                        self.user_holdings,
                        market_prices,
                        portfolio_value=equity,
                    )
                    self.proposals.append(proposal)
                    self._last_proposal_times[rec.token] = time.time()
                    self.audit_agent.log(
                        "Execution", f"Proposal Created: {proposal.id}",
                        data=proposal.model_dump(),
                    )
                    print(
                        f"[Controller] PROPOSAL CREATED: {proposal.action.upper()} "
                        f"{proposal.token} amount={proposal.amount:.4f} status={proposal.status}"
                    )
                    self._persist_state()

                print(
                    f"[Controller] Loop complete. Total proposals: {len(self.proposals)}. "
                    f"Pending: {len([p for p in self.proposals if p.status == 'pending'])}"
                )
                self.current_step = "monitoring"
                self.history.persist()
                await asyncio.sleep(self.polling_interval)

            except Exception as exc:
                self.audit_agent.log("Controller", f"Error in loop: {str(exc)}", level="ERROR")
                await asyncio.sleep(10)


# Global Instance
controller = ControllerAgent()
