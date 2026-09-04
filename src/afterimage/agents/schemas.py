from __future__ import annotations

from enum import StrEnum
from typing import Literal

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


class AgentReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    role: AgentRole
    status: Literal["support", "challenge", "abstain"]
    thesis: str
    findings: tuple[AgentFinding, ...]
    falsifiers: tuple[str, ...]
    reason_code: str
    model_id: str
    prompt_hash: str
    response_hash: str
    latency_ms: int = Field(ge=0)


class DeskReports(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    strategist: AgentReport
    regime_witness: AgentReport
    options_witness: AgentReport
    prosecutor: AgentReport
