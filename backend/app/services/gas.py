"""Live gas price for the chain the browser executes on (Base by default)."""

from __future__ import annotations

import os
import time
from typing import Optional

import httpx


BASE_RPC_URL = os.getenv("BASE_RPC_URL", "https://mainnet.base.org")
FALLBACK_GAS_GWEI = 0.01
CACHE_SECONDS = 60.0

_cached_gas: Optional[float] = None
_cached_at = 0.0


def estimate_gas_usd(gas_gwei: float, gas_limit: int, eth_price_usd: float) -> float:
    """Gas cost in USD: gwei * 1e-9 ETH/gas * gas * USD/ETH."""
    if gas_gwei is None or gas_limit is None or eth_price_usd is None:
        return 0.0
    return max(0.0, float(gas_gwei) * 1e-9 * float(gas_limit) * float(eth_price_usd))


async def get_gas_price_gwei(rpc_url: Optional[str] = None, timeout: float = 3.0) -> float:
    """Fetch ``eth_gasPrice`` from the configured RPC, cached for 60 seconds.

    Returns a conservative fallback instead of raising: the risk layer will
    still apply the gas cap to whatever value it receives, and a failed RPC
    must not stop the whole agent loop.
    """
    global _cached_gas, _cached_at

    now = time.time()
    if _cached_gas is not None and now - _cached_at < CACHE_SECONDS:
        return _cached_gas

    url = rpc_url or BASE_RPC_URL
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                json={"jsonrpc": "2.0", "id": 1, "method": "eth_gasPrice", "params": []},
            )
            response.raise_for_status()
            payload = response.json()
        wei = int(payload["result"], 16)
        gwei = wei / 1e9
        if not (0 <= gwei < 10_000):
            raise ValueError(f"implausible gas price {gwei} gwei")
    except Exception as exc:
        print(f"[Gas] Could not fetch gas price from {url}: {exc}; using {FALLBACK_GAS_GWEI} gwei")
        gwei = _cached_gas if _cached_gas is not None else FALLBACK_GAS_GWEI

    _cached_gas = float(gwei)
    _cached_at = now
    return _cached_gas
