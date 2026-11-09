"""Virtual portfolio for the public demo.

No wallet, no private key, no chain calls.  Proposals from the real strategy
pipeline are filled at their proposal price against a simulated starting cash
balance, and the result is persisted to ``demo_portfolio.json`` so the demo
keeps a plausible history across restarts.

This module is only used when ``DEMO_MODE=1``; the real ledger (``trades.json``)
is never touched by it.
"""

from __future__ import annotations

import time
import uuid
from typing import Dict, List, Optional

from .state_store import JsonStateStore
from .policy import STABLECOINS


STARTING_CASH = 1000.0
DUST = 1e-9


class DemoPortfolio:
    def __init__(self, store: Optional[JsonStateStore] = None):
        self.store = store or JsonStateStore(name="demo_portfolio.json")
        data = self.store.load() or {}
        self.cash = float(data.get("cash") if data.get("cash") is not None else STARTING_CASH)
        self.started_at = float(data.get("started_at") or time.time())
        self.positions: Dict[str, dict] = {}
        self.fills: List[dict] = list(data.get("fills") or [])[-1000:]

        for symbol, row in (data.get("positions") or {}).items():
            try:
                if isinstance(row, dict):
                    quantity = float(row.get("qty") or 0.0)
                    average = float(row.get("avg_entry") or 0.0)
                else:  # tolerate a bare quantity from an older shape
                    quantity, average = float(row or 0.0), 0.0
            except (TypeError, ValueError):
                continue
            symbol = symbol.upper()
            if symbol in STABLECOINS:
                # Stablecoins are cash.  Fold any legacy entry back into it so
                # the book never reports the same dollars twice.
                self.cash += quantity
                continue
            if quantity > DUST:
                self.positions[symbol] = {"qty": quantity, "avg_entry": average}

    # ------------------------------------------------------------------ reads
    def holdings(self) -> Dict[str, float]:
        """Shape the agent loop expects: symbol -> quantity."""
        result = {
            symbol: round(position["qty"], 8)
            for symbol, position in self.positions.items()
            if position["qty"] > DUST and symbol not in STABLECOINS
        }
        if self.cash > 0.01:
            result["USDC"] = round(self.cash, 2)
        return result

    def equity(self, prices: Dict[str, float]) -> float:
        total = self.cash
        for symbol, position in self.positions.items():
            price = float(prices.get(symbol.upper()) or position.get("avg_entry") or 0.0)
            total += position["qty"] * price
        return total

    def summary(self, prices: Optional[Dict[str, float]] = None) -> dict:
        prices = prices or {}
        rows = []
        invested = 0.0
        for symbol, position in sorted(self.positions.items()):
            price = float(prices.get(symbol.upper()) or position.get("avg_entry") or 0.0)
            value = position["qty"] * price
            cost = position["qty"] * position.get("avg_entry", 0.0)
            invested += value
            rows.append({
                "token": symbol,
                "quantity": round(position["qty"], 8),
                "avg_entry": round(position.get("avg_entry", 0.0), 8),
                "price": round(price, 8),
                "value_usd": round(value, 2),
                "unrealized_usd": round(value - cost, 2),
            })
        equity = self.cash + invested
        return {
            "cash": round(self.cash, 2),
            "positions": rows,
            "equity": round(equity, 2),
            "starting_cash": STARTING_CASH,
            "pnl_usd": round(equity - STARTING_CASH, 2),
            "pnl_pct": round((equity - STARTING_CASH) / STARTING_CASH * 100, 2),
            "fills": len(self.fills),
            "started_at": self.started_at,
        }

    def recent_fills(self, limit: int = 200) -> List[dict]:
        return self.fills[-limit:]

    # ----------------------------------------------------------------- writes
    def apply_fill(self, proposal) -> Optional[dict]:
        """Fill a proposal at its price.  Returns the fill, or ``None``."""
        price = float(getattr(proposal, "price", 0.0) or 0.0)
        quantity = float(getattr(proposal, "amount", 0.0) or 0.0)
        action = str(getattr(proposal, "action", "")).lower()
        token = str(getattr(proposal, "token", "")).upper()
        if price <= 0 or quantity <= 0 or not token or action not in ("buy", "sell"):
            return None
        if token in STABLECOINS:
            # Cash is not a tradable position: buying or "stopping out" of it
            # would corrupt the book.
            return None

        if action == "buy":
            cost = quantity * price
            if cost > self.cash:
                quantity = self.cash / price
                cost = quantity * price
            if quantity <= DUST:
                return None
            position = self.positions.setdefault(token, {"qty": 0.0, "avg_entry": 0.0})
            total_quantity = position["qty"] + quantity
            if total_quantity > 0:
                position["avg_entry"] = (
                    position["qty"] * position["avg_entry"] + cost
                ) / total_quantity
            position["qty"] = total_quantity
            self.cash -= cost
            value = cost
        else:
            position = self.positions.get(token)
            if not position or position["qty"] <= DUST:
                return None
            quantity = min(quantity, position["qty"])
            value = quantity * price
            position["qty"] -= quantity
            self.cash += value
            if position["qty"] <= DUST:
                del self.positions[token]

        fill = {
            "tx_hash": f"demo-{uuid.uuid4().hex[:16]}",
            "timestamp": int(time.time()),
            "token": token,
            "action": action,
            "quantity": round(quantity, 8),
            "price": price,
            "value_usd": round(value, 2),
            "cash_after": round(self.cash, 2),
        }
        self.fills.append(fill)
        self.fills = self.fills[-1000:]
        self.persist()
        return fill

    def reset(self) -> dict:
        self.cash = STARTING_CASH
        self.positions = {}
        self.fills = []
        self.started_at = time.time()
        self.persist()
        return self.summary()

    # ------------------------------------------------------------ persistence
    def persist(self) -> bool:
        return self.store.save({
            "cash": self.cash,
            "positions": self.positions,
            "fills": self.fills[-1000:],
            "started_at": self.started_at,
        })
