The module is a FastAPI application rooted at `app/main.py`, which mounts five routers under `/market`, `/portfolio`, `/agents`, `/signals`, `/news` and pre-populates market/news caches on startup via `asyncio.create_task`. Internal layering follows a clear request → controller pattern:
- `app/api/*_routes.py` — thin FastAPI route handlers that parse Pydantic models and delegate to services or the global `ControllerAgent`.
- `app/agents/controller.py` — the single-process orchestrator (`controller = ControllerAgent()`) running an async polling loop that calls Analysis/Risk/Execution/Audit agents, persists state to `agent_state.json`, and exposes lifecycle methods (`start`, `stop`, `halt`, `resume`).
- `app/agents/{analysis,risk,execution,audit,polling}_agent.py` — specialized agent classes composing LangChain/OpenAI calls and signal logic.
- `app/services/*` — domain services (CoinGecko/CoinMarketCap/DexScreener/Gas price feeds, portfolio persistence, indicators, guardrails, strategy, demo portfolio).
- `app/models/*` — shared Pydantic schemas for market data, agents, portfolios and signals.
- `app/core/config.py` — env-driven configuration loaded via `python-dotenv`.

Dependency direction is strictly inward: routes depend on agents/controllers; controllers depend on services and models; services are leaf modules. State is persisted as JSON files (`trades.json`, `agent_state.json`, nonce/cache files) rather than a database, with a `JsonStateStore` abstraction. A `DEMO_MODE` flag swaps real wallet/portfolio behavior for a simulated `DemoPortfolio`.