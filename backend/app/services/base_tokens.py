import json
from pathlib import Path
from typing import Dict, List, Optional

import httpx

from ..models.market import BaseToken
from .coingecko import (
    fetch_base_ecosystem_candidates,
    fetch_coin_base_address,
    fetch_price_changes,
)
from .geckoterminal import (
    fetch_base_token_metrics,
    fetch_base_volume_ranked_addresses,
)


ADDRESS_CACHE_PATH = Path(__file__).resolve().parents[2] / "base_address_cache.json"
RANKING_SIZE = 50
CANDIDATE_POOL_SIZE = 100

# Persistent CoinGecko-id -> Base contract address map. Resolution costs one
# CoinGecko coin-detail call per unknown id, so results are cached on disk;
# steady state needs no detail calls at all. None means "no Base address".
_address_cache: Optional[Dict[str, Optional[str]]] = None


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


async def _resolve_base_addresses(coin_ids: List[str]) -> Dict[str, str]:
    cache = _load_address_cache()
    resolved: Dict[str, str] = {}
    for coin_id in coin_ids:
        if coin_id in cache:
            if cache[coin_id]:
                resolved[coin_id] = cache[coin_id]
            continue
        address = await fetch_coin_base_address(coin_id)
        cache[coin_id] = address
        _save_address_cache()
        if address:
            resolved[coin_id] = address
    return resolved


async def _fetch_cap_ranked() -> List[BaseToken]:
    candidates = await fetch_base_ecosystem_candidates(limit=CANDIDATE_POOL_SIZE)
    id_to_address = await _resolve_base_addresses([c.id for c in candidates])
    metrics = await fetch_base_token_metrics(list(id_to_address.values()))

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


async def _fetch_volume_ranked() -> List[BaseToken]:
    addresses, volumes = await fetch_base_volume_ranked_addresses()
    metrics = await fetch_base_token_metrics(addresses[:RANKING_SIZE])

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
