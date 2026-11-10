---
kind: build_system
name: 'Build & Deployment: Docker Compose + GitHub Actions CI for FastAPI/Next.js Dual-Service Stack'
category: build_system
scope:
    - '**'
source_files:
    - .github/workflows/ci.yml
    - docker-compose.yml
    - backend/Dockerfile
    - frontend/Dockerfile
    - deploy/README.md
    - deploy/Caddyfile.snippet
    - start-all.ps1
    - start_dev.bat
    - backend/requirements.txt
    - frontend/package.json
---

# Build System Overview

DexTrader is a two-service application (FastAPI backend + Next.js frontend) built and deployed via **Docker** and **GitHub Actions**. There is no Makefile or shared build script at the repository root — each service owns its own build, and `docker-compose.yml` orchestrates them together.

## Toolchain

| Layer | Tool | Details |
|---|---|---|
| Backend runtime | Python 3.12 (`python:3.12-slim`) | Uvicorn ASGI server, single worker |
| Backend deps | pip / `requirements.txt` | Installed with `--no-cache-dir` in Docker |
| Frontend runtime | Node 20 Alpine (`node:20-alpine`) | Multi-stage Dockerfile (deps → build → runner) |
| Frontend deps | npm / `package-lock.json` | `npm ci` in CI, `npm run build` produces static Next.js output |
| Container orchestration | `docker-compose.yml` | Two services (`backend`, `frontend`), named volume `dextrader-state` |
| CI | GitHub Actions (`.github/workflows/ci.yml`) | Runs on push to `main` and all pull requests |
| Reverse proxy | Caddy (host-managed) | TLS termination; `/api/*` → backend, rest → frontend |
| Local dev (Windows) | PowerShell scripts | `start-all.ps1` (one terminal split into panes) and `start_dev.bat` (two separate windows) |

## Key Files

- `.github/workflows/ci.yml` — CI pipeline (Python unittests, TypeScript type-check, Next.js build, personal-data scan).
- `docker-compose.yml` — Production-ish stack definition; binds both services to `127.0.0.1` only.
- `backend/Dockerfile` — Single-worker Uvicorn image exposing port 8000.
- `frontend/Dockerfile` — Three-stage Node image; `NEXT_PUBLIC_*` variables are baked in at build time.
- `deploy/README.md` — Hosted deployment instructions (clone → compose up → append Caddy snippet).
- `deploy/Caddyfile.snippet` — Caddy reverse-proxy rules (referenced by deploy docs).
- `start-all.ps1` / `start_dev.bat` — Windows developer launchers.

## CI Pipeline (`.github/workflows/ci.yml`)

Two parallel jobs plus one security job:

1. **`backend`** (Ubuntu, working dir `backend`):
   - Sets up Python 3.12 with pip cache.
   - `pip install -r requirements.txt`.
   - `python -m unittest discover -p "test_*.py" -v` — discovers every `test_*.py` under `backend/`.

2. **`frontend`** (Ubuntu, working dir `frontend`):
   - Sets up Node 20 with npm cache keyed on `frontend/package-lock.json`.
   - `npm ci`.
   - Runs Node-based policy tests from `scripts/test_auto_trade_policy.cjs` and `scripts/test_base_token_support.cjs` (executed from repo root via `working-directory: .`).
   - `npx tsc --noEmit` — TypeScript type checking only (no emit).
   - `npm run build` with `NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:8000`.

3. **`no-personal-data`** — Scans tracked files for runtime state patterns (`trades.json`, `deleted_corrupted_trades.json`, `agent_state.json`, `price_history.json`, `demo_portfolio.json`, `agents.log`, `acct*.json`, `nonce*.json`, `baseblock.json`, `tibbair_bal.json`, `base_address_cache.json`) and fails the build if any are committed.

## Docker Images

### Backend (`backend/Dockerfile`)

- Base: `python:3.12-slim`.
- Copies `requirements.txt` first (layer caching), then `app/`.
- Creates `/data` directory for JSON-backed state.
- Exposes port 8000.
- CMD runs Uvicorn with `--workers 1` — explicitly documented as intentional because state lives in JSON files, not a database.

### Frontend (`frontend/Dockerfile`)

- Stage 1 (`deps`): installs dependencies via `npm ci`.
- Stage 2 (`build`): copies source and builds with `npm run build`; `NEXT_PUBLIC_BACKEND_URL` and `NEXT_PUBLIC_DEMO_MODE` are passed as `ARG`s and set as `ENV` so they are inlined by Next.js at build time.
- Stage 3 (`runner`): minimal production image running `npm start`.

## Runtime State & Persistence

- The backend writes trading state to JSON files under `DEXTRADER_STATE_DIR=/data` (set in both Dockerfile and compose).
- `docker-compose.yml` mounts a named volume `dextrader-state:/data` so state survives container restarts.
- `deploy/README.md` warns that `docker compose down -v` deletes this volume.
- The compose file sets `DEMO_MODE=1` for the backend and passes `NEXT_PUBLIC_DEMO_MODE` to the frontend build args.

## Environment Variables

- `.env.example` (root) is copied into `.env` before `docker compose up`.
- `NEXT_PUBLIC_BACKEND_URL` defaults to `https://dextrader.caldefoc.com/api` in compose but can be overridden via env.
- `NEXT_PUBLIC_DEMO_MODE` defaults to `1` in compose.
- `NEXT_TELEMETRY_DISABLED=1` is set in both frontend stages.

## Local Development

- `start-all.ps1`: opens one Windows Terminal tab split into two panes; supports `-Manual` (just cd into folders), `-Install` (runs `pip install` / `npm install` first), and default mode (assumes deps installed). Uses `python -m uvicorn app.main:app --reload` and `npm.cmd run dev`.
- `start_dev.bat`: launches two separate PowerShell windows, one per service.
- Both scripts assume the user has already installed Python 3.12+ and Node 20+.

## Conventions Observed

- Each subproject manages its own dependencies independently (`backend/requirements.txt`, `frontend/package-lock.json`); there is no monorepo tool (pnpm workspaces, lerna, etc.).
- CI uses `python -m unittest` for backend tests and `tsc --noEmit` + `npm run build` for the frontend — no lint step is present in CI beyond type checking.
- Policy-related tests live in `scripts/*.cjs` and are invoked from the repo root during the frontend CI job, even though they test backend-facing policy logic.
- Runtime data files are gitignored (enforced by the `no-personal-data` CI job scanning `git ls-files`); they must never be committed.
- The backend intentionally runs a single Uvicorn worker; horizontal scaling is not supported due to file-backed state.
- Frontend configuration is compile-time only (`NEXT_PUBLIC_*`); changing these values requires rebuilding the frontend image, not just restarting it.
- Production deployment assumes an existing host-level Caddy instance; the project does not provision or manage Caddy itself.