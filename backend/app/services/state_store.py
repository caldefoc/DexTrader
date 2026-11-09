"""Small atomic JSON state store used for agents, guardrails and price history."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from typing import Any, Dict, Optional


DEFAULT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def state_path(name: str) -> str:
    """Return ``backend/<name>`` unless ``DEXTRADER_STATE_DIR`` overrides it."""
    directory = os.getenv("DEXTRADER_STATE_DIR", DEFAULT_DIR)
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, name)


class JsonStateStore:
    def __init__(self, path: Optional[str] = None, name: str = "agent_state.json"):
        self.path = path or state_path(name)
        self._lock = threading.RLock()

    def load(self) -> Dict[str, Any]:
        with self._lock:
            if not os.path.exists(self.path):
                return {}
            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                return data if isinstance(data, dict) else {}
            except (OSError, ValueError) as exc:
                print(f"[StateStore] Could not read {self.path}: {exc}")
                return {}

    def save(self, data: Dict[str, Any]) -> bool:
        """Atomically replace the state file.  Never raises on I/O failure."""
        with self._lock:
            directory = os.path.dirname(self.path)
            os.makedirs(directory, exist_ok=True)
            temporary = None
            try:
                fd, temporary = tempfile.mkstemp(dir=directory, prefix=".state-", suffix=".tmp")
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(data, handle, indent=2, default=str)
                os.replace(temporary, self.path)
                return True
            except OSError as exc:
                print(f"[StateStore] Could not save {self.path}: {exc}")
                try:
                    if temporary and os.path.exists(temporary):
                        os.unlink(temporary)
                except OSError:
                    pass
                return False
