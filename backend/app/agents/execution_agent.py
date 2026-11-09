import time
import uuid
from typing import Optional

from ..models.agents import AnalysisRecommendation, RiskAssessment, TradeProposal
from ..services.policy import STABLECOINS, is_auto_tradeable


class ExecutionAgent:
    """Turns an approved recommendation into a sized, human-approvable proposal.

    Proposal amounts are always in TOKEN units (buy: tokens to receive,
    sell: tokens to sell).  Nothing here invents a balance when the wallet is
    disconnected: with no buying power the proposal is rejected, not padded
    with fake USDC.
    """

    BUY_STEP_FRACTIONS = {1: 0.25, 2: 0.35, 3: 0.50, 4: 0.60}
    TARGET_POSITION_PCT = 0.08
    MIN_TRADE_USD = 2.0
    DUST_THRESHOLD_USD = 0.50
    GAS_LIMIT = 250_000

    def __init__(self):
        self.name = "ExecutionAgent"

    # ------------------------------------------------------------------ record
    def record_execution(self, proposal: TradeProposal, tx_hash: str):
        """Record a successful execution to trades.json using portfolio service."""
        from ..models.portfolio import TradeExecution
        from ..services.portfolio import add_trade

        token_qty = proposal.amount
        usd_amount = proposal.amount * proposal.price if proposal.price else 0.0

        trade = TradeExecution(
            tx_hash=tx_hash,
            network="base",
            pair=f"{proposal.token}/USDC",
            action=proposal.action,
            amount=usd_amount,
            token="USDC",
            price=proposal.price,
            token_amount=token_qty,
            network_fee=proposal.gas_cost_usd,
            price_usd=proposal.price,
            status="completed",
            timestamp=int(time.time()),
        )

        try:
            add_trade(trade)
            print(f"[ExecutionAgent] Recorded trade: {tx_hash}")
        except Exception as exc:
            print(f"[ExecutionAgent] Failed to record trade: {exc}")

    # --------------------------------------------------------------- proposal
    def create_proposal(
        self,
        recommendation: AnalysisRecommendation,
        risk_assessment: RiskAssessment,
        user_holdings: dict = {},
        market_prices: dict = {},
        portfolio_value: Optional[float] = None,
    ) -> TradeProposal:
        holdings = {str(k).upper(): float(v or 0.0) for k, v in (user_holdings or {}).items()}
        eth_price = float(market_prices.get("ETH", 3000.0) or 3000.0)
        stable_value = sum(
            holdings.get(symbol, 0.0) for symbol in STABLECOINS
        )
        eth_value = (holdings.get("ETH", 0.0) + holdings.get("WETH", 0.0)) * eth_price
        buying_power = eth_value + stable_value
        if portfolio_value is None:
            portfolio_value = buying_power

        print(
            f"[ExecutionAgent] Buying power ${buying_power:.2f} "
            f"(stable ${stable_value:.2f}, ETH/WETH ${eth_value:.2f})"
        )

        base_kwargs = dict(
            id=str(uuid.uuid4()),
            token=recommendation.token.upper(),
            action=recommendation.action,
            price=recommendation.price,
            pct_change=recommendation.pct_change,
            slippage=risk_assessment.max_slippage,
            gas_limit=self.GAS_LIMIT,
            gas_cost_usd=risk_assessment.estimated_gas_usd,
            expected_profit_usd=risk_assessment.expected_profit_usd,
            auto_tradeable=is_auto_tradeable(recommendation.token),
            price_source="global_spot",
            sell_fraction=recommendation.sell_fraction or None,
            exit_kind=recommendation.exit_kind,
            timestamp=time.time(),
        )

        if recommendation.action == "buy":
            if buying_power < self.MIN_TRADE_USD:
                return TradeProposal(
                    **base_kwargs,
                    amount=0.0,
                    reason=(
                        f"{recommendation.reason} (Insufficient buying power: "
                        f"${buying_power:.2f}; connect a funded wallet)"
                    ),
                    status="rejected",
                )

            step = max(1, min(4, recommendation.buy_step or 1))
            fraction = self.BUY_STEP_FRACTIONS.get(step, 0.25)
            target_position = buying_power * self.TARGET_POSITION_PCT
            notional = target_position * fraction

            # Respect the risk layer's exposure headroom.
            if risk_assessment.max_notional_usd is not None:
                notional = min(notional, risk_assessment.max_notional_usd)
            # Never spend more than 95% of available cash.
            notional = min(notional, buying_power * 0.95)

            if notional < self.MIN_TRADE_USD:
                notional = min(self.MIN_TRADE_USD, buying_power * 0.95)

            if notional < self.DUST_THRESHOLD_USD:
                return TradeProposal(
                    **base_kwargs,
                    amount=0.0,
                    reason=(
                        f"{recommendation.reason} (Trade too small: "
                        f"${notional:.2f} < ${self.DUST_THRESHOLD_USD:.2f} dust threshold)"
                    ),
                    status="rejected",
                )

            amount = notional / recommendation.price if recommendation.price > 0 else 0.0
            notional = amount * recommendation.price
            return TradeProposal(
                **base_kwargs,
                amount=amount,
                notional_usd=round(notional, 4),
                reason=f"{recommendation.reason} | sized ${notional:.2f} ({step}/4)",
                status="pending",
            )

        # ------------------------------------------------------------- sell
        current_holding = holdings.get(recommendation.token.upper(), 0.0)
        if current_holding <= 0:
            return TradeProposal(
                **base_kwargs,
                amount=0.0,
                reason=f"{recommendation.reason} (No {recommendation.token} holdings to sell)",
                status="rejected",
            )

        sell_fraction = recommendation.sell_fraction or 0.25
        sell_fraction = max(0.0, min(1.0, sell_fraction))
        amount = current_holding * sell_fraction
        notional = amount * recommendation.price
        if notional < self.DUST_THRESHOLD_USD:
            return TradeProposal(
                **base_kwargs,
                amount=0.0,
                reason=(
                    f"{recommendation.reason} (Trade too small: "
                    f"${notional:.2f} < ${self.DUST_THRESHOLD_USD:.2f} dust threshold)"
                ),
                status="rejected",
            )

        return TradeProposal(
            **base_kwargs,
            amount=amount,
            notional_usd=round(notional, 4),
            reason=(
                f"{recommendation.reason} | selling {sell_fraction * 100:.0f}% "
                f"(${notional:.2f})"
            ),
            status="pending",
        )
