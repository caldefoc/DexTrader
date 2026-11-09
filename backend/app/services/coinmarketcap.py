from typing import List, Optional

import httpx

from ..core.config import COINMARKETCAP_API_KEY
from ..models.market import TradingPair


CMC_BASE_URL = "https://pro-api.coinmarketcap.com/trial-pro-api"

# Tokens we explicitly want to track to ensure they appear in the UI
# regardless of their market cap rank.
PRIORITY_SYMBOLS = [
    "BTC", "ETH", "SOL", "WETH", "USDC", "USDT", "DAI",
    "AERO", "DEGEN", "BRETT", "TOSHI", "MOCHI", # "BDOGE",  # Base tokens (BDOGE disabled until valid slug/symbol found)
    "ARB", "GMX", # Arbitrum
    "SHIB", # Memes
    "LINK", "UNI", "MATIC", "CRV", "GRT", "WBTC", "AAVE", # DeFi/Infra
    "VIRTUAL", "AVNT", "CLANKER", "AIXBT", "CBBTC",
    "TIBBIR", "LUNA",  # ETHY temporarily removed (not yet on CMC)
    "PYTH", "VVV", "XCN", "1INCH", "W", "MOVE", "MOCA", "FAI", "RED", "BIO", "GPS",  # Additional Base tokens (SIGN removed - insufficient liquidity)
    "ENA", "ICP", "MORPHO", "ETHFI", "ZRO",
]

# Map specific symbols to slugs to resolve ambiguity (e.g. DEGEN on Base)
# These slugs must be correct CoinMarketCap slugs.
# ONLY add entries here when the symbol is ambiguous on CMC (multiple tokens share the same symbol).
# Tokens with unique symbols should NOT be in this map — they will be fetched by symbol instead,
# which is more resilient (one bad slug in a batch request crashes the entire batch).
SYMBOL_SLUG_MAP = {
    # Base ecosystem tokens (ambiguous symbols)
    "DEGEN": "degen-base",
    "BRETT": "based-brett",
    "TOSHI": "toshithecat",
    "MOCHI": "mochi-the-catcoin-new",
    # "BDOGE": "based-doge-1"  # Disable until valid slug found
    "VIRTUAL": "virtual-protocol",
    "AVNT": "avantis",
    "CLANKER": "tokenbot-2",
    "AIXBT": "aixbt",
    "CBBTC": "coinbase-wrapped-btc",
    "TIBBIR": "ribbita-by-virtuals",
    "LUNA": "luna-by-virtuals",
    # "ETHY": "ethy-ai"  # Not yet listed on CMC, commented out
    # Arbitrum
    "ARB": "arbitrum",
    "GMX": "gmx",
    # New Base tokens (only those with ambiguous symbols)
    "W": "wormhole",          # "W" is too short/ambiguous
    "MOVE": "movement",       # Multiple MOVE tokens on CMC
    # "SIGN": "sign",         # Removed - insufficient liquidity on Base
    "MOCA": "mocaverse",      # CMC slug differs from expected
    "BIO": "bio",             # BioCrypt also uses BIO symbol
}

