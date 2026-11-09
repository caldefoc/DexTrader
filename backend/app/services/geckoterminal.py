from math import isfinite
from typing import Dict, List, Optional, Tuple

import asyncio

import httpx


GECKOTERMINAL_BASE_URL = "https://api.geckoterminal.com/api/v2"

MAX_ADDRESSES_PER_REQUEST = 30
POOL_PAGES = 10  # 20 pools per page -> top 200 Base pools by 24h volume
# The free tier throttles bursts hard; pace pool pagination and retry 429s.
POOL_PAGE_DELAY = 6.0
RATE_LIMIT_RETRY_DELAY = 20.0

# Cloudflare in front of GeckoTerminal rejects clients that look like bare
# automation, so identify the demo and always request JSON.
GECKOTERMINAL_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "DexTraderDemo/1.0 (+https://dextrader.caldefoc.com)",
}

# Quote assets on Base DEX pools. Pool volume is attributed to the non-quote
# side only, so these tokens do not absorb the volume of every pool they quote.
QUOTE_TOKEN_ADDRESSES = {
    "0x4200000000000000000000000000000000000006",  # WETH
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",  # USDC
    "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca",  # USDbC
    "0x50c5725949a6f0c72e6c4a641f24049a917db0cb",  # DAI
    "0xfde4c96c8593536e31f229ea8f37b2ada2699bb2",  # USDT
}


def _finite_number(value: object) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


class BaseTokenMetrics:
    def __init__(
        self,
        address: str,
        name: str,
        symbol: str,
        price: float,
        fdv: Optional[float],
        volume_24h: Optional[float],
        coingecko_id: Optional[str],
    ):
        self.address = address
        self.name = name
        self.symbol = symbol
        self.price = price
        self.fdv = fdv
        self.volume_24h = volume_24h
        self.coingecko_id = coingecko_id


def _parse_token(item: object) -> Optional[BaseTokenMetrics]:
    if not isinstance(item, dict):
        return None
    attributes = item.get("attributes")
    if not isinstance(attributes, dict):
        return None
    address = attributes.get("address")
    name = attributes.get("name")
    symbol = attributes.get("symbol")
    if not (
        isinstance(address, str)
        and address.startswith("0x")
        and isinstance(name, str)
        and name.strip()
        and isinstance(symbol, str)
        and symbol.strip()
    ):
        return None
    price = _finite_number(attributes.get("price_usd"))
    if price is None or price < 0:
        return None
    fdv = _finite_number(attributes.get("fdv_usd"))
    if fdv is not None and fdv < 0:
        fdv = None
    volume = None
    volume_usd = attributes.get("volume_usd")
    if isinstance(volume_usd, dict):
        volume = _finite_number(volume_usd.get("h24"))
    if volume is not None and volume < 0:
        volume = None
    coingecko_id = attributes.get("coingecko_coin_id")
    if not isinstance(coingecko_id, str) or not coingecko_id.strip():
        coingecko_id = None
    return BaseTokenMetrics(
        address=address.lower(),
        name=name,
        symbol=symbol,
        price=price,
        fdv=fdv,
        volume_24h=volume,
        coingecko_id=coingecko_id,
    )


async def _get_json(client: httpx.AsyncClient, url: str, **kwargs) -> dict:
    for attempt in range(2):
        response = await client.get(url, **kwargs)
        if response.status_code == 429 and attempt == 0:
            await asyncio.sleep(RATE_LIMIT_RETRY_DELAY)
            continue
        response.raise_for_status()
        return response.json()
    raise ValueError("unreachable")


async def _fetch_tokens(network: str, addresses: List[str]) -> List[dict]:
    """Fetch requested raw tokens with shared batching and rate-limit retries."""
    if network not in ("eth", "base", "arbitrum"):
        raise ValueError("Unsupported GeckoTerminal network")
    unique = list(dict.fromkeys(address.lower() for address in addresses))
    tokens: List[dict] = []
    async with httpx.AsyncClient(timeout=15, headers=GECKOTERMINAL_HEADERS) as client:
        for start in range(0, len(unique), MAX_ADDRESSES_PER_REQUEST):
            batch = unique[start : start + MAX_ADDRESSES_PER_REQUEST]
            payload = await _get_json(
                client,
                f"{GECKOTERMINAL_BASE_URL}/networks/{network}/tokens/multi/{','.join(batch)}",
                headers={"Accept": "application/json"},
            )
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise ValueError("Invalid GeckoTerminal tokens payload")
            for item in payload["data"]:
                if not isinstance(item, dict):
                    continue
                attributes = item.get("attributes")
                if not isinstance(attributes, dict):
                    continue
                address = attributes.get("address")
                if isinstance(address, str) and address.lower() in batch:
                    tokens.append(item)
    return tokens


