import asyncio
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes_market import router as market_router, get_cached_market_data
from .api.routes_portfolio import router as portfolio_router
from .api.routes_agents import router as agents_router
from .api.routes_signals import router as signals_router
from .api.routes_news import router as news_router, fetch_all_feeds

app = FastAPI(title="DexTrader Backend")

# Comma-separated list; defaults to the local dev origins only.  Set
# CORS_ORIGINS="*" deliberately when exposing the API on a host.
_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials="*" not in _origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(market_router, prefix="/market", tags=["market"])
app.include_router(portfolio_router, prefix="/portfolio", tags=["portfolio"])
app.include_router(agents_router, prefix="/agents", tags=["agents"])
app.include_router(signals_router, prefix="/signals", tags=["signals"])
app.include_router(news_router, prefix="/news", tags=["news"])


@app.on_event("startup")
async def startup_event():
    """Pre-populate caches on startup to prevent duplicate API calls."""
    try:
        asyncio.create_task(get_cached_market_data(force_refresh=True))
        print("Market data cache pre-population started...")
    except Exception as exc:
        print(f"Market data cache pre-population failed: {exc}")

    try:
        asyncio.create_task(fetch_all_feeds(force_refresh=True))
        print("News feeds pre-population started...")
    except Exception as exc:
        print(f"News feeds pre-population failed: {exc}")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
