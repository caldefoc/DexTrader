---
kind: error_handling
name: 'Error Handling: HTTPException-driven FastAPI with Localized try/catch and No Custom Error Types'
category: error_handling
scope:
    - '**'
source_files:
    - backend/app/main.py
    - backend/app/api/routes_agents.py
    - backend/app/api/routes_market.py
    - backend/app/api/routes_portfolio.py
    - backend/app/agents/controller.py
    - backend/app/agents/polling_agent.py
    - frontend/context/MarketDataContext.tsx
    - frontend/components/AgentsControlPanel.tsx
---

## Overview

DexTrader has no centralized error taxonomy, custom exception hierarchy, or global FastAPI `exception_handler`. Errors are handled in two distinct layers:

- **Backend (FastAPI/Python)** — route handlers raise `fastapi.HTTPException` for client-facing errors; internal agent loops swallow exceptions via broad `try/except Exception` blocks and log via an in-process audit logger.
- **Frontend (Next.js/React)** — components use local `try/catch` around each `fetch`, log with `console.error`, and surface user-visible messages through React state (`setError`) or inline `alert`.

There is no `errors/` package, no sentinel error classes, no `panic`/`recover` equivalent, and no middleware-level error transformer.

## Backend Conventions

### Route-layer HTTPException usage

Route modules import `HTTPException` from `fastapi` and raise it with explicit `status_code` + `detail`:

- `routes_agents.py:149` — wraps a `ValueError` from `set_agent_cache_duration` into `HTTPException(status_code=400, detail=str(exc))`.
- `routes_market.py:103-104` — raises `502` when Base token market data cannot be fetched.
- `routes_market.py:135,140` — raises `422` for invalid volume/address queries.
- `routes_market.py:159` — raises `502` for failed token volume fetches.
- `routes_portfolio.py:45,55` — raises `404` when demo mode is disabled.
- `routes_portfolio.py:78-79` — raises `403` for unauthorized portfolio access.

The status codes used are descriptive of the failure class (400 bad request, 403 forbidden, 404 not found, 422 validation, 502 upstream failure). There is no shared constants module for these codes.

### Internal agent error swallowing

Long-running agents do not propagate errors upward. Instead they catch broadly and continue:

- `agents/controller.py:99-102` — reconstructing proposals from disk silently skips malformed entries (`except Exception: continue`).
- `agents/controller.py:105-108` — reconstructing `last_trade_times` catches `(TypeError, ValueError)` and continues.
- `agents/controller.py:129-182` — `_reconstruct_state_from_trades` wraps the whole reconstruction in `try/except Exception` and prints `Failed to reconstruct state: {exc}`.
- `agents/audit_agent.py:20-29` — file persistence is wrapped in `try/except OSError` because the volume may be read-only (tests, containers).
- `agents/polling_agent.py:16-17` — validates cache duration by raising `ValueError("Cache duration must be at least 60 seconds")`; this is caught only by the route handler that calls it.

This means failures inside the agent loop are treated as non-fatal background noise rather than request failures.

### Startup tasks

`app/main.py:44-54` wraps both async startup tasks (`get_cached_market_data`, `fetch_all_feeds`) in `try/except Exception` and logs failures without crashing the server. This is intentional: the API should stay up even if pre-population fails.

### No global exception handler

A grep for `@app.exception_handler` / `exception_handler` across the backend returns zero matches. All HTTP responses go through FastAPI's default JSON error formatter.

### External service error handling

Service modules inspect `response.status_code` directly rather than raising domain exceptions:

- `services/coingecko.py:107,170` — checks `response.status_code == 200` and `== 429`, logging via `print`.
- `services/coinmarketcap.py:132,146,162,173` — same pattern per batch.
- `services/geckoterminal.py:113` — retries once on `429`.
- `api/routes_market.py:78` — detects rate-limiting by checking `exc.response.status_code == 429`.

## Frontend Conventions

### Per-call try/catch

Every network call in the UI is individually wrapped:

- `components/AgentsControlPanel.tsx` — start/stop/halt/resume, proposal complete/reject, and toggle all have their own `try/catch(e) { console.error(...) }` blocks.
- `context/MarketDataContext.tsx:51-59` — loads cached data then fresh data, catching storage and fetch errors separately.
- `context/MarketDataContext.tsx:72-85` — health-check gate throws `Error('Backend not ready')` before fetching market data.
- `app/news/page.tsx:51` — throws `Error("Failed to fetch news feeds")`.
- `components/BaseTokensPanel.tsx:45` — throws `Error("Unable to load Base tokens. Try refreshing.")` when `!response.ok`.
- `components/DemoPortfolio.tsx:34` — throws `Error(\`Backend returned ${res.status}\`)`.

### User-facing error state

`MarketDataContext.tsx` exposes an `error` string via React context. On failure it maps the raw message to a friendlier one (`"Backend starting up... Please wait a moment and try again."`) and falls back to stored data if available, only rethrowing when there is no cached data.

### Inline alerts

For critical user actions the frontend uses `alert()` directly (e.g. `alert("Please connect wallet first")` before executing a trade proposal in `AgentsControlPanel.tsx:229`).

## Key Files

- `backend/app/main.py` — FastAPI app bootstrap, CORS middleware, startup task error wrapping.
- `backend/app/api/routes_agents.py` — canonical example of converting a Python `ValueError` to `HTTPException(400)`.
- `backend/app/api/routes_market.py` — `HTTPException` usage for upstream failures (502) and validation (422).
- `backend/app/api/routes_portfolio.py` — `HTTPException` for auth/config gates (403, 404).
- `backend/app/agents/controller.py` — broad `try/except Exception` swallowing inside the long-running agent loop.
- `backend/app/agents/polling_agent.py` — source of the `ValueError` raised for invalid cache duration.
- `frontend/context/MarketDataContext.tsx` — reference pattern for health-gated fetch, user-friendly error mapping, and fallback to localStorage.
- `frontend/components/AgentsControlPanel.tsx` — representative of per-call `try/catch` + `console.error` pattern across the UI.

## Conventions Observed

1. Backend route handlers translate domain/validation errors into `fastapi.HTTPException` with explicit numeric `status_code` and human-readable `detail`.
2. Long-running agent internals swallow exceptions broadly (`except Exception`) and persist/log state instead of propagating — treating agent-loop failures as recoverable.
3. Startup-time background work is wrapped in `try/except Exception` so a single failing cache prefill does not prevent the server from starting.
4. External API clients check `response.status_code` explicitly (especially `200` and `429`) rather than raising exceptions.
5. Frontend code never centralizes error handling; each async operation has its own `try/catch` block that logs to `console.error` and optionally updates component state.
6. User-facing errors are surfaced either through React context state (`setError`) or inline `alert()` for blocking conditions.
7. There is no repository-wide error type hierarchy, no sentinel error values, and no global FastAPI exception handler — conventions are enforced only by repeated practice across files.