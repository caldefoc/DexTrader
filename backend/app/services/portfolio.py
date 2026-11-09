import json
import os
from typing import List, Dict
from ..models.portfolio import TradeExecution

# Use absolute path relative to this file to ensure we always find trades.json
# This file is in backend/app/services/
# trades.json is in backend/
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_FILE = os.path.join(BASE_DIR, "trades.json")

EXECUTED_TRADES: List[TradeExecution] = []

def load_trades() -> List[TradeExecution]:
    global EXECUTED_TRADES
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
                EXECUTED_TRADES = [TradeExecution(**t) for t in data]
        except Exception as e:
            print(f"Error loading trades from {DATA_FILE}: {e}")
            EXECUTED_TRADES = []
    else:
        EXECUTED_TRADES = []
    return EXECUTED_TRADES

def save_trades(trades: List[TradeExecution]):
    global EXECUTED_TRADES
    EXECUTED_TRADES = trades
    try:
        with open(DATA_FILE, "w") as f:
            json.dump([t.dict() for t in trades], f, indent=2)
    except Exception as e:
        print(f"Error saving trades to {DATA_FILE}: {e}")

def add_trade(trade: TradeExecution):
    global EXECUTED_TRADES
    EXECUTED_TRADES.append(trade)
    save_trades(EXECUTED_TRADES)

def get_all_trades() -> List[TradeExecution]:
    return EXECUTED_TRADES

def reload_trades() -> List[TradeExecution]:
    """Reload trades from the JSON file (useful when file is updated externally)"""
    global EXECUTED_TRADES
    return load_trades()

def get_user_holdings() -> Dict[str, float]:
    """
    Calculate current token holdings based on trade history.
    Returns a dictionary of {SYMBOL: AMOUNT}.

    Uniform trade record standard (see models/portfolio.py):
      buy  -> gained BASE tokens: token_amount
      sell -> lost BASE tokens:   token_amount
      (legacy records where token == base stored the sold quantity in `amount`)
    """
    holdings = {}

    for t in EXECUTED_TRADES:
        try:
            base, quote = t.pair.split("/")
        except ValueError:
            continue # Skip invalid pairs

        is_new_format = (t.token == quote)

        if t.action == "buy":
            # Buying BASE using QUOTE -> gained BASE tokens
            holdings[base] = holdings.get(base, 0.0) + (t.token_amount or 0.0)

        elif t.action == "sell":
            # Selling BASE for QUOTE -> lost BASE tokens
            if is_new_format:
                holdings[base] = holdings.get(base, 0.0) - (t.token_amount or 0.0)
            else:
                # Legacy format: amount = token qty sold
                holdings[base] = holdings.get(base, 0.0) - (t.amount or 0.0)

    # Clean up small residuals or negatives (though negatives imply missing history)
    return {k: v for k, v in holdings.items() if v > 0}

# Initialize on module load
load_trades()
