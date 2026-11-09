from fastapi import APIRouter, HTTPException, Query, Request
from collections import OrderedDict
import re
import time
from typing import Literal, Optional
import asyncio

import httpx

from ..models.market import BaseTokenSnapshot, MarketSnapshot, GainersLosers, TokenVolumesSnapshot
from ..services.base_tokens import fetch_base_tokens
from ..services.coinmarketcap import fetch_market_pairs
from ..services.geckoterminal import fetch_token_volumes

router = APIRouter()

# Cache for market data
_market_data_cache: Optional[list] = None
_cache_timestamp: float = 0
CACHE_DURATION = 3600  # 1 hour cache

# Cache initialization lock to prevent duplicate API calls
_cache_lock = asyncio.Lock()
_cache_initialized = False

async def get_cached_market_data(force_refresh: bool = False) -> list:
    global _market_data_cache, _cache_timestamp, _cache_initialized
    
    current_time = time.time()
    
    # Return cached data if it exists and is fresh, unless force_refresh is True
    if (_market_data_cache is not None and 
        (current_time - _cache_timestamp) < CACHE_DURATION and 
        not force_refresh):
        return _market_data_cache
    
    # Use lock to prevent multiple simultaneous API calls when cache is empty
    async with _cache_lock:
        # Check cache again inside the lock to avoid race condition
        if (_market_data_cache is not None and 
            (current_time - _cache_timestamp) < CACHE_DURATION and 
            not force_refresh):
            return _market_data_cache
        
        # Fetch fresh data and update cache
        fresh_data = await fetch_market_pairs(limit=200)
        _market_data_cache = fresh_data
        _cache_timestamp = current_time
        _cache_initialized = True
        
        return fresh_data

@router.get("/", response_model=MarketSnapshot)
async def get_market(limit: int = Query(50, ge=1, le=500), refresh: bool = Query(False)) -> MarketSnapshot:
    pairs = await get_cached_market_data(force_refresh=refresh)
    # Apply limit to the cached data
    limited_pairs = pairs[:limit]
    return MarketSnapshot(pairs=limited_pairs)


@router.get("/gainers-losers", response_model=GainersLosers)
async def get_gainers_losers(limit: int = Query(10, ge=1, le=100), refresh: bool = Query(False)) -> GainersLosers:
    pairs = await get_cached_market_data(force_refresh=refresh)
    sorted_pairs = sorted(pairs, key=lambda p: p.change_24h, reverse=True)
    gainers = sorted_pairs[:limit]
    losers = list(reversed(sorted_pairs))[:limit]
    return GainersLosers(gainers=gainers, losers=losers)


_base_tokens_cache: dict[str, BaseTokenSnapshot] = {}
_base_tokens_timestamp: dict[str, float] = {}
_base_tokens_lock = asyncio.Lock()
BASE_TOKENS_CACHE_DURATION = 300


def _is_rate_limited(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429
    return "429" in str(exc)


@router.get("/base-tokens", response_model=BaseTokenSnapshot)
async def get_base_tokens(
    sort_by: Literal["market_cap", "volume_24h"] = "market_cap",
) -> BaseTokenSnapshot:
    async with _base_tokens_lock:
        if (
            sort_by in _base_tokens_cache
            and time.monotonic() - _base_tokens_timestamp[sort_by] < BASE_TOKENS_CACHE_DURATION
        ):
            return _base_tokens_cache[sort_by]

        try:
            tokens = await fetch_base_tokens(sort_by=sort_by)
            snapshot = BaseTokenSnapshot(tokens=tokens)
        except (httpx.HTTPError, ValueError) as exc:
            # A refreshed ranking that is rate limited is better served from
            # the previous successful snapshot than as an empty tab.
            stale = _base_tokens_cache.get(sort_by)
            if stale is not None and _is_rate_limited(exc):
                print(f"[BaseTokens] Rate limited, serving cached {sort_by} ranking")
                return stale
            raise HTTPException(
                status_code=502, detail="Unable to fetch Base token market data"
            ) from None

        _base_tokens_cache[sort_by] = snapshot
        _base_tokens_timestamp[sort_by] = time.monotonic()
        return snapshot


TOKEN_VOLUME_NETWORKS = {1: "eth", 8453: "base", 42161: "arbitrum"}
TOKEN_VOLUMES_MAX_ADDRESSES = 100
TOKEN_VOLUMES_MAX_QUERY_LENGTH = 8192
TOKEN_VOLUMES_CACHE_DURATION = 300
TOKEN_VOLUMES_CACHE_MAX_ENTRIES = 1000
_token_volumes_cache: OrderedDict[tuple[int, str], tuple[float, Optional[float]]] = OrderedDict()
_token_volumes_lock = asyncio.Lock()


@router.get("/token-volumes", response_model=TokenVolumesSnapshot)
async def get_token_volumes(
    request: Request,
    chain_id: int = Query(...),
    addresses: str = Query(..., min_length=1, max_length=TOKEN_VOLUMES_MAX_ADDRESSES * 43 - 1),
) -> TokenVolumesSnapshot:
    # Reject ambiguous/coerced input and oversized queries before any provider call.
    if (
        len(request.scope["query_string"]) > TOKEN_VOLUMES_MAX_QUERY_LENGTH
        or len(request.query_params.getlist("chain_id")) != 1
        or len(request.query_params.getlist("addresses")) != 1
        or re.fullmatch(r"[0-9]+", request.query_params["chain_id"]) is None
        or chain_id not in TOKEN_VOLUME_NETWORKS
    ):
        raise HTTPException(status_code=422, detail="Invalid token volume query")
    supplied = addresses.split(",")
    if len(supplied) > TOKEN_VOLUMES_MAX_ADDRESSES or any(
        re.fullmatch(r"0x[0-9a-fA-F]{40}", address) is None for address in supplied
    ):
        raise HTTPException(status_code=422, detail="Invalid token contract addresses")
    unique = list(dict.fromkeys(address.lower() for address in supplied))

    # Recheck freshness under the lock so overlapping concurrent misses share work.
    async with _token_volumes_lock:
        now = time.monotonic()
        volumes: dict[str, Optional[float]] = {}
        missing = []
        for address in unique:
            cached = _token_volumes_cache.get((chain_id, address))
            if cached is not None and now - cached[0] < TOKEN_VOLUMES_CACHE_DURATION:
                volumes[address] = cached[1]
            else:
                missing.append(address)

        if missing:
            try:
                fresh = await fetch_token_volumes(TOKEN_VOLUME_NETWORKS[chain_id], missing)
            except (httpx.HTTPError, ValueError):
                raise HTTPException(status_code=502, detail="Unable to fetch token volumes") from None

            # Publish only after every batch succeeds; failures leave old entries intact.
            completed_at = time.monotonic()
            for address in missing:
                volume = fresh.get(address)
                volumes[address] = volume
                _token_volumes_cache[(chain_id, address)] = (completed_at, volume)

        for address in unique:
            _token_volumes_cache.move_to_end((chain_id, address))
        while len(_token_volumes_cache) > TOKEN_VOLUMES_CACHE_MAX_ENTRIES:
            _token_volumes_cache.popitem(last=False)
        return TokenVolumesSnapshot(chain_id=chain_id, volumes=volumes)
