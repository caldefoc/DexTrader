# DexTrader

A two-part crypto trading app: a Next.js dashboard that reads your wallet in the browser, and a FastAPI backend that turns market data into trade *proposals* which you approve and sign yourself.

It was built as a personal experiment in semi-autonomous trading: a small pipeline of rule-based "agents" watches a watchlist, proposes buys on dips and sells on profit targets, and the browser does the actual swapping (Uniswap on Base, plus Uniswap V2/V3 and Aerodrome paths for other chains). There is no server-side private key anywhere — the backend never signs or sends a transaction. Its job ends at "here is a proposal"; the wallet popup is the gate.

It is also, honestly, a work in progress. Several rules from the original design brief (`agent_guidelines.txt`) are not implemented, some modules are dead code, and the state lives in a JSON file. See [Known gaps](#known-gaps).

This is a **reference release**: the code runs and is tested, but it is not a product and it is not financial advice. It talks to Base mainnet by default and moves real funds when you approve a swap — use a testnet or small amounts until you trust it.

![Python](https://img.shields.io/badge/python-3.12%2B-blue) ![Next.js](https://img.shields.io/badge/Next.js-14.2.3-black) ![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)

## What it does

1. **Market data.** The backend pulls a ranked listing from CoinMarketCap's keyless `trial-pro-api` host (top 50 for the agent loop, top 200 for the dashboard), then fills in the 46 hardcoded `PRIORITY_SYMBOLS` — the tokens this thing actually trades — most of which sit outside that listing. Since the trial host returns 403 for `quotes/latest`, the fill-in comes from CoinGecko by coin id instead. Prices are global spot prices in USD, not Base DEX pool prices. Results are cached in-process for one hour (five minutes for the Base-token and volume panels).
2. **Signals.** `GET /signals` tries DeepSeek first (plain `httpx` call to `api.deepseek.com`, model `deepseek-chat`), falls back to OpenAI `gpt-4o-mini` through LangChain, and finally to a deterministic rule: `≥ +10%` 24h → sell, `≤ −10%` → buy, else hold (`services/strategy.py`).
3. **Agent pipeline.** The `Controller` agent runs a loop: poll cached market data → filter to the 17 monitored tokens ∪ current holdings → `AnalysisAgent` (dip-buy / profit-target sells) → `RiskAgent` (holdings, gas ceiling, confidence) → `ExecutionAgent` (sizes the trade) → append a pending `TradeProposal`. `AuditAgent` writes every step to `backend/agents.log` and mirrors it into an in-memory list that is never trimmed (`get_logs(limit)` only slices it for display).
4. **Human approval, then on-chain execution.** Proposals are fetched by the browser. The Agents page polls `/agents/proposals` every 2 s; the optional auto-trade mode polls on its own interval and executes eligible proposals without a click. Either way the swap is built and sent **in the browser** through the injected wallet (`window.ethereum`), then the result is POSTed back to `/portfolio/trade`.
5. **Ledger.** Trades land in `backend/trades.json` (gitignored; the app starts with an empty ledger) with a documented record shape: `amount` = quote quantity, `token_amount` = base quantity, `token` = quote symbol, `price` = quote per base. Holdings and average entry prices are reconstructed from that file on startup; there is no database.
6. **Pages.** `/dashboard` (market table plus signals), `/portfolio` (live wallet balances read with `ethers`, plus a Base-token ranking panel), `/agents` (controller start/stop, live logs, proposal queue), `/reports` (trade history, CSV export), `/news` (7 crypto RSS feeds), `/settings`.

## Stack

| Layer | Choice | Where |
|---|---|---|
| Frontend | Next.js 14.2.3 (App Router), React 18.2, TypeScript 5.4, Tailwind 3.4 | `frontend/` |
| Wallet / chain | `ethers` 6.13.2 against the injected provider (`window.ethereum`) | `frontend/lib/autoTradeExecutor.ts`, `frontend/components/TradePreviewModal.tsx` |
| State in the browser | React context + `localStorage` (no server session) | `frontend/context/`, `frontend/hooks/` |
| Backend | FastAPI + Uvicorn, Pydantic v2 models | `backend/app/` |
| LLM | LangChain + `langchain-openai`, or raw HTTP to DeepSeek | `backend/app/agents/langchain_signals.py` |
| Market data | CoinMarketCap trial API, CoinGecko, GeckoTerminal | `backend/app/services/` |
| News | `feedparser` + `httpx` over 7 RSS feeds | `backend/app/api/routes_news.py` |
| Persistence | JSON file (`backend/trades.json`, gitignored) + append-only log | `backend/app/services/portfolio.py`, `backend/app/agents/audit_agent.py` |

## Getting started

Two processes. The backend has no build step. Copy `.env.example` to `.env` if you want to supply API keys; everything runs without them.

**Backend**

```bash
cd backend
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload  # http://127.0.0.1:8000  (docs at /docs)
```

**Frontend**

```bash
cd frontend
npm install
npm run dev                    # http://localhost:3000
```

Then open <http://localhost:3000/dashboard>, connect an injected wallet, and set the network in **Settings** (default is Base).

Windows convenience scripts, all at the repo root:

- `start_dev.bat` — opens two PowerShell windows, one per service.
- `start-all.ps1` — one Windows Terminal tab split in two panes (`-Manual` to only `cd`, `-Install` to `npm install` / `pip install` first). Requires `wt`.

The backend warms its caches on startup (`@app.on_event("startup")` pre-populates market and news), so the first page load is fast; the first seconds after boot may log transient fetch errors.

## Config

Secrets live in a root-level `.env`. It exists in the working copy and is gitignored (`.gitignore:17`); its values are not reproduced here. Names, and what reads them:

| Variable | Read at | Controls |
|---|---|---|
| `COINMARKETCAP_API_KEY` | `backend/app/core/config.py:9` | Sent only when the CMC base URL is **not** `trial-pro-api`. With the current hardcoded trial URL it is never sent (keyless endpoint). |
| `COINGECKO_API_KEY` | `backend/app/core/config.py:10` | Sent as `x-cg-demo-api-key` on CoinGecko demo-API calls. Optional; requests still work anonymously (stricter rate limits). |
| `OPENAI_API_KEY` | `backend/app/core/config.py:11` | Second-tier signal source, `gpt-4o-mini` via LangChain. |
| `DEEPSEEK_API_KEY` | `backend/app/core/config.py:12` | First-tier signal source, `deepseek-chat`, `temperature: 0`, JSON output. |
| `LANGCHAIN_API_KEY` | nothing | Present in `.env`, not referenced by any Python file. LangChain tracing is not configured. |
| `NEXT_PUBLIC_BACKEND_URL` | `frontend/constants/config.ts:1` and 8 other call sites | Backend origin. Defaults to `http://127.0.0.1:8000` when unset; no `frontend/.env*` file is present, so the default is what actually runs. |

`.env.example` mirrors this list with empty values; copy it to `.env`.

In-app settings are browser-only (`localStorage` keys prefixed `dexTrader_`): display currency (USD/EUR, rate pulled from `api.exchangerate-api.com`), network (`sepolia` / `mainnet` / `base` / `arbitrum`, default `base`), signals polling interval, market refresh interval, agent cache duration (300 s ⇄ 3600 s, posted to `POST /agents/config/cache-duration`), auto-trading on/off and its interval (default 300 s). Two are cosmetic: `marketRefreshInterval` is stored and rendered but nothing schedules a refresh from it, and `pollingInterval` only drives the `/signals` poll.

## API surface

All routes are unauthenticated and CORS is `allow_origins=["*"]` (`backend/app/main.py:15`) — fine for a localhost-only tool, not for a host.

| Prefix | Routes |
|---|---|
| `/market` | `GET /`, `/gainers-losers`, `/base-tokens`, `/token-volumes` |
| `/portfolio` | `POST /holdings`, `POST /trade`, `GET /trades`, `/trades/export`, `/trades/debug`, `POST /trades/reload`, `GET /` (stub, always empty) |
| `/agents` | `POST /start`, `/stop`, `/holdings`, `/proposals/{id}/complete`, `/proposals/{id}/reject`, `/report`, `/config/cache-duration`; `GET /status`, `/proposals`, `/logs` |
| `/signals` | `GET /` |
| `/news` | `GET /feeds` |
| — | `GET /health` |

`/market/token-volumes` accepts only `chain_id` 1, 8453 or 42161, at most 100 `0x…` addresses, and rejects malformed or duplicated query fields with 422 before any upstream call.

## Layout

```
backend/
  app/
    main.py                 FastAPI app, CORS, router wiring, startup cache warm-up
    core/config.py          .env loading; the four API keys
    api/                    routes_market, routes_portfolio, routes_agents, routes_signals, routes_news
    agents/                 controller (loop), analysis, risk, execution, audit, polling (cache), langchain_signals
    services/               coinmarketcap, coingecko, geckoterminal, base_tokens, portfolio, reports, strategy
    models/                 Pydantic models: market, portfolio, agents, signals
  trades.json               runtime ledger (gitignored)
  agents.log                runtime audit log, append-only (gitignored)
  base_address_cache.json   runtime CoinGecko-id → Base contract cache (gitignored)
  test_*.py                 unit tests
frontend/
  app/                      dashboard, portfolio, agents, reports, news, settings pages
  components/               MarketTable, PortfolioTable, TradePreviewModal, AgentsControlPanel, …
  context/                  Wallet, Settings, MarketData, Signals providers
  hooks/useAutoTrading.ts   proposal → swap loop
  lib/autoTradeExecutor.ts  Uniswap V3 quoting + execution on Base
  constants/tokens.ts       per-chain token, router and quoter addresses
scripts/                    cross-cutting tests (node:test and Playwright)
agent_guidelines.txt        the original design brief (partly unimplemented)
```

## Tests

CI (`.github/workflows/ci.yml`) runs the backend unit tests, the frontend policy tests, `tsc --noEmit` and `next build` on every push, and fails if runtime data is ever tracked. There is no `npm test` script, so the commands are spelled out below.

- **Backend unit tests** — `backend/test_base_market.py` (26 tests), `test_token_volumes.py` (28), `test_auto_trade_policy.py` (3), `test_base_token_support.py` (3). Plain `unittest` (several use `IsolatedAsyncioTestCase`); all upstream HTTP is mocked. They import `app.*`, so run from `backend/`: `python -m unittest test_base_market`, etc.
- **Frontend policy tests** — `scripts/test_auto_trade_policy.cjs`, `scripts/test_base_token_support.cjs`. `node:test`, but they transpile the real `.ts` sources in memory with `require("../frontend/node_modules/typescript")`, so `npm install` must have run. Run: `node --test scripts/test_auto_trade_policy.cjs`.
- **Browser smoke test** — `scripts/test_portfolio_display.py`: Playwright driving installed Chrome headless against `http://127.0.0.1:3000` (override with `PORTFOLIO_TEST_URL`), intercepting all network calls and injecting a fake `window.ethereum`. Playwright is **not** in `requirements.txt`. A dev server must be running.

Not tested: the agent proposal → execution path end to end, the swap construction inside `TradePreviewModal`, news parsing, anything touching a real chain or a real wallet.

## Known gaps

Honest inventory of what is thin, dead, or hardcoded. Everything below was read from the code, not inferred from commit messages.

- **The brief is bigger than the implementation.** `agent_guidelines.txt` asks for RSI(14), VWAP deviation, a 5-minute volume-spike filter, scale-out ladders, stop-losses, trailing stops, daily drawdown circuit breakers and a kill switch. `AnalysisAgent` implements none of them: `vwap = price` (line 24), `rsi=50.0` (110) and `volume_spike=False` (112) are literals on every recommendation. The only real inputs are 24h % change, position state and average entry.
- **`RiskAgent` limits are decorative.** `max_gas_gwei = 50.0` is compared against a `current_gas_gwei` *default argument* of 20.0 — the controller calls `validate(rec, holdings)` with two arguments, so live gas is never passed and the check can never fire. `min_profit_usd` and `max_position_size_usd` are assigned and never read; the gas-cost figure is computed into a variable and then ignored (`risk_agent.py:43`).
- **Fallback holdings are fake money.** If holdings arrive empty, `ExecutionAgent` substitutes `{"ETH": 1.0, "USDC": 1000.0}` and sizes proposals against a ~$3,500 portfolio (`execution_agent.py:64-70`). Proposals can therefore look real while nothing is connected.
- **Dead modules and a no-op.** `agents/orchestrator.py`, `logic_agent.py` and `trading_agent.py` form a second pipeline that nothing imports; `execute_signals()` just returns its input (`trading_agent.py:49-50`), and `evaluate_risk()` alongside it is never called. `ControllerAgent._get_mock_snapshot()` (line 367) is unreferenced too.
- **Dead components.** `DailyReportSummary.tsx` and `PairSelector.tsx` are exported and never imported.
- **Sizing stops at step 3.** `AnalysisAgent` allows a fourth buy step on big dips (`current_buy_step <= 4`, line 54), but `ExecutionAgent` only parses `"Step 2"` and `"Step 3"` out of the reason string (`execution_agent.py:112-117`), so a "Value Buy Step 4" proposal is silently sized as step 1.
- **Proposals live only in memory.** `ControllerAgent.proposals` is a list on a module-level singleton; restarting Uvicorn wipes the queue. Position state is rebuilt from `trades.json`; proposals are not.
- **Pricing source ≠ execution venue.** Proposals are priced from global CMC/CoinGecko spot; execution is a Base DEX swap. Auto-trade additionally handles only `ETH, WETH, VVV, VIRTUAL, AERO, TIBBIR, AVNT` (`autoTradeExecutor.ts:4`) and refuses anything not on chain 8453 — so the 17-symbol watchlist mostly produces proposals the auto-trader will skip.
- **Hardcoded numbers in the money path.** Trade sizing is 8% of buying power (`execution_agent.py:79`), dust floor $0.50, minimum trade $2.00, gas limit 250k, auto-trade gas price `0.01` gwei (`useAutoTrading.ts:68`), 0.5% default slippage with a 1% floor for six "volatile" symbols (`autoTradeExecutor.ts:11`). The Reports page and the CSV exporter both convert quote amounts to USD with a fixed table (`ETH = 3000`) rather than a live rate (`services/reports.py:8`, `app/reports/page.tsx:57`).
- **Inverted-pair handling is heuristic.** Reports decides whether a trade is "inverted" from a hardcoded list of currency symbols and flips the displayed action accordingly; `portfolio.get_user_holdings()` reconstructs balances with a legacy-format branch for old records. Both work around inconsistent historical records in the same JSON file.
- **Cosmetic or ignored fields.** `MarketSnapshot` has no `timestamp` field, yet the controller passes one (`controller.py:280`) — Pydantic drops it silently. The agent cache comment says "5 minutes" next to `3600` (`polling_agent.py:8`), and the market cache is also 3600 s (`routes_market.py:20`) — a long time for a trading UI. `POST /agents/proposals/{id}/complete` takes `tx_hash` as a *query* parameter while the Agents page sends it in a JSON body, so manually approved proposals are marked executed without a hash (the audit entry is skipped; the trade itself is still recorded by `TradePreviewModal`). `constants/config.ts` exports `BACKEND_URL`, but eight other files re-declare the same `process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8000"` expression inline.
- **Security posture is localhost-only.** No auth, no user model, CORS `*`, wallet addresses never persisted server-side, and the audit log is a file that grows without rotation — `backend/agents.log` is already 42 MB.
- **Repository hygiene.** `backend/trades.json`, `agents.log`, the `*.backup` copies and the raw JSON-RPC dumps are gitignored and must stay that way; CI fails if any is tracked. `.qoder/repowiki/` is likewise excluded until it is regenerated against the current code.
- **Dependency notes.** `requirements.txt` is pinned to the versions the tests were run against, and lists no test dependencies (`pytest` is not used; Playwright is not listed). `zustand` is a declared frontend dependency and imported nowhere.
- **Docs drift.** `.qoder/repowiki/` contains a generated English wiki for this repo (architecture, API reference, token ecosystem). Useful for orientation, but generated at some earlier point; where it disagrees with the code, the code is right.

## Not covered here

- **Licence.** GPL-3.0-only; see `LICENSE`.
- **Deployment.** No Dockerfile or production notes yet. `npm run build` is exercised in CI; `next start` and a hosted deployment are not.
- **Minimum versions.** Python 3.12+ (CI uses 3.12; developed on 3.14). Node 20+ (CI uses 20; developed on 24).
- **Upstream API behaviour.** CMC's keyless `trial-pro-api` path and CoinGecko's anonymous limits were not re-verified; the code's own comments record earlier failures (CMC `quotes/latest` 403 on the trial path, CoinGecko rejecting underscore headers). Expect upstream shape changes to surface as a token silently missing from the list rather than an error.

## Licence

GPL-3.0-only. See [LICENSE](LICENSE).

## Disclaimer

Experimental software, provided as-is under the GPL's warranty disclaimer. It can lose money: it trades real tokens on Base mainnet by default, prices proposals from global spot rather than the DEX pool it executes against, and several risk controls described in `agent_guidelines.txt` are not implemented (see [Known gaps](#known-gaps)). Nothing here is financial advice. Use a testnet or amounts you can afford to lose.

## History

Started early 2026 as an experiment in agent-driven trading, with `agent_guidelines.txt` written before the code. The shape that survived is: server-side reasoning, client-side signing. The parts that never made it — real indicators, a risk layer with teeth, persistence for proposals — are listed above rather than quietly omitted.
