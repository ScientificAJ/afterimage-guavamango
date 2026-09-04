from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentRole(StrEnum):
    STRATEGIST = "strategist"
    REGIME_WITNESS = "regime_witness"
    OPTIONS_WITNESS = "options_witness"
    PROSECUTOR = "prosecutor"


class AgentFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    claim: str
    evidence_keys: tuple[str, ...]
    severity: Literal["support", "warning", "fatal"]
    basis: Literal["observation", "inference"] = "observation"


class AgentReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    role: AgentRole
    status: Literal["support", "challenge", "abstain"]
    thesis: str
    findings: tuple[AgentFinding, ...]
    falsifiers: tuple[str, ...]
    reason_code: str
    model_id: str
    prompt_version: str = "unversioned"
    prompt_hash: str
    input_packet_hash: str = "unbound"
    response_hash: str
    response_preimage: dict[str, Any] | None = None
    provider_request_id: str | None = None
    provider_created_at: int | None = None
    provider_system_fingerprint: str | None = None
    latency_ms: int = Field(ge=0)


class DeskReports(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    strategist: AgentReport
    regime_witness: AgentReport
    options_witness: AgentReport
    prosecutor: AgentReport
