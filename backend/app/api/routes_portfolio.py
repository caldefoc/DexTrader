import json
import os
from typing import List
from fastapi import APIRouter, Query, Body
from fastapi.responses import StreamingResponse
import io

from ..models.portfolio import PortfolioSnapshot, TradeExecution
from ..services.reports import generate_csv_report
from ..services.portfolio import get_all_trades, add_trade, reload_trades

from ..services import portfolio
from ..agents.controller import controller

router = APIRouter()

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
    trades = portfolio.get_all_trades()
    
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
    trades = portfolio.get_all_trades()
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
