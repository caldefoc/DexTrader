import logging
import time
import os
from typing import Optional
from ..models.agents import AuditLog

# Determine log file path dynamically
# Get the directory of the current file (backend/app/agents)
current_dir = os.path.dirname(os.path.abspath(__file__))
# Go up two levels to get to backend root (backend/)
backend_root = os.path.dirname(os.path.dirname(current_dir))
log_file_path = os.path.join(backend_root, "agents.log")

# Configure standard logging
logging.basicConfig(
    filename=log_file_path,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

class AuditAgent:
    def __init__(self):
        self.name = "AuditAgent"
        self.logs = []

    def log(self, agent_name: str, message: str, level: str = "INFO", data: Optional[dict] = None):
        """
        Log an event to file and memory.
        """
        log_entry = AuditLog(
            timestamp=time.time(),
            agent=agent_name,
            message=message,
            level=level,
            data=data
        )
        self.logs.append(log_entry)
        
        # Also write to standard logger
        log_msg = f"[{agent_name}] {message}"
        if data:
            log_msg += f" | Data: {data}"
            
        if level == "ERROR":
            logging.error(log_msg)
        elif level == "WARNING":
            logging.warning(log_msg)
        else:
            logging.info(log_msg)
            
        return log_entry

    def get_logs(self, limit: int = 100):
        return sorted(self.logs, key=lambda x: x.timestamp, reverse=True)[:limit]
