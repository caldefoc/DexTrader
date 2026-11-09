import asyncio
import json
import time
from pathlib import Path
from typing import Dict, List, Optional

import httpx

from ..models.market import BaseToken
from .coingecko import (
    fetch_base_address_map,
    fetch_base_ecosystem_candidates,
    fetch_coin_base_address,
    fetch_price_changes,
)
from .dexscreener import fetch_token_metrics as fetch_dexscreener_metrics
from .geckoterminal import (
    fetch_base_token_metrics,
    fetch_base_volume_ranked_addresses,
)
from .state_store import state_path


# Both caches live in the state directory (a mounted volume in Docker) so a
# container restart does not force a full re-resolution burst.
ADDRESS_CACHE_PATH = Path(state_path("base_address_cache.json"))
PLATFORM_MAP_PATH = Path(state_path("base_platform_map.json"))
PLATFORM_MAP_TTL = 12 * 3600
RANKING_SIZE = 50
CANDIDATE_POOL_SIZE = 100

# Persistent CoinGecko-id -> Base contract address map. Resolution costs one
# CoinGecko coin-detail call per unknown id, so results are cached on disk;
# steady state needs no detail calls at all. None means "no Base address".
_address_cache: Optional[Dict[str, Optional[str]]] = None

# Whole-catalogue id -> Base address snapshot fetched in a single request.
# Guarded by its own timestamp so it is refreshed once per TTL, not per request.
_platform_map: Optional[Dict[str, Optional[str]]] = None
_platform_map_timestamp: float = 0.0
_platform_map_lock = asyncio.Lock()


def _load_address_cache() -> Dict[str, Optional[str]]:
    global _address_cache
    if _address_cache is None:
        cache: Dict[str, Optional[str]] = {}
        try:
            data = json.loads(ADDRESS_CACHE_PATH.read_text())
            addresses = data.get("addresses") if isinstance(data, dict) else None
            if isinstance(addresses, dict):
                for key, value in addresses.items():
                    if isinstance(key, str) and (value is None or isinstance(value, str)):
                        cache[key] = value
        except (OSError, ValueError):
            cache = {}
        _address_cache = cache
    return _address_cache


def _save_address_cache() -> None:
    if _address_cache is None:
        return
    try:
        tmp_path = ADDRESS_CACHE_PATH.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps({"version": 1, "addresses": _address_cache}, indent=2, sort_keys=True)
        )
        tmp_path.replace(ADDRESS_CACHE_PATH)
    except OSError:
        pass  # The cache is best-effort; it must never fail a request.


def _load_platform_map() -> Dict[str, Optional[str]]:
    """Disk-backed platform snapshot; empty when missing, stale or unreadable."""
    global _platform_map, _platform_map_timestamp
    if _platform_map is not None:
        return _platform_map
    try:
        data = json.loads(PLATFORM_MAP_PATH.read_text())
        fetched_at = float(data.get("fetched_at", 0))
        addresses = data.get("addresses")
        if not isinstance(addresses, dict):
            raise ValueError("missing addresses")
        if time.time() - fetched_at > PLATFORM_MAP_TTL:
            raise ValueError("stale platform map")
        _platform_map = {
            key: value
            for key, value in addresses.items()
            if isinstance(key, str) and (value is None or isinstance(value, str))
        }
        _platform_map_timestamp = fetched_at
    except (OSError, ValueError, TypeError):
        _platform_map = {}
    return _platform_map


def _save_platform_map(addresses: Dict[str, Optional[str]]) -> None:
    try:
        PLATFORM_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = PLATFORM_MAP_PATH.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(
                {"version": 1, "fetched_at": _platform_map_timestamp, "addresses": addresses}
            )
        )
        tmp_path.replace(PLATFORM_MAP_PATH)
    except OSError:
        pass  # Best effort; the ranking must not fail because of a cache write.


async def _get_platform_map() -> Dict[str, Optional[str]]:
    """Fetch (at most once per TTL) the id -> Base address catalogue snapshot."""
    global _platform_map, _platform_map_timestamp
    cached = _load_platform_map()
    if time.time() - _platform_map_timestamp <= PLATFORM_MAP_TTL:
        return cached
    async with _platform_map_lock:
        if time.time() - _platform_map_timestamp <= PLATFORM_MAP_TTL:
            return _platform_map or {}
        try:
            addresses = await fetch_base_address_map()
        except (httpx.HTTPError, ValueError):
            # The per-coin detail path below is still a valid fallback.  Back
            # off for a full TTL so a provider outage cannot amplify into a
            # retry storm against the same rate limit.
            _platform_map_timestamp = time.time()
            return cached
        _platform_map = addresses
        _platform_map_timestamp = time.time()
        _save_platform_map(addresses)
        return addresses


async def _resolve_base_addresses(coin_ids: List[str]) -> Dict[str, str]:
    cache = _load_address_cache()
    resolved: Dict[str, str] = {}
    unknown: List[str] = []
    for coin_id in coin_ids:
        if coin_id in cache:
            if cache[coin_id]:
                resolved[coin_id] = cache[coin_id]
            continue
        unknown.append(coin_id)

    if unknown:
        # Bulk lookup keeps steady-state resolution to a single CoinGecko call.
        platforms = await _get_platform_map()
        for coin_id in list(unknown):
            if coin_id not in platforms:
                continue
            address = platforms[coin_id]
            cache[coin_id] = address
            if address:
                resolved[coin_id] = address
            unknown.remove(coin_id)
        if unknown:
            _save_address_cache()

    for coin_id in unknown:
        address = await fetch_coin_base_address(coin_id)
        cache[coin_id] = address
        _save_address_cache()
        if address:
            resolved[coin_id] = address
    return resolved


