from ..services.coinmarketcap import fetch_market_pairs
from ..models.market import MarketSnapshot
import time

# Cache for agent market data.  The strategy runs on 1-minute samples, so a
# long cache would feed it the same price over and over and make RSI/VWAP
# meaningless.  One minute matches the original brief's 30-60 second polling.
_agent_market_cache = None
_agent_cache_timestamp = 0
_agent_cache_duration = 60  # seconds (configurable, minimum 60)


def set_agent_cache_duration(duration: int):
    """Set the agent cache duration (minimum 60 seconds)."""
    global _agent_cache_duration
    if duration < 60:
        raise ValueError("Cache duration must be at least 60 seconds")
    _agent_cache_duration = duration
    return _agent_cache_duration


def get_agent_cache_duration() -> int:
    return _agent_cache_duration


async def poll_once() -> MarketSnapshot:
    global _agent_market_cache, _agent_cache_timestamp

    current_time = time.time()

    if (
        _agent_market_cache is not None
        and (current_time - _agent_cache_timestamp) < _agent_cache_duration
    ):
        return _agent_market_cache

    pairs = await fetch_market_pairs()
    snapshot = MarketSnapshot(pairs=pairs, timestamp=current_time)

    _agent_market_cache = snapshot
    _agent_cache_timestamp = current_time

    return snapshot
