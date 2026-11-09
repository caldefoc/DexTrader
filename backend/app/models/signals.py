from pydantic import BaseModel
from typing import Literal, Optional


SignalType = Literal["buy", "sell", "hold"]
SignalSource = Literal["llm", "rules", "deepseek"]


class Signal(BaseModel):
    pair: str
    action: SignalType
    confidence: float
    explanation: Optional[str] = None
    source: Optional[SignalSource] = None
    created_at: Optional[float] = None
