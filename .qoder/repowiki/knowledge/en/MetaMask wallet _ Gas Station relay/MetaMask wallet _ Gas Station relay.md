---
kind: external_dependency
name: MetaMask wallet / Gas Station relay
slug: metamask
category: external_dependency
category_hints:
    - client_constraint
    - framework_behavior
scope:
    - '**'
source_files:
    - frontend/lib/autoTradeExecutor.ts
    - frontend/components/TradePreviewModal.tsx
---

### Role
Injected browser wallet (`window.ethereum`) that opens the confirmation popup and, when the user selects a non-native token (USDC, WETH) as the gas-payment method, routes the transaction through MetaMask's Gas Station relay so the user pays gas in that token instead of ETH.

### Integration shape
- The app itself never calls Gas Station directly; it submits an EIP-1559 transaction via `eth_sendTransaction` and lets MetaMask decide whether to relay it.
- Selecting ETH restores normal EIP-1559 control (Low/Normal/High), where the app's configured gas price (default 0.01 gwei on Base) applies.

### Stable guidance for users / support
- Verify exact quoting behavior against MetaMask's Gas Station docs.