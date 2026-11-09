from typing import List

import time
from ..models.market import MarketSnapshot
from ..models.signals import Signal, SignalType


def evaluate_market(snapshot: MarketSnapshot) -> List[Signal]:
    signals: List[Signal] = []
    for pair in snapshot.pairs:
        action: SignalType
        confidence: float = 0.5
        explanation: str = ""

        if pair.change_24h >= 10:
            action = "sell"
            confidence = 0.8
            explanation = f"Price surged by {pair.change_24h:.2f}% in 24h, indicating strong momentum - consider taking profits."
        elif pair.change_24h <= -10:
            action = "buy"
            confidence = 0.8
            explanation = f"Price dropped by {abs(pair.change_24h):.2f}% in 24h, indicating a potential buying opportunity."
        else:
            action = "hold"
            confidence = 0.4
            explanation = f"Price change of {pair.change_24h:.2f}% is within neutral range."

        signals.append(
            Signal(
                pair=f"{pair.base_symbol}/{pair.quote_symbol}",
                action=action,
                confidence=confidence,
                explanation=explanation,
                source="rules",
                created_at=time.time(),
            )
        )
    return signals
