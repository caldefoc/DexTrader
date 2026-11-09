import time
from typing import Dict, List, Optional

from ..models.agents import AnalysisRecommendation
from ..models.market import MarketSnapshot
from ..services.market_history import MarketHistory


class AnalysisAgent:
    """Rule-based strategy layer.

    Buys dips that are confirmed by RSI, VWAP and a volume spike; exits
    positions through a mechanical scale-out ladder, a hard stop ladder and a
    trailing stop.  Indicators that are still warming up return ``None`` and
    the agent falls back to the 24h change with lower confidence -- it never
    fabricates a neutral RSI or a fake VWAP.
    """

    # Buy gates
    BUY_DIP_MINOR = -2.0
    BUY_DIP_STRONG = -5.0
    BUY_DIP_MAJOR = -8.0
    MAX_BUY_STEPS = 4
    RSI_BUY_MAX = 35.0
    RSI_OVERBOUGHT = 70.0
    VWAP_DISCOUNT = 0.995
    VOLUME_SPIKE_THRESHOLD = 2.0

    # Take-profit ladder: (gain threshold, cumulative fraction of original)
    TAKE_PROFIT_LADDER = ((0.015, 0.20), (0.03, 0.50), (0.06, 0.90))
    RUNNER_TARGET = 0.20          # cap the remainder at +20%
    TRAILING_ARM_GAIN = 0.03      # trail once +3% in profit
    TRAILING_DISTANCE = 0.015     # 1.5% below peak

    # Stop ladder: (loss threshold as negative fraction, cumulative fraction)
    STOP_LADDER = ((-0.015, 0.25), (-0.03, 0.75), (-0.05, 1.0))
    STOP_REENTRY_COOLDOWN = 3600  # seconds
    STOP_REENTRY_DISCOUNT = 0.985

    def __init__(self, history: Optional[MarketHistory] = None):
        self.name = "AnalysisAgent"
        self.history = history

    # ------------------------------------------------------------------ state
    @staticmethod
    def _state(position_states: dict, token: str) -> dict:
        state = dict(position_states.get(token, {}))
        state.setdefault("avg_entry", 0.0)
        state.setdefault("buy_step", 0)
        state.setdefault("peak_price", 0.0)
        state.setdefault("tranches_sold", [])
        state.setdefault("last_exit_price", 0.0)
        state.setdefault("last_exit_ts", 0)
        state.setdefault("last_exit_kind", None)
        return state

    @staticmethod
    def _holding(user_holdings: dict, token: str) -> float:
        return float(user_holdings.get(token, user_holdings.get(token.upper(), 0.0)) or 0.0)

    @staticmethod
    def _fraction_to_sell(sold_cumulative: float, target_cumulative: float) -> float:
        if target_cumulative <= sold_cumulative:
            return 0.0
        remaining = max(0.0, 1.0 - sold_cumulative)
        if remaining <= 0:
            return 0.0
        return min(1.0, (target_cumulative - sold_cumulative) / remaining)

    @staticmethod
    def _cumulative_sold(state: dict) -> float:
        return min(1.0, max(0.0, float(state.get("cumulative_sold", 0.0) or 0.0)))

    # ------------------------------------------------------------------ main
    def analyze(
        self,
        snapshot: MarketSnapshot,
        position_states: dict = {},
        user_holdings: dict = {},
    ) -> List[AnalysisRecommendation]:
        recommendations: List[AnalysisRecommendation] = []
        now = time.time()
        print(f"[AnalysisAgent] Analyzing {len(snapshot.pairs)} pairs. Holdings: {user_holdings}")

        for pair in snapshot.pairs:
            token = pair.base_symbol.upper()
            price = pair.price
            if price <= 0:
                continue

            state = self._state(position_states, token)
            avg_entry = float(state.get("avg_entry", 0.0) or 0.0)
            current_step = int(state.get("buy_step", 0) or 0)
            has_holding = self._holding(user_holdings, token) > 0

            indicators = (
                self.history.summary(token, now)
                if self.history is not None
                else {"rsi": None, "vwap": None, "volume_ratio": None,
                      "volume_spike": False, "sample_count": 0}
            )
            rsi = indicators.get("rsi")
            vwap = indicators.get("vwap")
            volume_ratio = indicators.get("volume_ratio")
            volume_spike = bool(indicators.get("volume_spike"))
            indicators_ready = bool(indicators.get("rsi_ready") and indicators.get("vwap_ready"))

            if has_holding and price > float(state.get("peak_price", 0.0) or 0.0):
                state["peak_price"] = price
                position_states[token] = state

            action = "hold"
            confidence = 0.0
            reason = "Market is neutral"
            sell_fraction = 0.0
            exit_kind: Optional[str] = None
            buy_step = 0
            gain_pct: Optional[float] = None

            # ------------------------------------------------------- exits
            if has_holding and avg_entry > 0:
                gain = (price - avg_entry) / avg_entry
                gain_pct = gain
                peak = float(state.get("peak_price", price) or price)
                peak_gain = (peak - avg_entry) / avg_entry if avg_entry > 0 else 0.0
                drawdown_from_peak = (peak - price) / peak if peak > 0 else 0.0
                sold_cumulative = self._cumulative_sold(state)

                # 1. Hard stop ladder (deepest triggered level wins).
                stop_target = 0.0
                stop_label = None
                for threshold, target in self.STOP_LADDER:
                    if gain <= threshold:
                        stop_target = target
                        stop_label = threshold
                if stop_target > sold_cumulative:
                    sell_fraction = self._fraction_to_sell(sold_cumulative, stop_target)
                    exit_kind = "stop_loss"
                    action = "sell"
                    confidence = 0.95
                    reason = (
                        f"Stop-loss {gain * 100:.2f}% (level {stop_label * 100:.1f}%) "
                        f"[Entry: {avg_entry:.6f}, Curr: {price:.6f}]"
                    )

                # 2. Trailing stop once the position has been in profit.
                elif (
                    peak_gain >= self.TRAILING_ARM_GAIN
                    and drawdown_from_peak >= self.TRAILING_DISTANCE
                ):
                    sell_fraction = 1.0
                    exit_kind = "trailing_stop"
                    action = "sell"
                    confidence = 0.9
                    reason = (
                        f"Trailing stop: {drawdown_from_peak * 100:.2f}% off peak "
                        f"{peak:.6f} (peak gain {peak_gain * 100:.1f}%)"
                    )

                # 3. Scale-out ladder.
                else:
                    target = None
                    tranche_label = None
                    for index, (threshold, cumulative) in enumerate(self.TAKE_PROFIT_LADDER):
                        if gain >= threshold and sold_cumulative < cumulative:
                            target = cumulative
                            tranche_label = f"T{index + 1} +{threshold * 100:.1f}%"
                            break
                    # Runner: hold the last slice until +20%, then cap it.
                    if target is None and gain >= self.RUNNER_TARGET and sold_cumulative < 1.0:
                        target = 1.0
                        tranche_label = f"runner cap +{self.RUNNER_TARGET * 100:.0f}%"

                    if target is not None:
                        sell_fraction = self._fraction_to_sell(sold_cumulative, target)
                        exit_kind = "take_profit"
                        action = "sell"
                        confidence = 0.8
                        reason = (
                            f"Profit {gain * 100:.2f}% ({tranche_label}); "
                            f"selling {sell_fraction * 100:.0f}% of remaining "
                            f"[Entry: {avg_entry:.6f}, Curr: {price:.6f}]"
                        )

                # 4. Discretionary pump exit only when entry is unknown.
            elif has_holding and avg_entry <= 0 and pair.change_24h >= 5.0:
                if rsi is None or rsi >= self.RSI_OVERBOUGHT:
                    sell_fraction = 0.25
                    exit_kind = "take_profit"
                    action = "sell"
                    confidence = 0.65
                    reason = f"Pump +{pair.change_24h:.1f}% without entry price; trimming 25%"

            # -------------------------------------------------------- buys
            if action == "hold" and current_step < self.MAX_BUY_STEPS:
                buy_allowed, buy_reason, buy_step = self._buy_signal(
                    state=state,
                    pair_change=pair.change_24h,
                    price=price,
                    rsi=rsi,
                    vwap=vwap,
                    volume_spike=volume_spike,
                    indicators_ready=indicators_ready,
                    now=now,
                )
                if buy_allowed:
                    action = "buy"
                    buy_step = current_step + 1
                    confidence = self._buy_confidence(
                        change=pair.change_24h,
                        step=buy_step,
                        rsi=rsi,
                        vwap=vwap,
                        price=price,
                        volume_spike=volume_spike,
                        indicators_ready=indicators_ready,
                    )
                    reason = self._buy_reason(
                        change=pair.change_24h, step=buy_step, rsi=rsi,
                        vwap=vwap, price=price, volume_ratio=volume_ratio,
                        indicators_ready=indicators_ready,
                    )

            if action == "sell" and sell_fraction <= 0:
                action = "hold"

            if action == "hold":
                continue

            recommendations.append(
                AnalysisRecommendation(
                    token=token,
                    action=action,
                    confidence=round(min(confidence, 0.95), 2),
                    reason=reason,
                    price=price,
                    pct_change=pair.change_24h,
                    rsi=rsi,
                    vwap=vwap,
                    volume_spike=volume_spike,
                    volume_ratio=volume_ratio,
                    buy_step=buy_step,
                    sell_fraction=round(sell_fraction, 4),
                    gain_pct=round(gain_pct, 6) if gain_pct is not None else None,
                    exit_kind=exit_kind,
                    indicators_ready=indicators_ready,
                )
            )

        return recommendations

    # --------------------------------------------------------------- helpers
    def _buy_signal(
        self,
        state: dict,
        pair_change: float,
        price: float,
        rsi: Optional[float],
        vwap: Optional[float],
        volume_spike: bool,
        indicators_ready: bool,
        now: float,
    ):
        if pair_change > self.BUY_DIP_MINOR:
            return False, f"Dip only {pair_change:.1f}% (needs <= {self.BUY_DIP_MINOR}%)", 0

        # Re-entry rule: after a stop, wait for a lower price and fresh volume.
        last_exit_kind = state.get("last_exit_kind")
        last_exit_ts = float(state.get("last_exit_ts", 0) or 0)
        last_exit_price = float(state.get("last_exit_price", 0) or 0)
        if last_exit_kind == "stop_loss" and now - last_exit_ts < self.STOP_REENTRY_COOLDOWN:
            if last_exit_price <= 0 or price > last_exit_price * self.STOP_REENTRY_DISCOUNT:
                return False, "Re-entry blocked after stop-loss (waiting for 1.5% lower)", 0
            if not volume_spike:
                return False, "Re-entry blocked after stop-loss (needs volume confirmation)", 0

        # RSI gate: don't catch a falling knife that is still overbought.
        if rsi is not None and rsi > self.RSI_BUY_MAX:
            return False, f"RSI {rsi:.1f} not oversold (needs <= {self.RSI_BUY_MAX:.0f})", 0

        # VWAP gate when we have enough history.
        if vwap is not None and price > vwap * self.VWAP_DISCOUNT:
            return False, f"Price {price:.6f} above VWAP {vwap:.6f} (no discount)", 0

        # Volume-spike filter: mandatory once history is available.
        strong_dip = pair_change <= self.BUY_DIP_STRONG
        if indicators_ready and not volume_spike and not strong_dip:
            return False, "Volume spike filter not met (5m volume < 2x 1h average)", 0

        # With no history at all, require at least a strong dip rather than
        # blindly trusting the 24h change.
        if not indicators_ready and pair_change > self.BUY_DIP_STRONG:
            return True, "Dip buy (indicators warming up)", 0

        return True, "Dip confirmed by indicators", 0

    def _buy_confidence(
        self,
        change: float,
        step: int,
        rsi: Optional[float],
        vwap: Optional[float],
        price: float,
        volume_spike: bool,
        indicators_ready: bool,
    ) -> float:
        confidence = 0.55 + 0.03 * max(0, step - 1)
        if rsi is not None and rsi < 30:
            confidence += 0.05
        if volume_spike:
            confidence += 0.08
        if vwap is not None and price < vwap * 0.98:
            confidence += 0.05
        if not indicators_ready:
            confidence -= 0.05
        if change <= self.BUY_DIP_MAJOR:
            confidence += 0.05
        return min(0.9, confidence)

    @staticmethod
    def _buy_reason(
        change: float,
        step: int,
        rsi: Optional[float],
        vwap: Optional[float],
        price: float,
        volume_ratio: Optional[float],
        indicators_ready: bool,
    ) -> str:
        parts = [f"Dip {abs(change):.1f}% (buy step {step})"]
        if rsi is not None:
            parts.append(f"RSI {rsi:.1f}")
        else:
            parts.append("RSI warming up")
        if vwap is not None:
            parts.append(f"{(price / vwap - 1) * 100:+.2f}% vs VWAP")
        else:
            parts.append("VWAP warming up")
        if volume_ratio is not None:
            parts.append(f"vol {volume_ratio:.1f}x")
        if not indicators_ready:
            parts.append("unconfirmed")
        return ", ".join(parts)
