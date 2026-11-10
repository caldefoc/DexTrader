---
kind: business_term
name: Business Glossary
category: business_term
scope:
    - '**'
---

### Virtual
- Definition：Internal stablecoin symbol used by DexTrader's demo/portfolio system (referenced as `VIRTUAL` and `VVV` in the auto-trader allowlist and portfolio code). Not a public ERC-20 token — it represents the simulated cash balance in demo mode and appears in the app's internal token set.
- Aliases：VVV

### PRIORITY_SYMBOLS
- Definition：Hardcoded set of 46 token symbols that the app actively tracks and proposes trades for. They supplement the dynamic CoinMarketCap ranking and are the tokens whose USD quotes are filled via CoinGecko when the CMC trial endpoint lacks them.

### Demo mode
- Definition：Build/runtime flag (`DEMO_MODE=1` backend, `NEXT_PUBLIC_DEMO_MODE=1` frontend) that replaces real trading with bookkeeping over a virtual $1,000 USDC portfolio. Trades are instantly filled at proposal price without slippage, fees or partial fills; `POST /portfolio/trade` returns 403 and the wallet button is replaced by a Demo badge.

### Kill switch
- Definition：Manual halt command (`POST /agents/halt`) that stops the agent pipeline and clears both the daily-trade and drawdown circuit breakers; `/resume` re-enables it. It is the team's emergency stop for the autonomous trading loop.
- Aliases：halt

### Scale-out ladder
- Definition：Mechanical exit strategy that sells portions of a position at predefined profit levels: 20% at +1.5%, 50% at +3%, 90% at +6%, with the remainder capped at +20%. Implemented in the analysis agent and distinct from the stop ladder.

### Stop ladder
- Definition：Mechanical loss-exit strategy that sells 25% at −1.5%, 75% at −3%, and 100% at −5% of entry. Works together with the trailing stop (armed at +3% peak gain with a 1.5% trail).
