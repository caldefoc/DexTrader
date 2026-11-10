---
kind: external_dependency
name: Uniswap V3 router/quoter on Base
slug: uniswap-v3
category: external_dependency
category_hints:
    - sdk_real_api
scope:
    - '**'
source_files:
    - frontend/lib/autoTradeExecutor.ts
    - frontend/constants/tokens.ts
---

### Role
On-chain DEX contract pair used by the frontend's `autoTradeExecutor.ts` to build and submit swap transactions on Base. Router and quoter addresses are declared in `frontend/constants/tokens.ts`.

### Stable integration notes
- Auto-trade mode supports only `ETH, WETH, VVV, VIRTUAL, AERO, TIBBIR, AVNT` and refuses anything not on chain 8453; manual trades from the wallet popup are broader.
- Verify router/quoter addresses and ABI against the latest Uniswap V3 deployment on Base.