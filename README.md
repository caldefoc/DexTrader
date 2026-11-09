# DexTrader

A two-part crypto trading app: a Next.js dashboard that reads your wallet in the browser, and a FastAPI backend that turns market data into trade *proposals* which you approve and sign yourself.

It was built as a personal experiment in semi-autonomous trading: a small pipeline of rule-based "agents" watches a watchlist, proposes buys on confirmed dips and sells on a mechanical exit ladder, and the browser does the actual swapping (Uniswap on Base, plus Uniswap V2/V3 and Aerodrome paths for other chains). There is no server-side private key anywhere — the backend never signs or sends a transaction. Its job ends at "here is a proposal"; the wallet popup is the gate.

The strategy rules from the original design brief (`agent_guidelines.txt`) are implemented: RSI(14), VWAP deviation, a 5-minute volume-spike filter, a scale-out ladder, stop-loss and trailing stops, a daily drawdown circuit breaker and a kill switch. What remains thin is the infrastructure around them — JSON files instead of a database, global spot pricing rather than the DEX pool the swap executes against, and a localhost-only security posture. [Remaining gaps](#remaining-gaps) lists them honestly.

This is a **reference release**: the code runs and is tested, but it is not a product and it is not financial advice. It talks to Base mainnet by default and moves real funds when you approve a swap — use a testnet or small amounts until you trust it. A hosted demo with a simulated portfolio and no wallet runs at <https://dextrader.caldefoc.com> (see [Demo mode](#demo-mode)).

![Python](https://img.shields.io/badge/python-3.12%2B-blue) ![Next.js](https://img.shields.io/badge/Next.js-14.2.3-black) ![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)

## What it does

1. **Market data.** The backend pulls a ranked listing from CoinMarketCap's keyless `trial-pro-api` host (top 50 for the agent loop, top 200 for the dashboard), then fills in the 46 hardcoded `PRIORITY_SYMBOLS` — the tokens this thing actually trades — most of which sit outside that listing. Since the trial host returns 403 for `quotes/latest`, the fill-in comes from CoinGecko by coin id instead. Prices are global spot prices in USD, not Base DEX pool prices. The dashboard caches results for one hour (five minutes for the Base-token and volume panels); the agent loop uses its own 60-second cache so the strategy sees fresh prices.
2. **Signals.** `GET /signals` tries DeepSeek first (plain `httpx` call to `api.deepseek.com`, model `deepseek-chat`), falls back to OpenAI `gpt-4o-mini` through LangChain, and finally to a deterministic rule: `≥ +10%` 24h → sell, `≤ −10%` → buy, else hold (`services/strategy.py`).
3. **Agent pipeline.** The `Controller` agent runs a loop: poll market data → filter to the 17 monitored tokens ∪ current holdings → record the sample in a rolling price/volume history → `AnalysisAgent` (indicator-gated dip buys, scale-out ladder, stop ladder, trailing stop) → `RiskAgent` (confidence, live gas ceiling, gas-vs-profit, position cap, portfolio circuit breakers) → `ExecutionAgent` (sizes the trade, or rejects it when there is no buying power) → append a `TradeProposal`. `AuditAgent` writes every step to a rotating `backend/agents.log` (5 MB × 3) and keeps the last 1,000 entries in memory for the UI.
4. **Human approval, then on-chain execution.** Proposals are fetched by the browser. The Agents page polls `/agents/proposals` every 2 s; the optional auto-trade mode polls on its own interval and executes eligible proposals without a click. Either way the swap is built and sent **in the browser** through the injected wallet (`window.ethereum`), then the result (including `price_usd` at execution and the `tx_hash`) is POSTed back to `/portfolio/trade`.
5. **Ledger and state.** Trades land in `backend/trades.json` (gitignored; the app starts with an empty ledger) with a documented record shape: `amount` = quote quantity, `token_amount` = base quantity, `token` = quote symbol, `price` = quote per base, `price_usd` = USD per base at execution. Holdings and average entry prices are reconstructed from that file on startup. Strategy state (buy steps, peak price, tranches sold, last exit), open proposals and the guardrail counters persist to `backend/agent_state.json`, and indicator history to `backend/price_history.json` (both gitignored). There is no database.
6. **Pages.** `/dashboard` (market table plus signals), `/portfolio` (live wallet balances read with `ethers`, plus a Base-token ranking panel), `/agents` (controller start/stop, halt/resume, guardrail state, live logs, proposal queue), `/reports` (trade history, CSV export), `/news` (7 crypto RSS feeds), `/settings`.

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
| Persistence | JSON files (`trades.json`, `agent_state.json`, `price_history.json`, all gitignored) + rotating log | `backend/app/services/portfolio.py`, `state_store.py`, `agents/audit_agent.py` |

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
| `CORS_ORIGINS` | `backend/app/main.py:16` | Comma-separated allowed origins. Defaults to `http://localhost:3000,http://127.0.0.1:3000`; credentials are disabled if you set `*`. |
| `BASE_RPC_URL` | `backend/app/services/gas.py:12` | JSON-RPC endpoint used to read `eth_gasPrice` for the risk layer. Defaults to `https://mainnet.base.org`. |
| `DEXTRADER_STATE_DIR` | `backend/app/services/state_store.py:16` | Directory for `agent_state.json` and `price_history.json`. Defaults to `backend/`. |
| `NEXT_PUBLIC_BACKEND_URL` | `frontend/constants/config.ts:1` | Backend origin, reused by every page. Defaults to `http://127.0.0.1:8000`. |
| `DEMO_MODE` | `backend/app/core/config.py:16` | Runs the backend as a public demo: virtual $1,000 portfolio, real market data, simulated fills, `POST /portfolio/trade` refused with 403. |
| `NEXT_PUBLIC_DEMO_MODE` | `frontend/constants/config.ts:8` | Demo build: banner, no wallet button, "Simulate" instead of "Review & Sign", portfolio page reads the virtual portfolio. Build-time — requires a rebuild. |
| `LANGCHAIN_API_KEY` | nothing | Present in `.env`, not referenced by any Python file. LangChain tracing is not configured. |

`.env.example` mirrors the functional list with empty values; copy it to `.env`.

In-app settings are browser-only (`localStorage` keys prefixed `dexTrader_`): display currency (USD/EUR, rate pulled from `api.exchangerate-api.com`), network (`sepolia` / `mainnet` / `base` / `arbitrum`, default `base`), signals polling interval, market refresh interval, agent cache duration (60 s ⇄ 3600 s, posted to `POST /agents/config/cache-duration`), auto-trading on/off and its interval (default 300 s). Two are cosmetic: `marketRefreshInterval` is stored and rendered but nothing schedules a refresh from it, and `pollingInterval` only drives the `/signals` poll.

## Demo mode

The deployment at <https://dextrader.caldefoc.com> runs with `DEMO_MODE=1` and a frontend built with `NEXT_PUBLIC_DEMO_MODE=1`. In that mode:

- The agent loop runs for real: live prices, real indicators, real proposals, real guardrails.
- The portfolio starts at $1,000 of simulated USDC (`services/demo_portfolio.py`). Executing a proposal ("Simulate") fills it immediately at the proposal price and updates cash, position size and average entry. The fill is recorded with a `demo-` hash in `demo_portfolio.json`; `trades.json` is never touched.
- `POST /portfolio/trade` returns 403, so nothing can inject a "real" trade into the demo ledger. `POST /portfolio/holdings` and `/agents/holdings` are ignored — the virtual portfolio is the only source of balances.
- Auto-trading is hard-disabled in the browser, even if a wallet extension is present and the toggle was left on. The wallet button is replaced by a "Demo mode" badge.
- `GET /portfolio/demo` returns the virtual summary, `POST /portfolio/demo/reset` restores $1,000 and clears positions. The banner offers a reset button.
- Fills ignore slippage, fees and price impact; they are bookkeeping, not a backtest.

Backend and frontend flag must agree. `NEXT_PUBLIC_DEMO_MODE` is baked in at build time, so changing it requires `npm run build` again.

## API surface

All routes are unauthenticated. CORS defaults to the two localhost origins and is controlled by `CORS_ORIGINS`; nothing else guards the API, so do not expose it on a host without adding auth in front.

| Prefix | Routes |
|---|---|
| `/market` | `GET /`, `/gainers-losers`, `/base-tokens`, `/token-volumes` |
| `/portfolio` | `POST /holdings`, `POST /trade`, `GET /trades`, `/trades/export`, `/trades/debug`, `POST /trades/reload`, `GET /` (stub, always empty), `GET /demo`, `POST /demo/reset` (last two only in demo mode) |
| `/agents` | `POST /start`, `/stop`, `/halt`, `/resume`, `/holdings`, `/proposals/{id}/complete`, `/proposals/{id}/reject`, `/report`, `/config/cache-duration`; `GET /status`, `/state`, `/proposals`, `/logs` |
| `/signals` | `GET /` |
| `/news` | `GET /feeds` |
| — | `GET /health` |

`POST /agents/proposals/{id}/complete` accepts `{"tx_hash": "0x…"}` in the body (what the UI sends) and still honours the legacy `?tx_hash=` query parameter. `GET /agents/state` returns guardrail counters, equity/drawdown, per-position strategy state and the current indicator values for every monitored token. `/market/token-volumes` accepts only `chain_id` 1, 8453 or 42161, at most 100 `0x…` addresses, and rejects malformed or duplicated query fields with 422 before any upstream call.

## Layout

```
backend/
  app/
    main.py                 FastAPI app, configurable CORS, router wiring, cache warm-up
    core/config.py          .env loading; the four API keys
    api/                    routes_market, routes_portfolio, routes_agents, routes_signals, routes_news
    agents/                 controller (loop), analysis, risk, execution, audit, polling, langchain_signals
    services/               indicators, market_history, guardrails, gas, policy, state_store, demo_portfolio,
                            coinmarketcap, coingecko, geckoterminal, base_tokens, portfolio, reports, strategy
    models/                 Pydantic models: market, portfolio, agents, signals
  trades.json               runtime ledger (gitignored)
  agent_state.json          proposals + strategy/guardrail state (gitignored)
  price_history.json        rolling indicator samples, 48 h (gitignored)
  demo_portfolio.json       virtual demo cash/positions/fills (gitignored)
  agents.log                rotating audit log, 5 MB × 3 (gitignored)
  base_address_cache.json   runtime CoinGecko-id → Base contract cache (gitignored)
  test_*.py                 unit tests
frontend/
  app/                      dashboard, portfolio, agents, reports, news, settings pages
  components/               MarketTable, PortfolioTable, TradePreviewModal, AgentsControlPanel, DemoBanner, DemoPortfolio, …
  context/                  Wallet, Settings, MarketData, Signals providers
  hooks/useAutoTrading.ts   proposal → swap loop
  lib/autoTradeExecutor.ts  Uniswap V3 quoting + execution on Base
  constants/tokens.ts       per-chain token, router and quoter addresses
scripts/                    cross-cutting tests (node:test and Playwright)
agent_guidelines.txt        the original design brief
```

## Tests

CI (`.github/workflows/ci.yml`) runs the backend unit tests, the frontend policy tests, `tsc --noEmit` and `next build` on every push, and fails if runtime data is ever tracked.

- **Backend unit tests** — 116 tests across `test_base_market.py`, `test_token_volumes.py`, `test_auto_trade_policy.py`, `test_base_token_support.py`, `test_indicators.py`, `test_market_history.py`, `test_analysis_agent.py`, `test_risk_agent.py`, `test_execution_agent.py`, `test_guardrails.py`, `test_agent_routes.py`, `test_demo_portfolio.py` and `test_demo_routes.py`. Plain `unittest`; all upstream HTTP is mocked. They import `app.*`, so run from `backend/`: `python -m unittest discover -p "test_*.py"`.
- **Frontend policy tests** — 18 tests in `scripts/test_auto_trade_policy.cjs` and `scripts/test_base_token_support.cjs`. `node:test`, but they transpile the real `.ts` sources in memory with `require("../frontend/node_modules/typescript")`, so `npm install` must have run. Run: `npm test` from `frontend/`, or `node --test scripts/test_auto_trade_policy.cjs`.
- **Browser smoke test** — `scripts/test_portfolio_display.py`: Playwright driving installed Chrome headless against `http://127.0.0.1:3000` (override with `PORTFOLIO_TEST_URL`), intercepting all network calls and injecting a fake `window.ethereum`. Playwright is **not** in `requirements.txt`. A dev server must be running.

Not tested: the agent proposal → execution path end to end in a browser, the swap construction inside `TradePreviewModal`, news parsing, anything touching a real chain or a real wallet.

## Strategy and safety rules

Implemented in `services/indicators.py`, `services/market_history.py`, `services/guardrails.py` and the three agents. Numbers are defaults in code, not settings.

Stablecoins (`USDC`, `USDT`, `DAI`) are treated as cash everywhere: excluded from analysis, never given position state, and rejected by the demo portfolio, so a depeg cannot produce a "sell USDC" stop-loss.

- **Indicators** — Wilder RSI(14), VWAP from rolling 24 h volume deltas, and a 5-minute volume ratio against a 1-hour baseline (spike ≥ 2×). Samples come from the agent loop's own snapshots; a new sample is taken at most once per 55 s and history is kept for 48 h. During warm-up an indicator returns `None` and the signal is either skipped or downgraded — never filled with a neutral constant.
- **Buy gates** — 24 h change ≤ −2% to be eligible; RSI ≤ 35; price at or below VWAP; volume spike required unless the dip is ≤ −5%; after a stop-loss, re-entry waits 1 hour, needs a price 1.5% below the exit, and needs a volume spike. Four buy steps of 25 / 35 / 50 / 60 % of the per-step target.
- **Exits** — stop ladder at −1.5 / −3 / −5% selling 25 / 75 / 100% of the position; trailing stop armed at +3% peak gain with a 1.5% trail; scale-out ladder selling 20 / 50 / 90% at +1.5 / +3 / +6%; the remainder is capped at +20%.
- **Risk layer** — confidence ≥ 0.50, live Base gas price capped at 50 gwei, estimated gas ≤ 10% of expected profit, minimum expected profit $0.10, position capped at 10% of portfolio value with an 8% per-step target, sells fail closed when there is no balance, and buys fail closed when there is no buying power.
- **Circuit breakers** — 20 trades/day, 6 per token, halt on −5% daily drawdown; `POST /agents/halt` is a manual kill switch and `/resume` clears both. State survives restarts.

## Remaining gaps

Honest inventory of what is still thin, hardcoded, or a deliberate simplification. Everything below was read from the code, not inferred from commit messages.

- **Pricing source ≠ execution venue.** Proposals are priced from global CMC/CoinGecko spot; execution is a Base DEX swap. Auto-trade handles only `ETH, WETH, VVV, VIRTUAL, AERO, TIBBIR, AVNT` (`autoTradeExecutor.ts`) and refuses anything not on chain 8453, so the 17-symbol watchlist mostly produces proposals the auto-trader will skip (they remain manually executable from the wallet).
- **Indicators need uptime.** RSI(14) needs 15 samples and VWAP needs volume deltas, so a freshly started backend trades on the 24 h change only (at reduced confidence) until roughly an hour of history exists. History is persisted across restarts to shorten this, but a long outage still resets the warm-up window.
- **The volume filter uses 24 h volume deltas.** Upstream provides `volume_24h`, not per-minute volume, so the 5-minute bucket is derived by differencing consecutive samples. It is a proxy: it responds correctly to bursts, but it cannot see intra-sample noise.
- **Hardcoded numbers in the money path.** Per-step sizing, the 8% target / 10% cap, dust floor $0.50, minimum trade $2.00, gas limit 250k, auto-trade gas price, and the 0.5–2% slippage bounds are constants in code. The Reports page and CSV exporter now prefer `price_usd` captured at execution and only fall back to a fixed rate table for older records.
- **Inverted-pair handling is heuristic.** Reports decides whether a trade is "inverted" from a hardcoded list of currency symbols; `portfolio.get_user_holdings()` keeps a legacy-format branch for old records. Both work around inconsistent historical entries in the same JSON file.
- **JSON persistence.** State is written atomically, but there is no database, no migration path and no multi-process safety; two Uvicorn workers would fight over the same files. Concurrent writes from the browser and the agent loop are serialised in-process only.
- **Security posture is localhost-only.** No auth, no user model, wallet addresses never persisted server-side, and CORS is a configuration default rather than a security boundary. The audit log now rotates, but there is no retention policy beyond that.
- **Market cache is long for a trading UI.** The dashboard's market cache is 3,600 s by default (configurable); the agent loop uses 60 s, so proposals stay fresh even when the table does not.
- **Repository hygiene.** `backend/trades.json`, `agents.log`, `agent_state.json`, `price_history.json`, the `*.backup` copies and the raw JSON-RPC dumps are gitignored and must stay that way; CI fails if any is tracked. `.qoder/repowiki/` is excluded until it is regenerated against the current code.
- **Dependency notes.** `requirements.txt` is pinned to the versions the tests were run against, and lists no test dependencies (`pytest` is not used; Playwright is not listed). `zustand` is a declared frontend dependency and imported nowhere.
- **The demo is bookkeeping, not a simulator.** Simulated fills execute instantly at the proposal price with no slippage, fees, gas or partial fills, so demo P&L is optimistic by construction. It also shares the pricing-source caveat above.
- **Docs drift.** `.qoder/repowiki/` contains a generated English wiki for this repo (architecture, API reference, token ecosystem). Useful for orientation, but generated at some earlier point; where it disagrees with the code, the code is right.

## Not covered here

- **Licence.** GPL-3.0-only; see `LICENSE`.
- **Deployment.** No Dockerfile or production notes yet. `npm run build` is exercised in CI; `next start` and a hosted deployment are not.
- **Minimum versions.** Python 3.12+ (CI uses 3.12; developed on 3.14). Node 20+ (CI uses 20; developed on 24).
- **Upstream API behaviour.** CMC's keyless `trial-pro-api` path and CoinGecko's anonymous limits were not re-verified; the code's own comments record earlier failures (CMC `quotes/latest` 403 on the trial path, CoinGecko rejecting underscore headers). Expect upstream shape changes to surface as a token silently missing from the list rather than an error.

## Licence

GPL-3.0-only. See [LICENSE](LICENSE).

## Disclaimer

Experimental software, provided as-is under the GPL's warranty disclaimer. It can lose money: it trades real tokens on Base mainnet by default and prices proposals from global spot rather than the DEX pool it executes against. The risk layer is real but it is a set of heuristics, not a guarantee. Nothing here is financial advice. Use a testnet or amounts you can afford to lose.

## History

Started early 2026 as an experiment in agent-driven trading, with `agent_guidelines.txt` written before the code. The shape that survived is: server-side reasoning, client-side signing. The strategy layer originally shipped as literals (`rsi = 50`, `vwap = price`); those are now computed from a rolling history, with stop ladders, guardrails and persisted state added on top.
