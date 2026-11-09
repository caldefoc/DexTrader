from typing import List

from ..models.market import MarketSnapshot
from ..models.signals import Signal
from ..services.strategy import evaluate_market


async def generate_signals(snapshot: MarketSnapshot) -> List[Signal]:
    return evaluate_market(snapshot)

