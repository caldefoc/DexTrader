"""Keyless Base token metrics from DexScreener.

Used as a fallback when GeckoTerminal is unavailable or Cloudflare-challenged.
DexScreener reports chain-specific price, FDV and 24h volume per pair, so the
Base ranking keeps the same meaning it has with GeckoTerminal data.
"""

from math import isfinite
from typing import Dict, Iterable, List, Optional

import httpx

from .geckoterminal import BaseTokenMetrics


DEXSCREENER_BASE_URL = "https://api.dexscreener.com"
MAX_ADDRESSES_PER_REQUEST = 30


def _finite_number(value: object) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def _liquidity(pair: dict) -> float:
    liquidity = pair.get("liquidity")
    value = _finite_number(liquidity.get("usd")) if isinstance(liquidity, dict) else None
    return value if value is not None and value >= 0 else 0.0


def _metrics_from_pair(pair: dict) -> Optional[BaseTokenMetrics]:
    token = pair.get("baseToken")
    if not isinstance(token, dict):
        return None
    address = token.get("address")
    name = token.get("name")
    symbol = token.get("symbol")
    if not (
        isinstance(address, str)
        and address.startswith("0x")
        and isinstance(name, str)
        and name.strip()
        and isinstance(symbol, str)
        and symbol.strip()
    ):
        return None

    price = _finite_number(pair.get("priceUsd"))
    if price is None or price <= 0:
        return None

    fdv = _finite_number(pair.get("fdv"))
    if fdv is not None and fdv < 0:
        fdv = None

    volume: Optional[float] = None
    volumes = pair.get("volume")
    if isinstance(volumes, dict):
        volume = _finite_number(volumes.get("h24"))
    if volume is not None and volume < 0:
        volume = None

    return BaseTokenMetrics(
        address=address.lower(),
        name=name,
        symbol=symbol,
        price=price,
        fdv=fdv,
        volume_24h=volume,
        coingecko_id=None,
    )


def _chunks(items: List[str], size: int) -> Iterable[List[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


async def fetch_token_metrics(addresses: List[str]) -> Dict[str, BaseTokenMetrics]:
    """Base-chain metrics per contract address, deepest pool per token."""
    unique = list(dict.fromkeys(address.lower() for address in addresses if address))
    requested = set(unique)
    best: Dict[str, tuple[float, BaseTokenMetrics]] = {}

    async with httpx.AsyncClient(
        timeout=20, headers={"Accept": "application/json"}
    ) as client:
        for batch in _chunks(unique, MAX_ADDRESSES_PER_REQUEST):
            response = await client.get(
                f"{DEXSCREENER_BASE_URL}/tokens/v1/base/{','.join(batch)}"
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise ValueError("Invalid DexScreener tokens payload")
            for pair in payload:
                if not isinstance(pair, dict):
                    raise ValueError("Invalid DexScreener pair")
                metrics = _metrics_from_pair(pair)
                if metrics is None or metrics.address not in requested:
                    continue
                liquidity = _liquidity(pair)
                current = best.get(metrics.address)
                if current is None or liquidity > current[0]:
                    best[metrics.address] = (liquidity, metrics)

    if not best:
        raise ValueError("No usable DexScreener metrics")
    return {address: metrics for address, (_, metrics) in best.items()}
