import csv
import io
from typing import List
from ..models.portfolio import TradeExecution
from datetime import datetime

# Approximate USD rates for quote currencies (matches the frontend Reports page)
USD_RATES = {"ETH": 3000.0, "WETH": 3000.0, "USDC": 1.0, "USDT": 1.0, "DAI": 1.0}

def generate_csv_report(trades: List[TradeExecution]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        "Date", "Network", "Pair", "Action", "Price", 
        "Token Amount", "Network Fee", "Amount (USD)", "Status", "Tx Hash"
    ])
    
    for t in trades:
        dt = datetime.fromtimestamp(t.timestamp)
        
        # Uniform trade record standard: t.amount is always the quantity of the
        # pair's quote currency and t.token names that currency. Convert the
        # quote quantity to USD; fall back to price * token_amount (= quote qty).
        quote_qty = t.amount if t.amount else (
            (t.price or 0.0) * (t.token_amount or 0.0)
        )
        rate = USD_RATES.get(t.token, 1.0)
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
