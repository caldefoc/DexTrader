"""Pure technical-indicator helpers.

No network, no global state.  Every function returns ``None`` when it does not
have enough data instead of inventing a neutral value -- callers decide whether
a missing indicator should block a trade or merely lower confidence.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence, Tuple


def _clean(values: Iterable[Optional[float]]) -> list[float]:
    return [float(v) for v in values if v is not None and float(v) > 0]


def rsi(closes: Sequence[Optional[float]], period: int = 14) -> Optional[float]:
    """Wilder's RSI over ``closes``.

    Requires at least ``period + 1`` valid closes.  Returns 0-100 or ``None``.
    """
    values = _clean(closes)
    if period <= 0 or len(values) < period + 1:
        return None

    gains = 0.0
    losses = 0.0
    for previous, current in zip(values[: period], values[1 : period + 1]):
        change = current - previous
        if change >= 0:
            gains += change
        else:
            losses -= change

    avg_gain = gains / period
    avg_loss = losses / period

    for previous, current in zip(values[period:-1], values[period + 1 :]):
        change = current - previous
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        avg_gain = ((period - 1) * avg_gain + gain) / period
        avg_loss = ((period - 1) * avg_loss + loss) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def vwap(prices: Sequence[Optional[float]], volumes: Sequence[Optional[float]]) -> Optional[float]:
    """Volume-weighted average price.  Ignores samples without a volume."""
    numerator = 0.0
    denominator = 0.0
    for price, volume in zip(prices, volumes):
        if price is None or volume is None:
            continue
        price = float(price)
        volume = float(volume)
        if price <= 0 or volume <= 0:
            continue
        numerator += price * volume
        denominator += volume
    if denominator <= 0:
        return None
    return numerator / denominator


def volume_ratio(
    short_volume: Optional[float],
    baseline_volume: Optional[float],
    baseline_windows: float = 1.0,
) -> Optional[float]:
    """Compare a short volume bucket against an average bucket of equal size.

    ``baseline_volume`` is the volume observed over ``baseline_windows`` times
    the short window (e.g. 5-minute volume vs 1 hour of volume = 12 windows).
    """
    if short_volume is None or baseline_volume is None:
        return None
    if baseline_volume <= 0 or baseline_windows <= 0:
        return None
    expected = baseline_volume / baseline_windows
    if expected <= 0:
        return None
    return short_volume / expected


def is_volume_spike(ratio: Optional[float], threshold: float = 2.0) -> bool:
    return ratio is not None and ratio >= threshold


def pct_change(new: Optional[float], old: Optional[float]) -> Optional[float]:
    if new is None or old is None or old == 0:
        return None
    return (new - old) / old
