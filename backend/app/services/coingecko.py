from math import isfinite
from typing import Dict, List, Optional

import httpx

from ..core.config import COINGECKO_API_KEY
from ..models.market import TradingPair


COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"

# Map trading symbols to Coingecko coin IDs.
# These IDs are stable and correspond to the /coins/markets endpoint.
COINGECKO_SYMBOL_ID_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "WETH": "weth",
    "USDC": "usd-coin",
    "USDT": "tether",
    "DAI": "dai",
    "AERO": "aerodrome-finance",
    "DEGEN": "degen-base",
    "BRETT": "based-brett",
    "TOSHI": "toshi",
    "MOCHI": "mochi-thecatcoin",
    "ARB": "arbitrum",
    "GMX": "gmx",
    "SHIB": "shiba-inu",
    "LINK": "chainlink",
    "UNI": "uniswap",
    "MATIC": "matic-network",
    "CRV": "curve-dao-token",
    "GRT": "the-graph",
    "WBTC": "wrapped-bitcoin",
    "AAVE": "aave",
    "VIRTUAL": "virtual-protocol",
    "AVNT": "avantis",
    "CLANKER": "tokenbot-2",
    "AIXBT": "aixbt",
    "CBBTC": "coinbase-wrapped-btc",
    "TIBBIR": "ribbita-by-virtuals",
    "LUNA": "luna-by-virtuals",
    "PYTH": "pyth-network",
    "VVV": "venice-token",
    "XCN": "chain-2",
    "1INCH": "1inch",
    "W": "wormhole",
    "MOVE": "movement",
    "MOCA": "mocaverse",
    "BIO": "bio-protocol",
    "FAI": "freysa-ai",
    "BONK": "bonk",
    "PEPE": "pepe",
    "ENA": "ethena",
    "ICP": "internet-computer",
    "MORPHO": "morpho",
    "ETHFI": "ether-fi",
    "ZRO": "layerzero",
}


async def fetch_coingecko_pairs(symbols: List[str], convert: str = "USD") -> List[TradingPair]:
    """Fetch price data from Coingecko for a list of symbols."""
    ids = []
    for s in symbols:
        cid = COINGECKO_SYMBOL_ID_MAP.get(s)
        if cid:
            ids.append(cid)

    if not ids:
        return []

    params = {
        "vs_currency": convert.lower(),
        "ids": ",".join(ids),
        "sparkline": "false",
    }
    headers = {"Accept": "application/json"}
    if COINGECKO_API_KEY:
        # CoinGecko demo API expects the hyphenated header name; headers with
        # underscores are dropped by their CDN and the request is treated as
        # anonymous (now blocked with a CloudFront 403).
        headers["x-cg-demo-api-key"] = COINGECKO_API_KEY

    pairs: List[TradingPair] = []
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            response = await client.get(
                f"{COINGECKO_BASE_URL}/coins/markets",
                params=params,
                headers=headers,
            )
            if response.status_code == 200:
                data = response.json()
                for item in data:
                    p = _parse_coingecko_item(item, convert)
                    if p:
                        pairs.append(p)
            else:
                print(f"Coingecko error: {response.status_code} {response.text}")
        except Exception as e:
            print(f"Error fetching from Coingecko: {e}")

    return pairs


def _parse_coingecko_item(item: dict, convert: str) -> Optional[TradingPair]:
    symbol = item.get("symbol", "").upper()
    price = item.get("current_price")
    change = item.get("price_change_percentage_24h")
    volume = item.get("total_volume")
    id_str = item.get("id", "")

    if not symbol or price is None:
        return None

    url = None
    if id_str:
        url = f"https://www.coingecko.com/en/coins/{id_str}/"

    return TradingPair(
        base_symbol=symbol,
        quote_symbol=convert,
        price=float(price),
        change_24h=float(change) if change is not None else 0.0,
        volume_24h=float(volume) if volume is not None else None,
        cmc_url=url,
    )


def _finite_number(value: object) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def _headers() -> dict:
    headers = {"Accept": "application/json"}
    if COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = COINGECKO_API_KEY
    return headers


class BaseEcosystemCandidate:
    def __init__(self, coin_id: str, name: str, symbol: str, change_24h: Optional[float]):
        self.id = coin_id
        self.name = name
        self.symbol = symbol
        self.change_24h = change_24h


async def fetch_base_ecosystem_candidates(limit: int = 100) -> List[BaseEcosystemCandidate]:
    """Top Base-ecosystem coins by GLOBAL market cap.

    Only used as a candidate pool: CoinGecko's category membership says a coin
    exists on Base, but its market metrics are global. Base-chain metrics are
    resolved separately via GeckoTerminal.
    """
    params = {
        "vs_currency": "usd",
        "category": "base-ecosystem",
        "order": "market_cap_desc",
        "per_page": limit,
        "page": 1,
        "sparkline": "false",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            f"{COINGECKO_BASE_URL}/coins/markets", params=params, headers=_headers()
        )
        response.raise_for_status()
        data = response.json()

    if not isinstance(data, list):
        raise ValueError("Invalid CoinGecko markets payload")

    candidates: List[BaseEcosystemCandidate] = []
    for item in data:
        if not isinstance(item, dict) or any(
            not isinstance(item.get(field), str) or not item[field].strip()
            for field in ("id", "name", "symbol")
        ):
            raise ValueError("Invalid CoinGecko token identity")
        candidates.append(
            BaseEcosystemCandidate(
                coin_id=item["id"],
                name=item["name"],
                symbol=item["symbol"],
                change_24h=_finite_number(item.get("price_change_percentage_24h")),
            )
        )
    if not candidates:
        raise ValueError("No usable CoinGecko Base candidates")
    return candidates


async def fetch_coin_base_address(coin_id: str) -> Optional[str]:
    """Resolve a coin's Base contract address, or None if it has none."""
    params = {
        "localization": "false",
        "tickers": "false",
        "market_data": "false",
        "community_data": "false",
        "developer_data": "false",
        "sparkline": "false",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            f"{COINGECKO_BASE_URL}/coins/{coin_id}", params=params, headers=_headers()
        )
        response.raise_for_status()
        data = response.json()

    if not isinstance(data, dict):
        raise ValueError("Invalid CoinGecko coin payload")
    platforms = data.get("platforms")
    if not isinstance(platforms, dict):
        return None
    address = platforms.get("base")
    if not isinstance(address, str) or not address.startswith("0x"):
        return None
    return address.lower()


async def fetch_price_changes(coin_ids: List[str]) -> Dict[str, Optional[float]]:
    """24h price change per coin id. Prices arbitrage across chains, so the
    global change is a fine approximation for the Base-market change."""
    if not coin_ids:
        return {}
    params = {
        "vs_currency": "usd",
        "ids": ",".join(coin_ids),
        "sparkline": "false",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            f"{COINGECKO_BASE_URL}/coins/markets", params=params, headers=_headers()
        )
        response.raise_for_status()
        data = response.json()

    if not isinstance(data, list):
        raise ValueError("Invalid CoinGecko markets payload")
    changes: Dict[str, Optional[float]] = {}
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            changes[item["id"]] = _finite_number(item.get("price_change_percentage_24h"))
    return changes
