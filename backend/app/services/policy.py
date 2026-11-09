"""Shared execution policy constants.

The browser executor duplicates this list in TypeScript; keep the two in sync.
"""

AUTO_TRADE_TARGETS = ("ETH", "WETH", "VVV", "VIRTUAL", "AERO", "TIBBIR", "AVNT")
STABLECOINS = ("USDC", "USDT", "DAI")


def is_auto_tradeable(symbol: str) -> bool:
    return symbol.upper() in AUTO_TRADE_TARGETS
