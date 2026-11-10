---
kind: external_dependency
name: GeckoTerminal market data source
slug: geckoterminal
category: external_dependency
category_hints:
    - vendor_identity
scope:
    - '**'
source_files:
    - backend/app/services/geckoterminal.py
---

Third-party market-data vendor consumed by `backend/app/services/geckoterminal.py`. Used alongside CoinMarketCap and CoinGecko to populate the dashboard's market tables.