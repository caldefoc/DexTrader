import logging
import os
import time
from collections import deque
from logging.handlers import RotatingFileHandler
from typing import Optional

from ..models.agents import AuditLog


# backend/app/agents -> backend/
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_root = os.path.dirname(os.path.dirname(current_dir))
log_file_path = os.path.join(backend_root, "agents.log")

logger = logging.getLogger("dextrader.audit")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    try:
        handler = RotatingFileHandler(
            log_file_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(handler)
    except OSError as exc:  # read-only volume, tests, etc.
        print(f"[AuditAgent] File logging disabled: {exc}")


class AuditAgent:
    def __init__(self):
        self.name = "AuditAgent"
        # Keep the live view bounded; the rotating file is the durable record.
        self.logs = deque(maxlen=1000)

    def log(self, agent_name: str, message: str, level: str = "INFO", data: Optional[dict] = None):
        log_entry = AuditLog(
            timestamp=time.time(),
            agent=agent_name,
            message=message,
            level=level,
            data=data,
        )
        self.logs.append(log_entry)

        log_msg = f"[{agent_name}] {message}"
        if data:
            log_msg += f" | Data: {data}"

        if level == "ERROR":
            logger.error(log_msg)
        elif level == "WARNING":
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

        return log_entry

    def get_logs(self, limit: int = 100):
        return sorted(self.logs, key=lambda entry: entry.timestamp, reverse=True)[:limit]
