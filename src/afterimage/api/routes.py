from __future__ import annotations

import os
import re
import secrets
from copy import deepcopy
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sse_starlette.sse import EventSourceResponse

from afterimage.agents.gateway import load_featherless_gateway
from afterimage.agents.roles import AgentDesk
from afterimage.contracts.hashing import canonical_sha256
from afterimage.contracts.models import ExecutionWarrant
from afterimage.execution import (
    build_alpaca_gateway,
    expected_account_id_hash,
)
from afterimage.execution.reconciler import Reconciler
from afterimage.orchestration.coordinator import Coordinator
from afterimage.storage import Database

from .stream import EVENT_STREAMS, stream_session

router = APIRouter()
database = Database(os.getenv("AFTERIMAGE_DB_URL", "sqlite:///./.afterimage/afterimage.db"))
coordinator = Coordinator(
    database,
    signing_key_path=os.getenv("AFTERIMAGE_SIGNING_KEY_PATH", ".afterimage/warrant-ed25519.pem"),
)
SESSION_SUMMARIES: dict[str, dict[str, Any]] = {}
SAFE_REASON = re.compile(r"^[A-Z][A-Z0-9_]*(?::[A-Za-z0-9_.@/ -]+)?$")
MAX_CACHED_SESSIONS = int(os.getenv("AFTERIMAGE_MAX_CACHED_SESSIONS", "50"))


class ReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fixture: str = "accepted"


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    warrant_id: str


class ShadowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str | None = Field(default=None, pattern=r"^[A-Za-z]{1,5}$")
    strategy_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{2,63}$")


def require_execution_token(provided: str | None) -> None:
    expected = os.getenv("AFTERIMAGE_EXECUTION_TOKEN", "")
    if not expected:
        raise HTTPException(503, "paper execution API is not armed")
    if provided is None or not secrets.compare_digest(provided, expected):
        raise HTTPException(403, "paper execution authorization failed")


def require_operator_token(provided: str | None) -> None:
    if os.getenv("AFTERIMAGE_REQUIRE_OPERATOR_AUTH", "false").lower() != "true":
        return
    expected = os.getenv("AFTERIMAGE_OPERATOR_TOKEN", "")
    if not expected:
        raise HTTPException(503, "operator API is not armed")
    if provided is None or not secrets.compare_digest(provided, expected):
        raise HTTPException(403, "operator authorization failed")


def public_error_detail(error: Exception) -> str:
    detail = str(error)
    return detail if len(detail) <= 160 and SAFE_REASON.fullmatch(detail) else "OPERATION_BLOCKED"


def redact_artifacts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"kind": item["kind"], "hash": item["hash"], "redacted": True}
        if item.get("kind") in {"warrant", "exit_warrant"}
        else public_summary(item)
        for item in items
    ]


def _public_warrant(warrant: dict[str, Any]) -> dict[str, Any]:
    def fingerprint(name: str) -> str:
        value = str(warrant.get(name, ""))
        return canonical_sha256({name: value}) if value else ""

    return {
        "intent_hash": warrant.get("intent_hash"),
        "risk_vector_hash": warrant.get("risk_vector_hash"),
        "expires_at": warrant.get("expires_at"),
        "nonce": fingerprint("nonce"),
        "signature": fingerprint("signature"),
        "public_key": fingerprint("public_key"),
        "redacted": True,
    }


