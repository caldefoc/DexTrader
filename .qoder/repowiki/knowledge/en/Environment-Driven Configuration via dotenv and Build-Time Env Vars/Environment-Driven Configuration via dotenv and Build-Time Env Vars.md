---
kind: configuration_system
name: Environment-Driven Configuration via dotenv and Build-Time Env Vars
category: configuration_system
scope:
    - '**'
source_files:
    - backend/app/core/config.py
    - .env.example
    - frontend/constants/config.ts
    - frontend/.env.local
    - docker-compose.yml
    - backend/app/main.py
---

## Approach

DexTrader uses a minimal, environment-variable-driven configuration system with no dedicated config library (Pydantic Settings, dynaconf, etc.).

- **Backend**: `backend/app/core/config.py` loads `.env` via `python-dotenv` (`load_dotenv(find_dotenv())`) at import time and exposes module-level constants read from `os.getenv`. Consumers import these names directly.
- **Frontend**: `frontend/constants/config.ts` reads Next.js build-time env vars (`NEXT_PUBLIC_BACKEND_URL`, `NEXT_PUBLIC_DEMO_MODE`) and re-exports them as plain constants consumed by pages/components.
- **Deployment**: `docker-compose.yml` injects runtime variables through `env_file: .env` plus explicit `environment:` overrides, and passes frontend build args (`NEXT_PUBLIC_BACKEND_URL`, `NEXT_PUBLIC_DEMO_MODE`) into the Docker build for the Next.js image.

There is no YAML/TOML/JSON config file format in use; all application settings are supplied as environment variables.

## Key Files

- `backend/app/core/config.py` — single source of truth for backend env vars.
- `frontend/constants/config.ts` — single source of truth for frontend env vars.
- `.env.example` — documented template of every supported variable.
- `frontend/.env.local` — local dev override (ignored by git).
- `docker-compose.yml` — production-ish stack wiring `.env` + env overrides + volume mount for state dir.
- `backend/app/main.py` — parses `CORS_ORIGINS` for FastAPI middleware.

## Architecture & Conventions

1. **Single loader module.** All backend configuration is centralized in `app.core.config`. Services and routes import from there rather than calling `os.getenv` themselves (e.g. `coingecko.py`, `coinmarketcap.py`, `routes_signals.py`, `controller.py`).
2. **Boolean flags are normalized manually.** `DEMO_MODE` is parsed as `os.getenv("DEMO_MODE", "0").strip().lower() in ("1", "true", "yes", "on")`; default is falsy.
3. **Secrets are optional per service.** Market data keys (`COINMARKETCAP_API_KEY`, `COINGECKO_API_KEY`) and LLM keys (`OPENAI_API_KEY`, `DEEPSEEK_API_KEY`) are loaded as raw strings; each consumer checks truthiness before using them:
   - Signal generation tries DeepSeek first, then OpenAI, then falls back to a deterministic rule when neither key is set (`backend/app/api/routes_signals.py`).
   - CoinGecko/CoinMarketCap services attach the API key only when present.
4. **Frontend env vars are build-time only.** `NEXT_PUBLIC_*` variables are baked into the Next.js bundle at build time; they cannot be changed at runtime without rebuilding the image.
5. **Demo mode is a cross-cutting feature flag.** `DEMO_MODE=1` switches the backend to a simulated portfolio (`demo_portfolio.py`) and hides wallet/trade execution paths; `NEXT_PUBLIC_DEMO_MODE=1` hides wallet UI on the frontend. The compose file sets both to `1` for the public demo.
6. **State directory is externalized.** `DEXTRADER_STATE_DIR` defaults to the working directory but can be overridden (via compose) so that `agent_state.json`, `trades.json`, `base_address_cache.json`, etc. persist on a named volume (`/data`).
7. **CORS origins are comma-separated env var.** `CORS_ORIGINS` is parsed in `backend/app/main.py` and passed to FastAPI's `CORSMiddleware`; the comment documents `CORS_ORIGINS="*"` as the deliberate pattern for exposing the API publicly.

## Conventions & Constraints

- Every new setting should be added to `.env.example` with a comment describing its purpose and default behavior — this is the authoritative documentation for available variables.
- Backend consumers must import from `app.core.config`, not call `os.getenv` directly, to keep loading order predictable (dotenv is loaded once at import time).
- Boolean flags should follow the same normalization pattern as `DEMO_MODE` (accepting `1`, `true`, `yes`, `on` as truthy) if they need to be toggled via compose or shell.
- Frontend-only configuration belongs in `frontend/constants/config.ts` and uses the `NEXT_PUBLIC_` prefix so Next.js includes it in the client bundle.
- Secrets (API keys) are never committed; `.env` is git-ignored and `.env.example` contains empty placeholders.
- There is no schema validation, type checking, or default-value registry beyond the Python `os.getenv(..., default)` calls — adding a new variable requires editing three places: `config.py`, `.env.example`, and any consumer.