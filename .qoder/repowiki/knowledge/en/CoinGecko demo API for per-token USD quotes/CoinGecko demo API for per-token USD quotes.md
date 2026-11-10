---
kind: external_dependency
name: CoinGecko demo API for per-token USD quotes
slug: coingecko
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
Fills in USD prices for the 46 hardcoded `PRIORITY_SYMBOLS` that CoinMarketCap's trial endpoint does not cover, called by coin id. Also supplies the exchange rate for display currency conversion (USD/EUR).

### Stable integration notes
- `COINGECKO_API_KEY` is sent as header `x-cg-demo-api-key`; anonymous requests still work but hit stricter rate limits.
- Anonymous usage is the default and expected path; upstream comments record earlier failures (underscore headers rejected).
- Verify demo-API endpoints and header format against CoinGecko docs.