def public_summary(summary: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(summary)

    def sanitize(item: Any) -> Any:
        if isinstance(item, dict):
            return {
                key: _public_warrant(nested)
                if key == "warrant" and isinstance(nested, dict)
                else sanitize(nested)
                for key, nested in item.items()
            }
        if isinstance(item, list):
            return [sanitize(nested) for nested in item]
        if isinstance(item, tuple):
            return [sanitize(nested) for nested in item]
        return item

    sanitized = sanitize(value)
    if not isinstance(sanitized, dict):
        raise TypeError("PUBLIC_SUMMARY_INVALID")
    return sanitized


def remember_session(summary: dict[str, Any]) -> None:
    session_id = str(summary["session_id"])
    SESSION_SUMMARIES[session_id] = summary
    EVENT_STREAMS[session_id] = list(summary["events"])
    while len(SESSION_SUMMARIES) > max(1, MAX_CACHED_SESSIONS):
        oldest = next(iter(SESSION_SUMMARIES))
        SESSION_SUMMARIES.pop(oldest, None)
        EVENT_STREAMS.pop(oldest, None)


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
async def preflight(
    x_afterimage_operator_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_operator_token(x_afterimage_operator_token)
    gateway: Any | None = None
    try:
        gateway = build_alpaca_gateway()
        await gateway.connect()
        checked = await gateway.preflight(expected_account_id_hash())
        return checked.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(409, public_error_detail(exc)) from exc
    finally:
        if gateway is not None:
            await gateway.close()


@router.post("/api/shadow")
async def shadow(
    request: ShadowRequest,
    x_afterimage_operator_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_operator_token(x_afterimage_operator_token)
    gateway: Any | None = None
    try:
        gateway = build_alpaca_gateway()
        await gateway.connect()
        summary = await coordinator.run_live_shadow(
            gateway,
            AgentDesk(load_featherless_gateway()),
            expected_account_id_hash(),
            symbol=request.symbol.upper() if request.symbol is not None else None,
            strategy_id=request.strategy_id,
        )
        remember_session(summary)
        return public_summary(summary)
    except Exception as exc:
        raise HTTPException(409, public_error_detail(exc)) from exc
    finally:
        if gateway is not None:
            await gateway.close()


@router.post("/api/replays")
def replay(
    request: ReplayRequest,
    x_afterimage_operator_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_operator_token(x_afterimage_operator_token)
    if request.fixture not in {"accepted", "rejected"}:
        raise HTTPException(400, "fixture must be accepted or rejected")
    summary = coordinator.run_demo(accepted=request.fixture == "accepted")
    remember_session(summary)
    return public_summary(summary)


@router.get("/api/sessions/{session_id}")
def session(
    session_id: str,
    x_afterimage_operator_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_operator_token(x_afterimage_operator_token)
    if session_id in SESSION_SUMMARIES:
        return public_summary(SESSION_SUMMARIES[session_id])
    stored = coordinator.repository.get_session(session_id)
    if stored is None:
        raise HTTPException(404, "session not found")
    return public_summary(stored)


@router.get("/api/sessions/{session_id}/events")
def events(
    session_id: str,
    x_afterimage_operator_token: str | None = Header(default=None),
) -> list[dict[str, Any]]:
    require_operator_token(x_afterimage_operator_token)
    return EVENT_STREAMS.get(session_id, [])


@router.get("/api/sessions/{session_id}/artifacts")
def artifacts(
    session_id: str,
    x_afterimage_operator_token: str | None = Header(default=None),
) -> list[dict[str, Any]]:
    require_operator_token(x_afterimage_operator_token)
    return redact_artifacts(coordinator.repository.session_artifacts(session_id))


@router.post("/api/risk/{session_id}")
def risk(
    session_id: str,
    x_afterimage_operator_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_operator_token(x_afterimage_operator_token)
    summary = SESSION_SUMMARIES.get(session_id)
    if summary is None or "risk" not in summary:
        raise HTTPException(404, "persisted risk decision not found")
    return {"risk": summary["risk"], "payoff": summary.get("payoff")}


@router.post("/api/execute/{session_id}")
async def execute(
    session_id: str,
    request: ExecuteRequest,
    x_afterimage_execution_token: str | None = Header(default=None),
    x_afterimage_operator_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_operator_token(x_afterimage_operator_token)
    if os.getenv("AFTERIMAGE_ENABLE_PAPER_EXECUTION", "false").lower() != "true":
        raise HTTPException(403, "paper execution is disabled")
    require_execution_token(x_afterimage_execution_token)
    payload = coordinator.repository.warrant_by_id(request.warrant_id)
    if payload is None:
        raise HTTPException(404, "warrant not found")
    warrant = ExecutionWarrant.model_validate(payload)
    gateway: Any | None = None
    try:
        gateway = build_alpaca_gateway()
        await gateway.connect()
        checked = await gateway.preflight(expected_account_id_hash())
        if checked.account.account_id_hash != warrant.intent.account_id_hash:
            raise HTTPException(409, "warrant is bound to a different account")
        return await coordinator.submit_shadow_session(
            gateway, expected_account_id_hash(), session_id, warrant
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(409, public_error_detail(exc)) from exc
    finally:
        if gateway is not None:
            await gateway.close()


@router.post("/api/reconcile/{session_id}")
async def reconcile(
    session_id: str,
    x_afterimage_operator_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_operator_token(x_afterimage_operator_token)
    local_orders = coordinator.repository.broker_orders(session_id)
    if not local_orders:
        raise HTTPException(404, "no submitted order exists for this session")
    client_order_id = str(local_orders[-1]["client_order_id"])
    gateway: Any | None = None
    try:
        gateway = build_alpaca_gateway()
        await gateway.connect()
        await gateway.preflight(expected_account_id_hash())
        return (await Reconciler(gateway).by_client_id(client_order_id)).__dict__
    except Exception as exc:
        raise HTTPException(409, public_error_detail(exc)) from exc
    finally:
        if gateway is not None:
            await gateway.close()


@router.post("/api/manage/{session_id}")
async def manage(
    session_id: str,
    x_afterimage_execution_token: str | None = Header(default=None),
    x_afterimage_operator_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_operator_token(x_afterimage_operator_token)
    if os.getenv("AFTERIMAGE_ENABLE_PAPER_EXECUTION", "false").lower() != "true":
        raise HTTPException(403, "paper execution is disabled")
    require_execution_token(x_afterimage_execution_token)
    gateway: Any | None = None
    try:
        gateway = build_alpaca_gateway()
        await gateway.connect()
        summary = await coordinator.manage_live_position(
            gateway, expected_account_id_hash(), session_id
        )
        remember_session(summary)
        return public_summary(summary)
    except Exception as exc:
        raise HTTPException(409, public_error_detail(exc)) from exc
    finally:
        if gateway is not None:
            await gateway.close()


@router.get("/api/stream/{session_id}")
def stream(
    session_id: str,
    last_event_id: int | None = Header(default=None),
    x_afterimage_operator_token: str | None = Header(default=None),
) -> EventSourceResponse:
    require_operator_token(x_afterimage_operator_token)
    return EventSourceResponse(stream_session(session_id, last_event_id or 0))
