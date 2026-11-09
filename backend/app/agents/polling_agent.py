from ..services.coinmarketcap import fetch_market_pairs
from ..models.market import MarketSnapshot
import time

# Cache for agent market data
_agent_market_cache = None
_agent_cache_timestamp = 0
_agent_cache_duration = 3600  # 5 minutes cache for agents (configurable)

def set_agent_cache_duration(duration: int):
    """Set the agent cache duration (minimum 60 seconds)"""
    global _agent_cache_duration
    if duration < 60:
        raise ValueError("Cache duration must be at least 60 seconds")
    _agent_cache_duration = duration
    return _agent_cache_duration

def get_agent_cache_duration() -> int:
    """Get the current agent cache duration"""
    return _agent_cache_duration

async def poll_once() -> MarketSnapshot:
    global _agent_market_cache, _agent_cache_timestamp
    
    current_time = time.time()
    
    # Return cached data if it exists and is fresh
    if (_agent_market_cache is not None and 
        (current_time - _agent_cache_timestamp) < _agent_cache_duration):
        return _agent_market_cache
    
    # Fetch fresh data and update cache
    pairs = await fetch_market_pairs()
    snapshot = MarketSnapshot(pairs=pairs)
    
    _agent_market_cache = snapshot
    _agent_cache_timestamp = current_time
    
    return snapshot

