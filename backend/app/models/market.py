from pydantic import BaseModel
from typing import List, Optional


class TradingPair(BaseModel):
    base_symbol: str
    quote_symbol: str
    price: float
    change_24h: float
    volume_24h: Optional[float] = None
    cmc_url: Optional[str] = None


class MarketSnapshot(BaseModel):
    pairs: List[TradingPair]
    timestamp: Optional[float] = None


class GainersLosers(BaseModel):
    gainers: List[TradingPair]
    losers: List[TradingPair]


class BaseToken(BaseModel):
    id: str
    name: str
    symbol: str
    price: float
    change_24h: Optional[float] = None
    volume_24h: Optional[float] = None
    market_cap: Optional[float] = None


class BaseTokenSnapshot(BaseModel):
    tokens: List[BaseToken]


class TokenVolumesSnapshot(BaseModel):
    chain_id: int
    volumes: dict[str, Optional[float]]

