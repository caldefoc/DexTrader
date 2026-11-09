from typing import List, Literal, Optional
from decimal import Decimal

from ..models.signals import Signal


TradeAction = Literal["buy", "sell"]


class TradeDecision:
    def __init__(
        self,
        accepted: bool,
        reason: Optional[str] = None,
        expected_profit: Optional[Decimal] = None,
        gas_cost: Optional[Decimal] = None,
    ) -> None:
        self.accepted = accepted
        self.reason = reason
        self.expected_profit = expected_profit
        self.gas_cost = gas_cost


def evaluate_risk(
    action: TradeAction,
    confidence: float,
    expected_profit: Decimal,
    gas_cost: Decimal,
    max_gas_price_gwei: Decimal,
    gas_price_gwei: Decimal,
    slippage_bps: int,
    skip_profit_check: bool = False,
) -> TradeDecision:
    if gas_price_gwei > max_gas_price_gwei:
        return TradeDecision(False, "Gas price above configured maximum")
    
    if not skip_profit_check and expected_profit < gas_cost:
        return TradeDecision(False, "Expected profit does not cover gas cost")
    
    if slippage_bps > 100:
        return TradeDecision(False, "Slippage tolerance above hard limit")
    
    if not skip_profit_check and confidence < 0.5:
        return TradeDecision(False, "Signal confidence below threshold")
        
    return TradeDecision(True, expected_profit=expected_profit, gas_cost=gas_cost)


async def execute_signals(signals: List[Signal]) -> List[Signal]:
    return signals