async def fetch_market_pairs(limit: int = 50, convert: str = "USD") -> List[TradingPair]:
    params = {"start": "1", "limit": str(limit), "convert": convert}
    headers = {"Accept": "application/json"}
    # Only send API key for non-trial endpoints; trial API is keyless
    # and sending an invalid/expired key results in 401 Unauthorized
    if COINMARKETCAP_API_KEY and "trial-pro-api" not in CMC_BASE_URL:
        headers["X-CMC_PRO_API_KEY"] = COINMARKETCAP_API_KEY
    
    pairs: List[TradingPair] = []
    found_symbols = set()

    async with httpx.AsyncClient(timeout=10) as client:
        # 1. Fetch top rankings
        try:
            response = await client.get(
                f"{CMC_BASE_URL}/v1/cryptocurrency/listings/latest",
                params=params,
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data", [])
            
            for item in data:
                p = _parse_item(item, convert)
                if p:
                    pairs.append(p)
                    found_symbols.add(p.base_symbol.upper())
        except Exception as e:
            print(f"Error fetching top listings: {e}")

        # 2. Fetch missing priority tokens via CMC quotes/latest
        # NOTE: The trial-pro-api path only supports listings/latest keyless.
        # quotes/latest requires an API key on the trial path (returns 403),
        # so we skip CMC quotes when using the trial API and fall through to CoinGecko.
        is_trial = "trial-pro-api" in CMC_BASE_URL
        missing = [s for s in PRIORITY_SYMBOLS if s not in found_symbols]
        
        if missing and not is_trial:
            # Split into standard symbols and slug-mapped symbols
            missing_symbols = []
            missing_slugs = []
            
            for s in missing:
                if s in SYMBOL_SLUG_MAP:
                    missing_slugs.append(SYMBOL_SLUG_MAP[s])
                else:
                    missing_symbols.append(s)
            
            # A. Fetch by Symbol (in batches to prevent one bad symbol from crashing all)
            if missing_symbols:
                SYMBOL_BATCH_SIZE = 5
                for i in range(0, len(missing_symbols), SYMBOL_BATCH_SIZE):
                    batch = missing_symbols[i:i + SYMBOL_BATCH_SIZE]
                    try:
                        quotes_params = {"symbol": ",".join(batch), "convert": convert}
                        response = await client.get(
                            f"{CMC_BASE_URL}/v1/cryptocurrency/quotes/latest",
                            params=quotes_params,
                            headers=headers,
                        )
                        if response.status_code == 200:
                            payload = response.json()
                            data_dict = payload.get("data", {})
                            
                            for symbol, item in data_dict.items():
                                target_item = item
                                if isinstance(item, list):
                                    target_item = item[0] 
                                
                                p = _parse_item(target_item, convert)
                                if p:
                                    pairs.append(p)
                                    found_symbols.add(p.base_symbol.upper())
                        else:
                            print(f"Error fetching symbol batch {batch}: {response.status_code} {response.text}")
                    except Exception as e:
                        print(f"Error fetching quotes by symbol batch {batch}: {e}")

            # B. Fetch by Slug (in batches to prevent one bad slug from crashing all)
            if missing_slugs:
                SLUG_BATCH_SIZE = 10
                for i in range(0, len(missing_slugs), SLUG_BATCH_SIZE):
                    batch = missing_slugs[i:i + SLUG_BATCH_SIZE]
                    try:
                        quotes_params = {"slug": ",".join(batch), "convert": convert}
                        response = await client.get(
                            f"{CMC_BASE_URL}/v1/cryptocurrency/quotes/latest",
                            params=quotes_params,
                            headers=headers,
                        )
                        if response.status_code == 200:
                            payload = response.json()
                            data_dict = payload.get("data", {})
                            
                            for _, item in data_dict.items():
                                target_item = item
                                p = _parse_item(target_item, convert)
                                if p:
                                    pairs.append(p)
                                    found_symbols.add(p.base_symbol.upper())
                        else:
                             print(f"Error fetching slug batch {batch}: {response.status_code} {response.text}")
                    except Exception as e:
                        print(f"Error fetching quotes by slug batch {batch}: {e}")

    # 3. Fallback to Coingecko for any still-missing priority tokens
    still_missing = [s for s in PRIORITY_SYMBOLS if s not in found_symbols]
    if still_missing:
        from ..services.coingecko import fetch_coingecko_pairs
        cg_pairs = await fetch_coingecko_pairs(still_missing, convert)
        for p in cg_pairs:
            if p.base_symbol.upper() not in found_symbols:
                pairs.append(p)
                found_symbols.add(p.base_symbol.upper())

    return pairs

def _parse_item(item: dict, convert: str) -> Optional[TradingPair]:
    symbol = item.get("symbol")
    quote = item.get("quote", {}).get(convert, {})
    price = quote.get("price")
    change = quote.get("percent_change_24h")
    volume = quote.get("volume_24h")
    slug = item.get("slug")
    
    if symbol is None or price is None:
        return None
        
    cmc_url = None
    if slug:
        cmc_url = f"https://coinmarketcap.com/currencies/{slug}/"
        
    return TradingPair(
        base_symbol=symbol,
        quote_symbol=convert,
        price=float(price),
        change_24h=float(change) if change is not None else 0.0,
        volume_24h=float(volume) if volume is not None else None,
        cmc_url=cmc_url,
    )
