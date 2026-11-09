from typing import List, Dict, Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from ..models.agents import PollingConfig, AgentStatus, TradeProposal, AuditLog
from ..agents.controller import controller

router = APIRouter()


class CompleteRequest(BaseModel):
    tx_hash: Optional[str] = None


class HaltRequest(BaseModel):
    reason: str = "Manual kill switch"


@router.post("/holdings")
async def update_holdings(holdings: Dict[str, float]):
    """Dynamically update user holdings in the controller."""
    controller.set_user_holdings(holdings)
    return {"status": "ok", "holdings": holdings}


@router.post("/start", response_model=AgentStatus)
async def start_agents(config: PollingConfig) -> AgentStatus:
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


@router.post("/halt", response_model=AgentStatus)
async def halt_agents(payload: Optional[HaltRequest] = Body(None)) -> AgentStatus:
    """Kill switch: stop opening new trades until resumed."""
    controller.halt(payload.reason if payload else "Manual kill switch")
    return controller.get_status()


@router.post("/resume", response_model=AgentStatus)
async def resume_agents() -> AgentStatus:
    controller.resume()
    return controller.get_status()


@router.get("/status", response_model=AgentStatus)
async def get_status() -> AgentStatus:
    return controller.get_status()


@router.get("/state")
async def get_state() -> dict:
    """Guardrail and indicator state for the dashboard."""
    status = controller.get_guardrail_status()
    status["positions"] = {
        token: {
            "avg_entry": round(state.get("avg_entry", 0.0), 8),
            "buy_step": state.get("buy_step", 0),
            "peak_price": state.get("peak_price", 0.0),
            "cumulative_sold": round(float(state.get("cumulative_sold", 0.0) or 0.0), 4),
        }
        for token, state in controller.position_states.items()
        if state.get("avg_entry")
    }
    status["indicators"] = {
        token: controller.history.summary(token)
        for token in controller.monitored_tokens
    }
    return status


@router.get("/proposals", response_model=List[TradeProposal])
async def get_proposals() -> List[TradeProposal]:
    return controller.get_proposals()


@router.get("/logs", response_model=List[AuditLog])
async def get_logs() -> List[AuditLog]:
    return controller.audit_agent.get_logs()


@router.post("/proposals/{proposal_id}/complete")
async def complete_proposal(
    proposal_id: str,
    payload: Optional[CompleteRequest] = Body(None),
    tx_hash: Optional[str] = None,
):
    """Mark a proposal executed.

    Accepts ``{"tx_hash": "0x..."}`` in the body (what the UI sends) and keeps
    the legacy query parameter for older clients.
    """
    resolved_hash = (payload.tx_hash if payload else None) or tx_hash
    controller.update_proposal_status(proposal_id, "executed", resolved_hash)
    return {"status": "ok", "tx_hash": resolved_hash}


@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal(proposal_id: str):
    controller.update_proposal_status(proposal_id, "rejected")
    return {"status": "ok"}


@router.post("/report")
async def generate_report():
    proposals = controller.get_proposals()
    executed = [p for p in proposals if p.status == "executed"]
    pending = [p for p in proposals if p.status == "pending"]

    summary = (
        f"Daily Report:\nTotal Proposals: {len(proposals)}\n"
        f"Executed: {len(executed)}\nPending: {len(pending)}\n"
    )

    if executed:
        summary += "\nExecuted Trades:\n"
        for proposal in executed:
            summary += (
                f"- {proposal.action.upper()} {proposal.token} "
                f"Amount: {proposal.amount} @ {proposal.price}\n"
            )

    return {"summary": summary}


@router.post("/config/cache-duration")
async def update_agent_cache_duration(duration: int):
    try:
        from ..agents.polling_agent import set_agent_cache_duration

        new_duration = set_agent_cache_duration(duration)
        return {"status": "ok", "cache_duration": new_duration}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