async def _fetch_metrics(addresses: List[str]) -> Dict[str, object]:
    """Base-chain metrics, falling back to DexScreener when GeckoTerminal fails.

    GeckoTerminal sits behind Cloudflare and challenges unattended clients, so
    a second keyless provider keeps the ranking available.
    """
    try:
        return await fetch_base_token_metrics(addresses)
    except (httpx.HTTPError, ValueError) as exc:
        print(f"[BaseTokens] GeckoTerminal unavailable ({exc}); using DexScreener")
        return await fetch_dexscreener_metrics(addresses)


async def _fetch_cap_ranked() -> List[BaseToken]:
    candidates = await fetch_base_ecosystem_candidates(limit=CANDIDATE_POOL_SIZE)
    id_to_address = await _resolve_base_addresses([c.id for c in candidates])
    metrics = await _fetch_metrics(list(id_to_address.values()))

    # Rank by Base FDV (Base total supply x Base DEX price). CoinGecko's own
    # market_cap is a global all-chain figure and must not be used here.
    entries = []
    for candidate in candidates:
        address = id_to_address.get(candidate.id)
        if address is None:
            continue
        metric = metrics.get(address)
        if metric is None or metric.fdv is None or metric.fdv <= 0:
            continue
        entries.append((candidate, metric))
    entries.sort(key=lambda entry: entry[1].fdv, reverse=True)

    tokens: List[BaseToken] = []
    seen_addresses = set()
    for candidate, metric in entries:
        if metric.address in seen_addresses:
            continue
        seen_addresses.add(metric.address)
        tokens.append(
            BaseToken(
                id=candidate.id,
                name=metric.name,
                symbol=metric.symbol.upper(),
                price=metric.price,
                change_24h=candidate.change_24h,
                volume_24h=metric.volume_24h,
                market_cap=metric.fdv,
            )
        )
        if len(tokens) == RANKING_SIZE:
            break
    if not tokens:
        raise ValueError("No usable Base token metrics")
    return tokens


async def _fetch_volume_ranked_from_candidates() -> List[BaseToken]:
    """Volume ranking without GeckoTerminal pools: rank tracked Base coins."""
    candidates = await fetch_base_ecosystem_candidates(limit=CANDIDATE_POOL_SIZE)
    id_to_address = await _resolve_base_addresses([c.id for c in candidates])
    metrics = await _fetch_metrics(list(id_to_address.values()))

    entries = []
    for candidate in candidates:
        address = id_to_address.get(candidate.id)
        metric = metrics.get(address) if address else None
        if metric is None or metric.volume_24h is None or metric.volume_24h <= 0:
            continue
        entries.append((candidate, metric))
    entries.sort(key=lambda entry: entry[1].volume_24h, reverse=True)

    tokens: List[BaseToken] = []
    seen_addresses = set()
    for candidate, metric in entries:
        if metric.address in seen_addresses:
            continue
        seen_addresses.add(metric.address)
        tokens.append(
            BaseToken(
                id=candidate.id,
                name=metric.name,
                symbol=metric.symbol.upper(),
                price=metric.price,
                change_24h=candidate.change_24h,
                volume_24h=metric.volume_24h,
                market_cap=metric.fdv,
            )
        )
        if len(tokens) == RANKING_SIZE:
            break
    if not tokens:
        raise ValueError("No usable Base token metrics")
    return tokens


async def _fetch_volume_ranked() -> List[BaseToken]:
    try:
        addresses, volumes = await fetch_base_volume_ranked_addresses()
    except (httpx.HTTPError, ValueError) as exc:
        print(f"[BaseTokens] GeckoTerminal pools unavailable ({exc}); ranking by candidates")
        return await _fetch_volume_ranked_from_candidates()
    metrics = await _fetch_metrics(addresses[:RANKING_SIZE])

    tokens: List[BaseToken] = []
    for address in addresses:
        metric = metrics.get(address)
        if metric is None:
            continue
        tokens.append(
            BaseToken(
                id=metric.coingecko_id or f"base-{address}",
                name=metric.name,
                symbol=metric.symbol.upper(),
                price=metric.price,
                change_24h=None,
                volume_24h=volumes[address],
                market_cap=metric.fdv,
            )
        )
        if len(tokens) == RANKING_SIZE:
            break
    if not tokens:
        raise ValueError("No usable Base token metrics")

    # Enrichment only: a CoinGecko outage must not fail the ranking.
    known_ids = [t.id for t in tokens if not t.id.startswith("base-")]
    try:
        changes = await fetch_price_changes(known_ids)
    except (httpx.HTTPError, ValueError):
        changes = {}
    for token in tokens:
        token.change_24h = changes.get(token.id)
    return tokens


async def fetch_base_tokens(sort_by: str = "market_cap") -> List[BaseToken]:
    if sort_by == "market_cap":
        return await _fetch_cap_ranked()
    if sort_by == "volume_24h":
        return await _fetch_volume_ranked()
    raise ValueError("Invalid Base token ranking")
