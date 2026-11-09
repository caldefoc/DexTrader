from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from decimal import Decimal

class PollingConfig(BaseModel):
    interval_seconds: int = 60
    monitored_tokens: Optional[List[str]] = None
    user_holdings: Optional[dict] = None # symbol -> amount
    agent_cache_duration: Optional[int] = 300  # seconds

class AgentStatus(BaseModel):
    running: bool
    current_step: Optional[str] = None
    last_run: Optional[float] = None
    monitored_tokens: Optional[List[str]] = None
    user_holdings: Optional[dict] = None
    halted: bool = False
    halt_reason: Optional[str] = None
    equity: Optional[float] = None
    day_start_equity: Optional[float] = None
    drawdown_pct: Optional[float] = None
    trades_today: int = 0
    max_daily_trades: int = 20

class AnalysisRecommendation(BaseModel):
    token: str
    action: Literal["buy", "sell", "hold"]
    confidence: float
    reason: str
    price: float
    pct_change: Optional[float] = None
    rsi: Optional[float] = None
    vwap: Optional[float] = None
    volume_spike: bool = False
    volume_ratio: Optional[float] = None
    buy_step: int = 0
    sell_fraction: float = 0.0
    gain_pct: Optional[float] = None
    exit_kind: Optional[str] = None  # take_profit | stop_loss | trailing_stop
    indicators_ready: bool = False

class RiskAssessment(BaseModel):
    approved: bool
    reason: str
    adjusted_amount: Optional[float] = None
    max_slippage: float = 0.5
    estimated_gas: float = 0.0
    gas_gwei: Optional[float] = None
    estimated_gas_usd: float = 0.0
    expected_profit_usd: float = 0.0
    max_notional_usd: Optional[float] = None
    checks: List[dict] = Field(default_factory=list)

class TradeProposal(BaseModel):
    id: str
    token: str
    action: Literal["buy", "sell"]
    amount: float
    price: float
    pct_change: Optional[float] = None
    reason: Optional[str] = None
    slippage: float
    gas_limit: int
    status: Literal["pending", "approved", "rejected", "executed"] = "pending"
    timestamp: float
    notional_usd: float = 0.0
    expected_profit_usd: float = 0.0
    gas_cost_usd: float = 0.0
    auto_tradeable: bool = False
    price_source: str = "global_spot"
    sell_fraction: Optional[float] = None
    exit_kind: Optional[str] = None

class AuditLog(BaseModel):
    timestamp: float
    agent: str
    message: str
    level: Literal["INFO", "WARNING", "ERROR"] = "INFO"
    data: Optional[dict] = None

