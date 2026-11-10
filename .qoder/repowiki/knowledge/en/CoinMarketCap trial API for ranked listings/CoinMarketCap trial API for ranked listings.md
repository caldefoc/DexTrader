---
kind: external_dependency
name: CoinMarketCap trial API for ranked listings
slug: coinmarketcap
category: external_dependency
category_hints:
    - sdk_real_api
    - client_constraint
scope:
    - '**'
source_files:
    - backend/app/services/coingecko.py
---

### Role
Primary source for the ranked token listing that seeds the agent watchlist (top 50 for the agent loop, top 200 for the dashboard). Uses the keyless `trial-pro-api` host by default, which rejects `quotes/latest` with 403 — so per-token USD quotes fall back to CoinGecko by coin id.

### Stable integration notes
- `COINMARKETCAP_API_KEY` is only sent when the base URL is NOT the hardcoded trial host; with the trial host the key is never transmitted.
- Upstream shape changes surface silently (a token simply drops off the list); no explicit error handling around the trial path.
- Verify current trial-host endpoint and rate limits against CoinMarketCap docs.