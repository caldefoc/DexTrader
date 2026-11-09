from pydantic import BaseModel
from typing import List


class WalletPosition(BaseModel):
    token_symbol: str
    balance: float
    value_usd: float
    pnl_24h: float


class PortfolioSnapshot(BaseModel):
    address: str
    positions: List[WalletPosition]


class TradeExecution(BaseModel):
    # Uniform trade record standard (all producers and consumers must follow this):
    #   amount       = quantity of the pair's QUOTE currency (spent on buy, received on sell)
    #   token_amount = quantity of the pair's BASE token (received on buy, sold on sell)
    #   token        = the quote currency symbol (names the currency of `amount`)
    #   price        = quote per base (unit price of the token in the quote currency)
    #   network_fee  = gas fee in USD
    tx_hash: str
    network: str
    pair: str
    action: str
    amount: float
    token: str
    price: float = 0.0
    token_amount: float = 0.0  # Quantity of the pair's base token (bought/sold)
    network_fee: float = 0.0   # Gas fee in USD
    price_usd: float = 0.0     # USD per base token at execution (for reporting)
    status: str = "completed"  # completed, failed, pending
    timestamp: int

