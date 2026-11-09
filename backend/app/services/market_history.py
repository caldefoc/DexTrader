"""Rolling per-token price/volume history used by the strategy layer.

The agent loop samples the market snapshot every cycle.  Those samples are the
only inputs we need for RSI, VWAP and the 5-minute volume-spike filter, so no
extra upstream API calls are made.  History is persisted across restarts to
``backend/price_history.json`` (gitignored).

Warm-up is honest: indicators that need more data than we have return ``None``
and the analysis layer lowers confidence or skips the signal rather than
pretending the market is neutral.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Deque, Dict, Iterable, List, Optional, Tuple
from collections import deque

from ..models.market import MarketSnapshot
from . import indicators
from .state_store import JsonStateStore


MAX_AGE_SECONDS = 2 * 24 * 60 * 60
MIN_SAMPLE_INTERVAL = 55.0
MAX_SAMPLES_PER_TOKEN = 3000


@dataclass(frozen=True)
class Sample:
    timestamp: float
    price: float
    volume_24h: Optional[float]


class MarketHistory:
    def __init__(self, store: Optional[JsonStateStore] = None):
        self.store = store or JsonStateStore(name="price_history.json")
        self._samples: Dict[str, Deque[Sample]] = {}
        self._last_saved = 0.0
        self._dirty = False
        self.load()

    # ------------------------------------------------------------------ I/O
    def load(self) -> None:
        data = self.store.load()
        cutoff = time.time() - MAX_AGE_SECONDS
        for symbol, rows in (data.get("samples") or {}).items():
            queue: Deque[Sample] = deque(maxlen=MAX_SAMPLES_PER_TOKEN)
            try:
                for row in rows:
                    timestamp, price, volume = float(row[0]), float(row[1]), row[2]
                    if timestamp < cutoff or price <= 0:
                        continue
                    queue.append(Sample(timestamp, price, None if volume is None else float(volume)))
            except (TypeError, ValueError, IndexError):
                continue
            if queue:
                self._samples[symbol.upper()] = queue

    def persist(self, force: bool = False) -> None:
        now = time.time()
        if not self._dirty and not force:
            return
        if not force and now - self._last_saved < 120:
            return
        self._prune(now)
        payload = {
            "samples": {
                symbol: [[s.timestamp, s.price, s.volume_24h] for s in queue]
                for symbol, queue in self._samples.items()
            }
        }
        if self.store.save(payload):
            self._dirty = False
            self._last_saved = now

    def _prune(self, now: float) -> None:
        cutoff = now - MAX_AGE_SECONDS
        for symbol in list(self._samples):
            queue = self._samples[symbol]
            while queue and queue[0].timestamp < cutoff:
                queue.popleft()
            if not queue:
                del self._samples[symbol]

    # --------------------------------------------------------------- record
    def record_pair(
        self,
        symbol: str,
        price: float,
        volume_24h: Optional[float] = None,
        now: Optional[float] = None,
    ) -> bool:
        if not symbol or price is None or price <= 0:
            return False
        now = now if now is not None else time.time()
        symbol = symbol.upper()
        queue = self._samples.setdefault(symbol, deque(maxlen=MAX_SAMPLES_PER_TOKEN))
        if queue and now - queue[-1].timestamp < MIN_SAMPLE_INTERVAL:
            return False
        queue.append(Sample(now, float(price), None if volume_24h is None else float(volume_24h)))
        self._dirty = True
        return True

    def record(self, snapshot: MarketSnapshot, now: Optional[float] = None) -> int:
        now = now if now is not None else (getattr(snapshot, "timestamp", None) or time.time())
        added = 0
        for pair in snapshot.pairs:
            if self.record_pair(pair.base_symbol, pair.price, pair.volume_24h, now):
                added += 1
        self.persist()
        return added

    # ---------------------------------------------------------------- query
    def samples(self, symbol: str, window_seconds: float = MAX_AGE_SECONDS) -> List[Sample]:
        queue = self._samples.get(symbol.upper())
        if not queue:
            return []
        cutoff = (queue[-1].timestamp if queue else time.time()) - window_seconds
        return [sample for sample in queue if sample.timestamp >= cutoff]

    def prices(self, symbol: str, window_seconds: float = 86400) -> List[float]:
        return [sample.price for sample in self.samples(symbol, window_seconds)]

    def closes(self, symbol: str, limit: int = 60) -> List[float]:
        return self.prices(symbol, MAX_AGE_SECONDS)[-limit:]

    def _volume_deltas(self, samples: Iterable[Sample]) -> List[Tuple[float, float]]:
        """Return ``(timestamp, volume traded since previous sample)``."""
        deltas: List[Tuple[float, float]] = []
        previous: Optional[Sample] = None
        for sample in samples:
            if previous is not None and sample.volume_24h is not None and previous.volume_24h is not None:
                deltas.append((sample.timestamp, max(0.0, sample.volume_24h - previous.volume_24h)))
            previous = sample
        return deltas

    def vwap(self, symbol: str, window_seconds: float = 86400) -> Optional[float]:
        samples = self.samples(symbol, window_seconds)
        if len(samples) < 2:
            return None
        deltas = self._volume_deltas(samples)
        price_by_timestamp = {sample.timestamp: sample.price for sample in samples}
        prices = [price_by_timestamp[timestamp] for timestamp, _ in deltas]
        volumes = [volume for _, volume in deltas]
        return indicators.vwap(prices, volumes)

    def volume_ratio(
        self,
        symbol: str,
        short_seconds: float = 300,
        baseline_seconds: float = 3600,
    ) -> Optional[float]:
        samples = self.samples(symbol, baseline_seconds + short_seconds)
        if len(samples) < 4:
            return None
        span = samples[-1].timestamp - samples[0].timestamp
        if span < max(600.0, short_seconds * 2):
            return None
        now = samples[-1].timestamp
        deltas = self._volume_deltas(samples)
        short_volume = sum(volume for ts, volume in deltas if ts >= now - short_seconds)
        baseline_volume = sum(volume for ts, volume in deltas if ts >= now - baseline_seconds)
        return indicators.volume_ratio(short_volume, baseline_volume, baseline_seconds / short_seconds)

    def summary(self, symbol: str, now: Optional[float] = None, period: int = 14) -> dict:
        """Snapshot of every indicator the analysis layer uses.

        ``rsi``/``vwap``/``volume_ratio`` are ``None`` during warm-up.
        """
        closes = self.closes(symbol, limit=max(period + 1, 40))
        rsi_value = indicators.rsi(closes, period=period)
        vwap_value = self.vwap(symbol, 86400)
        ratio = self.volume_ratio(symbol)
        samples = self.samples(symbol, 86400)
        return {
            "rsi": None if rsi_value is None else round(rsi_value, 2),
            "vwap": vwap_value,
            "volume_ratio": None if ratio is None else round(ratio, 2),
            "volume_spike": indicators.is_volume_spike(ratio),
            "sample_count": len(samples),
            "history_minutes": round((samples[-1].timestamp - samples[0].timestamp) / 60, 1) if len(samples) > 1 else 0.0,
            "rsi_ready": rsi_value is not None,
            "vwap_ready": vwap_value is not None,
            "volume_ready": ratio is not None,
        }
