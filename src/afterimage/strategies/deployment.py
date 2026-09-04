from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from afterimage.contracts.enums import DecisionStatus
from afterimage.contracts.hashing import canonical_sha256


class DeploymentEvidenceError(RuntimeError):
    pass


class DeploymentMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sample_count: int = Field(ge=1)
    profit_factor: Decimal
    expectancy_r: Decimal
    max_drawdown_r: Decimal
    positive_month_fraction: Decimal
    positive_underlyings: int = Field(ge=1)
    stress_profit_factor: Decimal
    neighbor_positive_fraction: Decimal
    minimum_target_to_stop: Decimal


class DeploymentManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    strategy_id: str
    strategy_version: str
    strategy_authority_hash: str
    strategy_config_hash: str
    strategy_source_hash: str
    result_path: str
    result_content_hash: str
    research_result_hash: str
    admitted: bool
    required_gates: dict[str, bool]
    metrics: DeploymentMetrics
    limitations: tuple[str, ...]
    manifest_hash: str


class DeploymentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: DecisionStatus
    metrics: DeploymentMetrics
    reasons: tuple[str, ...]
    commit_hash: str
    result_hash: str


def load_deployment_evidence(
    path: str | Path,
    *,
    strategy_id: str,
    strategy_version: str,
    strategy_authority_hash: str,
    strategy_config_hash: str,
    strategy_source_hash: str,
) -> tuple[DeploymentDecision, DeploymentManifest]:
    manifest_path = Path(path).resolve()
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeploymentEvidenceError("DEPLOYMENT_MANIFEST_UNAVAILABLE") from exc
    if not isinstance(raw, dict):
        raise DeploymentEvidenceError("DEPLOYMENT_MANIFEST_MALFORMED")
    claimed_hash = str(raw.get("manifest_hash", ""))
    core = {key: value for key, value in raw.items() if key != "manifest_hash"}
    if not claimed_hash or canonical_sha256(core) != claimed_hash:
        raise DeploymentEvidenceError("DEPLOYMENT_MANIFEST_HASH_MISMATCH")
    try:
        manifest = DeploymentManifest.model_validate(raw)
    except ValueError as exc:
        raise DeploymentEvidenceError("DEPLOYMENT_MANIFEST_MALFORMED") from exc
    expected = (
        manifest.strategy_id == strategy_id,
        manifest.strategy_version == strategy_version,
        manifest.strategy_authority_hash == strategy_authority_hash,
        manifest.strategy_config_hash == strategy_config_hash,
        manifest.strategy_source_hash == strategy_source_hash,
    )
    if not all(expected):
        raise DeploymentEvidenceError("DEPLOYMENT_STRATEGY_BINDING_MISMATCH")
    if manifest.schema_version != "afterimage-deployment-evidence-v1":
        raise DeploymentEvidenceError("DEPLOYMENT_SCHEMA_UNSUPPORTED")
    if (
        not manifest.admitted
        or not manifest.required_gates
        or not all(manifest.required_gates.values())
    ):
        raise DeploymentEvidenceError("DEPLOYMENT_GATES_REJECTED")
    result_path = (manifest_path.parent / manifest.result_path).resolve()
    if manifest_path.parent not in result_path.parents:
        raise DeploymentEvidenceError("RESULT_PATH_OUTSIDE_MANIFEST_ROOT")
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeploymentEvidenceError("RESULT_UNAVAILABLE") from exc
    if canonical_sha256(result) != manifest.result_content_hash:
        raise DeploymentEvidenceError("RESULT_CONTENT_HASH_MISMATCH")
    if not isinstance(result, dict) or result.get("result_hash") != manifest.research_result_hash:
        raise DeploymentEvidenceError("RESEARCH_RESULT_HASH_MISMATCH")
    return (
        DeploymentDecision(
            status=DecisionStatus.PASS,
            metrics=manifest.metrics,
            reasons=(),
            commit_hash=manifest.manifest_hash,
            result_hash=manifest.research_result_hash,
        ),
        manifest,
    )
