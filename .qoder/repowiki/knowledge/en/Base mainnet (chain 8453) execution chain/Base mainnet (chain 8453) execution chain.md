---
kind: external_dependency
name: Base mainnet (chain 8453) execution chain
slug: base
category: external_dependency
category_hints:
    - client_constraint
scope:
    - '**'
source_files:
    - backend/app/services/gas.py
    - frontend/constants/tokens.ts
---

### Role
The default and primary execution chain: all swaps go out on Base mainnet (chain id 8453). The backend reads live gas prices from Base via JSON-RPC (`BASE_RPC_URL`, default `https://mainnet.base.org`) and the risk layer caps gas at 50 gwei. Auto-trade mode refuses any swap targeting a chain other than 8453.

### Stable constraints
- Default network is `base`; `sepolia` / `mainnet` / `arbitrum` are selectable but auto-trade is hard-disabled for them.
- The L1 data fee on Base can change independently of L2 congestion and may affect total cost even when L2 blocks are unclogged.
- Verify current RPC endpoint and chain id against official Base documentation.