from typing import List

from .polling_agent import poll_once
from .logic_agent import generate_signals
from .trading_agent import execute_signals
from ..models.signals import Signal


async def run_cycle() -> List[Signal]:
  snapshot = await poll_once()
  signals = await generate_signals(snapshot)
  executed = await execute_signals(signals)
  return executed

