from typing import List, Dict
from fastapi import APIRouter, HTTPException
from ..models.agents import PollingConfig, AgentStatus, TradeProposal, AuditLog
from ..agents.controller import controller
from ..agents.audit_agent import AuditAgent # To access logs if needed

router = APIRouter()

@router.post("/holdings")
async def update_holdings(holdings: Dict[str, float]):
    """Dynamically update user holdings in the controller"""
    controller.set_user_holdings(holdings)
    return {"status": "ok", "holdings": holdings}

@router.post("/start", response_model=AgentStatus)
async def start_agents(config: PollingConfig) -> AgentStatus:
    # Update config if needed
    controller.polling_interval = config.interval_seconds
    if config.monitored_tokens is not None:
        controller.monitored_tokens = config.monitored_tokens
    if config.user_holdings is not None:
        controller.set_user_holdings(config.user_holdings)
        
    await controller.start()
    return controller.get_status()

@router.post("/stop", response_model=AgentStatus)
async def stop_agents() -> AgentStatus:
    controller.stop()
    return controller.get_status()

@router.get("/status", response_model=AgentStatus)
async def get_status() -> AgentStatus:
    return controller.get_status()

@router.get("/proposals", response_model=List[TradeProposal])
async def get_proposals() -> List[TradeProposal]:
    return controller.get_proposals()

@router.get("/logs", response_model=List[AuditLog])
async def get_logs() -> List[AuditLog]:
    return controller.audit_agent.get_logs()

@router.post("/proposals/{proposal_id}/complete")
async def complete_proposal(proposal_id: str, tx_hash: str = None):
    controller.update_proposal_status(proposal_id, "executed", tx_hash)
    return {"status": "ok"}

@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal(proposal_id: str):
    controller.update_proposal_status(proposal_id, "rejected")
    return {"status": "ok"}

@router.post("/report")
async def generate_report():
    proposals = controller.get_proposals()
    executed = [p for p in proposals if p.status == "executed"]
    pending = [p for p in proposals if p.status == "pending"]
    
    summary = f"Daily Report:\nTotal Proposals: {len(proposals)}\nExecuted: {len(executed)}\nPending: {len(pending)}\n"
    
    if executed:
        summary += "\nExecuted Trades:\n"
        for p in executed:
            summary += f"- {p.action.upper()} {p.token} Amount: {p.amount} @ {p.price}\n"
    
    return {"summary": summary}

@router.post("/config/cache-duration")
async def update_agent_cache_duration(duration: int):
    """Update the agent cache duration setting"""
    try:
        from ..agents.polling_agent import set_agent_cache_duration
        new_duration = set_agent_cache_duration(duration)
        return {"status": "ok", "cache_duration": new_duration}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
