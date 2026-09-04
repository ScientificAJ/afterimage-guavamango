from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict
from sse_starlette.sse import EventSourceResponse

from afterimage.contracts.models import ExecutionWarrant
from afterimage.execution import (
    AlpacaGateway,
    ExecutionService,
    build_alpaca_gateway,
    expected_account_id,
)
from afterimage.execution.reconciler import Reconciler
from afterimage.orchestration.coordinator import Coordinator
from afterimage.storage import Database

from .stream import EVENT_STREAMS, stream_session

router = APIRouter()
database = Database(os.getenv("AFTERIMAGE_DB_URL", "sqlite:///./afterimage.db"))
coordinator = Coordinator(
    database,
    signing_key_path=os.getenv("AFTERIMAGE_SIGNING_KEY_PATH", ".afterimage/warrant-ed25519.pem"),
)
SESSION_SUMMARIES: dict[str, dict[str, Any]] = {}


class ReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fixture: str = "accepted"


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    warrant_id: str


@router.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "paper_only": True,
        "execution_enabled": os.getenv("AFTERIMAGE_ENABLE_PAPER_EXECUTION", "false").lower()
        == "true",
        "strategies": coordinator.registry.list(),
        "audit_valid": coordinator.ledger.verify().valid,
    }


@router.post("/api/preflight")
async def preflight() -> dict[str, Any]:
    gateway: AlpacaGateway | None = None
    try:
        gateway = build_alpaca_gateway()
        await gateway.connect()
        checked = await gateway.preflight(expected_account_id())
        return checked.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(409, str(exc)) from exc
    finally:
        if gateway is not None:
            await gateway.close()


@router.post("/api/replays")
def replay(request: ReplayRequest) -> dict[str, Any]:
    if request.fixture not in {"accepted", "rejected"}:
        raise HTTPException(400, "fixture must be accepted or rejected")
    summary = coordinator.run_demo(accepted=request.fixture == "accepted")
    session_id = summary["session_id"]
    SESSION_SUMMARIES[session_id] = summary
    EVENT_STREAMS[session_id] = summary["events"]
    return summary


@router.get("/api/sessions/{session_id}")
def session(session_id: str) -> dict[str, Any]:
    if session_id in SESSION_SUMMARIES:
        return SESSION_SUMMARIES[session_id]
    stored = coordinator.repository.get_session(session_id)
    if stored is None:
        raise HTTPException(404, "session not found")
    return stored


@router.get("/api/sessions/{session_id}/events")
def events(session_id: str) -> list[dict[str, Any]]:
    return EVENT_STREAMS.get(session_id, [])


@router.get("/api/sessions/{session_id}/artifacts")
def artifacts(session_id: str) -> list[dict[str, Any]]:
    return coordinator.repository.session_artifacts(session_id)


@router.post("/api/risk/{session_id}")
def risk(session_id: str) -> dict[str, Any]:
    summary = SESSION_SUMMARIES.get(session_id)
    if summary is None or "risk" not in summary:
        raise HTTPException(404, "persisted risk decision not found")
    return {"risk": summary["risk"], "payoff": summary.get("payoff")}


@router.post("/api/execute/{session_id}")
async def execute(session_id: str, request: ExecuteRequest) -> dict[str, Any]:
    if os.getenv("AFTERIMAGE_ENABLE_PAPER_EXECUTION", "false").lower() != "true":
        raise HTTPException(403, "paper execution is disabled")
    payload = coordinator.repository.warrant_by_id(request.warrant_id)
    if payload is None:
        raise HTTPException(404, "warrant not found")
    warrant = ExecutionWarrant.model_validate(payload)
    gateway: AlpacaGateway | None = None
    try:
        gateway = build_alpaca_gateway()
        await gateway.connect()
        checked = await gateway.preflight(expected_account_id())
        if checked.account.account_id_hash != warrant.intent.account_id_hash:
            raise HTTPException(409, "warrant is bound to a different account")
        service = ExecutionService(gateway, coordinator.warrants, coordinator.repository)
        return (await service.submit(session_id, warrant)).model_dump(mode="json")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(409, str(exc)) from exc
    finally:
        if gateway is not None:
            await gateway.close()


@router.post("/api/reconcile/{session_id}")
async def reconcile(session_id: str) -> dict[str, Any]:
    local_orders = coordinator.repository.broker_orders(session_id)
    if not local_orders:
        raise HTTPException(404, "no submitted order exists for this session")
    client_order_id = str(local_orders[-1]["client_order_id"])
    gateway: AlpacaGateway | None = None
    try:
        gateway = build_alpaca_gateway()
        await gateway.connect()
        await gateway.preflight(expected_account_id())
        return (await Reconciler(gateway).by_client_id(client_order_id)).__dict__
    except Exception as exc:
        raise HTTPException(409, str(exc)) from exc
    finally:
        if gateway is not None:
            await gateway.close()


@router.get("/api/stream/{session_id}")
def stream(
    session_id: str, last_event_id: int | None = Header(default=None)
) -> EventSourceResponse:
    return EventSourceResponse(stream_session(session_id, last_event_id or 0))
