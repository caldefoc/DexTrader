from typing import List, Optional, Tuple

from ..models.agents import AnalysisRecommendation, RiskAssessment
from ..services.gas import estimate_gas_usd
from ..services.guardrails import Guardrails


class RiskAgent:
    """Validation layer: position limits, gas, profit and circuit breakers.

    The agent returns a structured list of checks rather than a single opaque
    reason so the UI and the audit log can show exactly which guardrail fired.
    """

    def __init__(self):
        self.name = "RiskAgent"
        self.min_confidence = 0.50
        self.max_slippage = 0.5
        self.abs_max_slippage = 2.0
        self.gas_limit = 250_000
        self.fallback_eth_price = 3000.0

    # ------------------------------------------------------------------ main
    def validate(
        self,
        recommendation: AnalysisRecommendation,
        user_holdings: dict = {},
        market_prices: Optional[dict] = None,
        gas_gwei: float = 20.0,
        portfolio_value: Optional[float] = None,
        guardrails: Optional[Guardrails] = None,
        available_cash: Optional[float] = None,
    ) -> RiskAssessment:
        market_prices = market_prices or {}
        checks: List[dict] = []

        def fail(reason: str) -> RiskAssessment:
            checks.append({"check": "result", "ok": False, "detail": reason})
            return RiskAssessment(
                approved=False,
                reason=reason,
                max_slippage=self.dynamic_slippage(recommendation),
                estimated_gas=gas_gwei,
                gas_gwei=gas_gwei,
                estimated_gas_usd=gas_cost,
                checks=checks,
            )

        token = recommendation.token.upper()
        eth_price = float(market_prices.get("ETH", self.fallback_eth_price) or self.fallback_eth_price)
        gas_cost = estimate_gas_usd(gas_gwei, self.gas_limit, eth_price)
        config = guardrails.config if guardrails else Guardrails().config

        # 0. Circuit breakers and frequency caps.
        if guardrails is not None:
            allowed, detail = guardrails.can_trade(token)
            checks.append({"check": "circuit_breaker", "ok": allowed, "detail": detail or "ok"})
            if not allowed:
                return fail(detail or "Trading halted")

        # 1. Confidence.
        ok = recommendation.confidence >= self.min_confidence
        checks.append({
            "check": "confidence",
            "ok": ok,
            "detail": f"{recommendation.confidence:.2f} (min {self.min_confidence:.2f})",
        })
        if not ok:
            return fail(f"Confidence {recommendation.confidence:.2f} below {self.min_confidence:.2f}")

        # 2. Gas ceiling.
        ok = gas_gwei <= config.max_gas_gwei
        checks.append({
            "check": "gas_price",
            "ok": ok,
            "detail": f"{gas_gwei:.4f} gwei (max {config.max_gas_gwei:.0f})",
        })
        if not ok:
            return fail(f"Gas price {gas_gwei:.2f} gwei exceeds {config.max_gas_gwei:.0f} gwei cap")

        slippage = self.dynamic_slippage(recommendation)
        balance = self._holding(user_holdings, token)

        # 3. Position sizing / exposure.
        max_notional: Optional[float] = None
        notional = 0.0

        if recommendation.action == "sell":
            ok = balance > 0
            checks.append({
                "check": "holdings",
                "ok": ok,
                "detail": f"{balance:.6f} {token}",
            })
            if not ok:
                return fail(f"Cannot SELL {token}: no holdings found")

            fraction = recommendation.sell_fraction or 0.25
            notional = balance * recommendation.price * fraction
        else:
            price = recommendation.price
            existing_value = balance * price
            if portfolio_value is None:
                portfolio_value = (
                    (available_cash if available_cash is not None else 0.0)
                    + existing_value
                )
            max_position_value = portfolio_value * config.max_position_pct
            headroom = max(0.0, max_position_value - existing_value)
            cash = available_cash if available_cash is not None else portfolio_value
            max_notional = min(
                portfolio_value * 0.08,   # per-step target
                headroom,
                cash * 0.95,
            )
            ok = max_notional >= 2.0
            checks.append({
                "check": "position_cap",
                "ok": ok,
                "detail": (
                    f"headroom ${headroom:.2f}, target ${max_notional:.2f} "
                    f"(cap {config.max_position_pct * 100:.0f}% of ${portfolio_value:.2f})"
                ),
            })
            if not ok:
                return fail(
                    f"Position cap reached for {token} "
                    f"(existing ${existing_value:.2f}, cap ${max_position_value:.2f})"
                )
            notional = max_notional

        # 4. Min-profit / gas-to-profit filter. Stops are exempt: protecting
        #    capital beats avoiding a small fee.
        expected_profit = 0.0
        if recommendation.action == "sell":
            if recommendation.exit_kind in ("stop_loss", "trailing_stop"):
                expected_profit = -notional * abs(recommendation.sell_fraction or 0)  # informational
                checks.append({
                    "check": "min_profit",
                    "ok": True,
                    "detail": "exempt (capital protection exit)",
                })
            else:
                gain = self._gain(recommendation)
                expected_profit = notional * max(gain, 0.0)
        else:
            # A buy is expected to reach the first ladder rung (+1.5%).
            expected_profit = notional * 0.015

        if recommendation.action == "buy" or recommendation.exit_kind not in ("stop_loss", "trailing_stop"):
            ok = expected_profit >= config.min_profit_usd
            checks.append({
                "check": "min_profit",
                "ok": ok,
                "detail": f"${expected_profit:.4f} (min ${config.min_profit_usd:.2f})",
            })
            if not ok:
                return fail(
                    f"Expected profit ${expected_profit:.2f} below "
                    f"${config.min_profit_usd:.2f} minimum"
                )

            gas_share = gas_cost / expected_profit if expected_profit > 0 else 1.0
            ok = gas_share <= 0.10
            checks.append({
                "check": "gas_vs_profit",
                "ok": ok,
                "detail": f"gas ${gas_cost:.4f} = {gas_share * 100:.1f}% of profit",
            })
            if not ok:
                return fail(
                    f"Gas ${gas_cost:.4f} is {gas_share * 100:.0f}% of expected profit "
                    f"${expected_profit:.2f} (max 10%)"
                )

        checks.append({"check": "result", "ok": True, "detail": "approved"})
        return RiskAssessment(
            approved=True,
            reason=(
                f"Risk checks passed ({len(checks) - 1} checks); "
                f"size ${notional:.2f}, gas ${gas_cost:.4f}"
            ),
            max_slippage=slippage,
            estimated_gas=gas_gwei,
            gas_gwei=gas_gwei,
            estimated_gas_usd=round(gas_cost, 6),
            expected_profit_usd=round(expected_profit, 4),
            max_notional_usd=round(max_notional, 2) if max_notional is not None else None,
            checks=checks,
        )

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _holding(holdings: dict, token: str) -> float:
        return float(holdings.get(token, holdings.get(token.upper(), 0.0)) or 0.0)

    @staticmethod
    def _gain(recommendation: AnalysisRecommendation) -> float:
        if recommendation.gain_pct is not None:
            return max(0.0, recommendation.gain_pct)
        return 0.015

    def dynamic_slippage(self, recommendation: AnalysisRecommendation) -> float:
        """0.5% for calm liquid pairs, up to 2% for volatile ones."""
        change = abs(recommendation.pct_change or 0.0)
        if change >= 10:
            slippage = 1.5
        elif change >= 5:
            slippage = 1.0
        else:
            slippage = self.max_slippage
        if recommendation.volume_spike:
            slippage += 0.25
        return round(min(self.abs_max_slippage, slippage), 2)
