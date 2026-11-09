import csv
import io
from typing import List
from ..models.portfolio import TradeExecution
from datetime import datetime

# Fallback USD rates.  Newer trades carry `price_usd` (captured at execution);
# the caller can also pass a live ETH price so old records are valued sanely.
USD_RATES = {"ETH": 3000.0, "WETH": 3000.0, "USDC": 1.0, "USDT": 1.0, "DAI": 1.0}

def generate_csv_report(trades: List[TradeExecution], eth_price: float = 3000.0) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        "Date", "Network", "Pair", "Action", "Price", 
        "Token Amount", "Network Fee", "Amount (USD)", "Status", "Tx Hash"
    ])
    
    rates = {**USD_RATES, "ETH": eth_price, "WETH": eth_price}
    for t in trades:
        dt = datetime.fromtimestamp(t.timestamp)
        
        # Prefer the USD price captured at execution, then fall back to the
        # quote-currency rate table.
        quote_qty = t.amount if t.amount else (
            (t.price or 0.0) * (t.token_amount or 0.0)
        )
        if t.price_usd and t.token_amount:
            amount_usd = (t.token_amount * t.price_usd) + (t.network_fee or 0.0)
        else:
            rate = rates.get(t.token, 1.0)
            amount_usd = (quote_qty * rate) + (t.network_fee or 0.0)
            
        writer.writerow([
            dt.strftime("%Y-%m-%d %H:%M:%S"),
            t.network,
            t.pair,
            t.action,
            t.price if t.price else "",
            t.token_amount if t.token_amount else "",
            t.network_fee if t.network_fee else "0.00",
            f"{amount_usd:.2f}",
            t.status,
            t.tx_hash
        ])
        
    return output.getvalue()
