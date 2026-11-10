---
kind: logging_system
name: Logging System — Python stdlib logging with per-agent file sinks
category: logging_system
scope:
    - '**'
source_files:
    - backend/app/agents/audit_agent.py
    - backend/app/models/agents.py
    - backend/app/main.py
---

## What system/approach is used

The repository uses the **Python standard library `logging` module** only. There is no third-party logging framework (no structlog, loguru, python-json-logger, etc.) and no centralized logging configuration file. Uvicorn's default access/error logging is left to its own defaults; FastAPI itself is not configured with a custom `log_config`. The only explicit logger setup in the codebase lives in `backend/app/agents/audit_agent.py`, which creates a dedicated logger named `dextrader.audit`.

## Key files and packages

- `backend/app/agents/audit_agent.py` — the sole place that configures a `logging.Logger` instance. It also defines the `AuditAgent` class whose `log()` method is the structured entry point for agent audit events.
- `backend/agents.log` — the active rotating file sink where `dextrader.audit` writes.
- `backend/uvicorn.log`, `backend/uvicorn.err` — produced by the Uvicorn process but not configured by application code.
- `backend/app/main.py` — FastAPI app bootstrap; it does not install any logging handlers or configure log levels.

## Architecture and conventions

1. **Per-component logger names**: The audit agent uses the hierarchical name `dextrader.audit`. This follows the conventional dotted-namespace pattern (`package.module`) so that loggers can be filtered later if a central config were introduced.
2. **Rotating file sink**: A single `RotatingFileHandler` writes to `backend/agents.log` with `maxBytes=5 MiB` and `backupCount=3`, producing up to four rotated files (`agents.log`, `agents.log.1`, …). The formatter is plain text: `"%(asctime)s [%(levelname)s] %(message)s"`.
3. **Durable + in-memory dual output**: `AuditAgent` keeps an in-memory `collections.deque(maxlen=1000)` of `AuditLog` model objects (defined in `backend/app/models/agents.py`) alongside the file sink. The comment states the intent: "Keep the live view bounded; the rotating file is the durable record." `get_logs(limit=100)` serves the recent entries back through the API.
4. **Structured fields via a model object**: Each audit event is wrapped in an `AuditLog(timestamp, agent, message, level, data)` before being appended to the deque and persisted. The `data` field is optional and serialized as-is into the log message string.
5. **Graceful fallback on read-only filesystems**: If opening `agents.log` fails (e.g. inside a container with a read-only volume or during tests), the OSError is caught and the handler is silently skipped, printing `[AuditAgent] File logging disabled: <exc>` to stdout instead of crashing.
6. **Level mapping**: `AuditAgent.log()` accepts a string level (`INFO`, `WARNING`, `ERROR`) and maps it to the corresponding `logger.info/warning/error` call; anything else falls through to `logger.info`.
7. **No global logging configuration**: Neither `main.py` nor any other module calls `logging.config.dictConfig`, `basicConfig`, or `uvicorn.config`. Consequently, Uvicorn's default console logging remains active, while the audit agent's file sink is independent.
8. **Frontend has no server-side logging concern**: The Next.js frontend does not define a backend logging strategy; client-side logs are not part of this category.

## Conventions and constraints

- **Convention observed**: Agent components should use the `AuditAgent.log(agent_name, message, level="INFO", data=None)` helper rather than calling the raw logger directly, so that every audit event is simultaneously recorded in the in-memory deque and the rotating file.
- **Constraint enforced by code**: The file handler is attached only once (`if not logger.handlers:`), preventing duplicate handlers on repeated imports.
- **Constraint enforced by code**: The in-memory log buffer is hard-capped at 1000 entries via `deque(maxlen=1000)`, ensuring bounded memory usage even under heavy audit traffic.
- **Constraint enforced by code**: The rotating file is limited to 5 MB per file with 3 backups, capping disk usage at roughly 20 MB for audit logs.
- **Constraint enforced by code**: Log level strings are restricted to the three branches handled in `AuditAgent.log`; unrecognized values are treated as `INFO`.
- **Not present**: No structured JSON log format, no correlation/request IDs, no centralized log-level configuration, no syslog/HTTP/file sink abstraction beyond the audit agent's own implementation.