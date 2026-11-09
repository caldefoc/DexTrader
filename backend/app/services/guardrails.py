"""Portfolio-level circuit breakers.

These guardrails are deliberately independent of the strategy: the analysis
layer can want a trade, the risk layer can approve it, and this module can
still refuse it because the day's loss limit, trade budget or kill switch says
stop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class GuardrailConfig:
    max_daily_trades: int = 20
    max_trades_per_token: int = 6
    max_daily_drawdown: float = 0.05
    max_position_pct: float = 0.10
    min_profit_usd: float = 0.10
    max_gas_gwei: float = 50.0
    gas_limit: int = 250_000


@dataclass
class Guardrails:
    config: GuardrailConfig = field(default_factory=GuardrailConfig)
    day: str = ""
    day_start_equity: Optional[float] = None
    last_equity: Optional[float] = None
    peak_equity: Optional[float] = None
    trades_today: int = 0
    trades_by_token: Dict[str, int] = field(default_factory=dict)
    halted: bool = False
    halt_reason: Optional[str] = None
    halt_kind: Optional[str] = None  # "manual" | "daily_drawdown"

    # ------------------------------------------------------------- lifecycle
    @staticmethod
    def _day_key(now: Optional[float] = None) -> str:
        moment = datetime.fromtimestamp(now, tz=timezone.utc) if now else datetime.now(timezone.utc)
        return moment.strftime("%Y-%m-%d")

    def begin_cycle(self, equity: Optional[float], now: Optional[float] = None) -> dict:
        """Roll the trading day, update the drawdown breaker, return status."""
        today = self._day_key(now)
        if today != self.day:
            self.day = today
            self.trades_today = 0
            self.trades_by_token = {}
            self.day_start_equity = equity if equity and equity > 0 else None
            if self.halted and self.halt_kind == "daily_drawdown":
                self.halted = False
                self.halt_reason = None
                self.halt_kind = None

        if equity is not None and equity > 0:
            if self.day_start_equity is None:
                self.day_start_equity = equity
            self.last_equity = equity
            self.peak_equity = max(self.peak_equity or equity, equity)
            drawdown = self.drawdown_pct(equity)
            if drawdown is not None and drawdown <= -self.config.max_daily_drawdown and not self.halted:
                self.halt(
                    f"Daily drawdown {drawdown * 100:.2f}% breached "
                    f"{self.config.max_daily_drawdown * 100:.1f}% limit",
                    kind="daily_drawdown",
                )
        return self.status(equity)

    def drawdown_pct(self, equity: Optional[float] = None) -> Optional[float]:
        if equity is None:
            equity = self.last_equity
        if equity is None or not self.day_start_equity:
            return None
        return (equity - self.day_start_equity) / self.day_start_equity

    # --------------------------------------------------------------- control
    def halt(self, reason: str, kind: str = "manual") -> None:
        self.halted = True
        self.halt_reason = reason
        self.halt_kind = kind

    def resume(self) -> None:
        self.halted = False
        self.halt_reason = None
        self.halt_kind = None

    # ------------------------------------------------------------- allowances
    def can_trade(self, token: str) -> Tuple[bool, Optional[str]]:
        if self.halted:
            return False, f"Trading halted: {self.halt_reason or 'kill switch engaged'}"
        if self.trades_today >= self.config.max_daily_trades:
            return False, (
                f"Daily trade limit reached "
                f"({self.trades_today}/{self.config.max_daily_trades})"
            )
        token = token.upper()
        count = self.trades_by_token.get(token, 0)
        if count >= self.config.max_trades_per_token:
            return False, (
                f"{token} per-token trade limit reached "
                f"({count}/{self.config.max_trades_per_token})"
            )
        return True, None

    def record_trade(self, token: str) -> None:
        token = token.upper()
        self.trades_today += 1
        self.trades_by_token[token] = self.trades_by_token.get(token, 0) + 1

    # -------------------------------------------------------------- reporting
    def status(self, equity: Optional[float] = None) -> dict:
        if equity is None:
            equity = self.last_equity
        return {
            "halted": self.halted,
            "halt_reason": self.halt_reason,
            "halt_kind": self.halt_kind,
            "day": self.day,
            "equity": equity,
            "day_start_equity": self.day_start_equity,
            "drawdown_pct": self.drawdown_pct(equity),
            "trades_today": self.trades_today,
            "max_daily_trades": self.config.max_daily_trades,
            "max_trades_per_token": self.config.max_trades_per_token,
            "max_daily_drawdown": self.config.max_daily_drawdown,
            "max_position_pct": self.config.max_position_pct,
            "min_profit_usd": self.config.min_profit_usd,
            "max_gas_gwei": self.config.max_gas_gwei,
        }

    # ------------------------------------------------------------ persistence
    def to_dict(self) -> dict:
        return {
            "day": self.day,
            "day_start_equity": self.day_start_equity,
            "last_equity": self.last_equity,
            "peak_equity": self.peak_equity,
            "trades_today": self.trades_today,
            "trades_by_token": self.trades_by_token,
            "halted": self.halted,
            "halt_reason": self.halt_reason,
            "halt_kind": self.halt_kind,
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "Guardrails":
        rails = cls()
        if not isinstance(data, dict):
            return rails
        for name in (
            "day", "day_start_equity", "last_equity", "peak_equity", "halted",
            "halt_reason", "halt_kind",
        ):
            if name in data and data[name] is not None:
                setattr(rails, name, data[name])
        rails.trades_today = int(data.get("trades_today") or 0)
        rails.trades_by_token = {
            str(k).upper(): int(v) for k, v in (data.get("trades_by_token") or {}).items()
        }
        return rails
