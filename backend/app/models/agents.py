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

class RiskAssessment(BaseModel):
    approved: bool
    reason: str
    adjusted_amount: Optional[float] = None
    max_slippage: float = 0.5
    estimated_gas: float = 0.0

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

class AuditLog(BaseModel):
    timestamp: float
    agent: str
    message: str
    level: Literal["INFO", "WARNING", "ERROR"] = "INFO"
    data: Optional[dict] = None