async def fetch_base_token_metrics(addresses: List[str]) -> Dict[str, BaseTokenMetrics]:
    """Batch-fetch Base-chain metrics for token contracts.

    price/fdv/volume are Base-chain only: price comes from Base DEX pools, fdv
    is Base total supply times that price, volume is Base DEX 24h volume.
    Tokens GeckoTerminal does not know are omitted from the result.
    """
    tokens = await _fetch_tokens("base", addresses)
    metrics: Dict[str, BaseTokenMetrics] = {}
    for item in tokens:
        parsed = _parse_token(item)
        if parsed:
            metrics[parsed.address] = parsed
    return metrics


async def fetch_token_volumes(network: str, addresses: List[str]) -> Dict[str, Optional[float]]:
    """Return chain-local h24 DEX USD volumes, independent of price/metadata."""
    tokens = await _fetch_tokens(network, addresses)
    volumes: Dict[str, Optional[float]] = dict.fromkeys(address.lower() for address in addresses)
    for item in tokens:
        attributes = item["attributes"]
        volume = None
        volume_usd = attributes.get("volume_usd")
        if isinstance(volume_usd, dict):
            volume = _finite_number(volume_usd.get("h24"))
        volumes[attributes["address"].lower()] = volume if volume is not None and volume >= 0 else None
    return volumes


def _pool_token_address(pool: dict, side: str) -> Optional[str]:
    relationships = pool.get("relationships")
    if not isinstance(relationships, dict):
        return None
    token = relationships.get(f"{side}_token")
    if not isinstance(token, dict):
        return None
    data = token.get("data")
    if not isinstance(data, dict):
        return None
    token_id = data.get("id")
    if not isinstance(token_id, str) or not token_id.startswith("base_0x"):
        return None
    return token_id[len("base_") :].lower()


async def fetch_base_volume_ranked_addresses() -> Tuple[List[str], Dict[str, float]]:
    """Rank Base tokens by attributed 24h DEX volume.

    Scans the top Base pools by 24h volume and attributes each pool's volume to
    its non-quote-side token (pools between two quote assets are skipped), so
    WETH/USDC do not absorb the volume of every pool they quote. Returns the
    ranked addresses and the attributed volume per address.
    """
    volumes: Dict[str, float] = {}
    async with httpx.AsyncClient(timeout=15, headers=GECKOTERMINAL_HEADERS) as client:
        for page in range(1, POOL_PAGES + 1):
            if page > 1:
                await asyncio.sleep(POOL_PAGE_DELAY)
            payload = await _get_json(
                client,
                f"{GECKOTERMINAL_BASE_URL}/networks/base/pools",
                params={"sort": "h24_volume_usd_desc", "page": page},
                headers={"Accept": "application/json"},
            )
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise ValueError("Invalid GeckoTerminal pools payload")
            pools = payload["data"]
            for pool in pools:
                if not isinstance(pool, dict):
                    raise ValueError("Invalid GeckoTerminal pool entry")
                attributes = pool.get("attributes")
                if not isinstance(attributes, dict):
                    raise ValueError("Invalid GeckoTerminal pool attributes")
                volume_usd = attributes.get("volume_usd")
                if not isinstance(volume_usd, dict):
                    raise ValueError("Invalid GeckoTerminal pool volume")
                volume = _finite_number(volume_usd.get("h24"))
                if volume is None or volume < 0:
                    raise ValueError("Invalid GeckoTerminal pool volume")
                base = _pool_token_address(pool, "base")
                quote = _pool_token_address(pool, "quote")
                if base is None or quote is None:
                    raise ValueError("Invalid GeckoTerminal pool tokens")
                if base in QUOTE_TOKEN_ADDRESSES and quote in QUOTE_TOKEN_ADDRESSES:
                    continue
                target = quote if base in QUOTE_TOKEN_ADDRESSES else base
                volumes[target] = volumes.get(target, 0.0) + volume
            if len(pools) < 20:  # GT page size: a short page means no more pages.
                break

    ranked = sorted(volumes, key=lambda address: volumes[address], reverse=True)
    return ranked, volumes
