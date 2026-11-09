import json
import os
from typing import List
from fastapi import APIRouter, Query, Body, HTTPException
from fastapi.responses import StreamingResponse
import io

from ..models.portfolio import PortfolioSnapshot, TradeExecution
from ..services.reports import generate_csv_report
from ..services.portfolio import get_all_trades, add_trade, reload_trades

from ..services import portfolio
from ..agents.controller import controller

router = APIRouter()


def _demo_trade(fill: dict) -> TradeExecution:
    return TradeExecution(
        tx_hash=fill["tx_hash"],
        network="demo",
        pair=f"{fill['token']}/USDC",
        action=fill["action"],
        amount=fill["value_usd"],
        token="USDC",
        price=fill["price"],
        token_amount=fill["quantity"],
        network_fee=0.0,
        price_usd=fill["price"],
        status="completed",
        timestamp=int(fill["timestamp"]),
    )


def _demo_trades() -> List[TradeExecution]:
    if not controller.demo_portfolio:
        return []
    return [_demo_trade(fill) for fill in controller.demo_portfolio.recent_fills(1000)]


@router.get("/demo")
async def demo_portfolio():
    """Virtual portfolio for the public demo (cash, positions, P&L)."""
    if not controller.demo or controller.demo_portfolio is None:
        raise HTTPException(status_code=404, detail="Demo mode is not enabled")
    return {
        **controller.demo_portfolio.summary(controller.last_prices),
        "prices_available": bool(controller.last_prices),
    }


@router.post("/demo/reset")
async def reset_demo_portfolio():
    if not controller.demo or controller.demo_portfolio is None:
        raise HTTPException(status_code=404, detail="Demo mode is not enabled")
    summary = controller.demo_portfolio.reset()
    controller.position_states = {}
    controller.simulated_positions = {}
    controller.user_holdings = controller.demo_portfolio.holdings()
    return summary


@router.post("/holdings")
async def update_holdings(holdings: dict = Body(...)):
    """Receive current holdings from frontend and update controller agent"""
    # holdings is expected to be { "ETH": 1.5, "USDC": 500.0, ... }
    controller.set_user_holdings(holdings)
    return {"status": "updated", "count": len(holdings)}

@router.get("/", response_model=PortfolioSnapshot)
async def get_portfolio(address: str = Query(...)) -> PortfolioSnapshot:
    return PortfolioSnapshot(address=address, positions=[])


@router.post("/trade", response_model=TradeExecution)
async def record_trade(trade: TradeExecution):
    if controller.demo:
        raise HTTPException(
            status_code=403,
            detail="Demo mode: real trade recording is disabled. Use /agents/proposals/{id}/complete to simulate a fill.",
        )
    added = portfolio.add_trade(trade)
    # Update controller state exactly once per transaction.  The same tx can
    # arrive here and through /agents/proposals/{id}/complete.
    if added:
        try:
            controller.update_position_from_trade(
                trade.pair,
                trade.action,
                trade.token_amount or 0.0,
                trade.price or 0.0,
                tx_hash=trade.tx_hash,
            )
        except Exception:
            pass
    return trade


@router.get("/trades", response_model=List[TradeExecution])
async def get_trades(
    limit: int = 100,
    network: str = Query(None),
    action: str = Query(None),
    start_date: int = Query(None),
    end_date: int = Query(None)
):
    trades = _demo_trades() if controller.demo else portfolio.get_all_trades()
    
    # Apply filters
    if network and network != "all":
        trades = [t for t in trades if t.network == network]
    
    if action and action != "all":
        trades = [t for t in trades if t.action == action]
        
    if start_date:
        trades = [t for t in trades if t.timestamp >= start_date]
        
    if end_date:
        trades = [t for t in trades if t.timestamp <= end_date]
        
    return trades[-limit:]

@router.get("/trades/export")
async def export_trades(eth_price: float = Query(3000.0, gt=0)):
    trades = _demo_trades() if controller.demo else portfolio.get_all_trades()
    csv_content = generate_csv_report(trades, eth_price=eth_price)
    return StreamingResponse(
        io.StringIO(csv_content),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=trade_report.csv"}
    )

@router.post("/trades/reload")
async def reload_trades_endpoint():
    """Reload trades from the JSON file (useful when file is updated externally)"""
    reloaded_trades = reload_trades()
    return {"status": "reloaded", "count": len(reloaded_trades)}

@router.get("/trades/debug")
async def debug_trades():
    """Debug endpoint to see what trades are being returned"""
    trades = get_all_trades()
    debug_info = []
    for trade in trades[-10:]:  # Show last 10 trades
        debug_info.append({
            "pair": trade.pair,
            "action": trade.action,
            "token": trade.token,
            "amount": trade.amount,
            "token_amount": trade.token_amount,
            "timestamp": trade.timestamp
        })
    return {"total_trades": len(trades), "recent_trades": debug_info}
