from __future__ import annotations

from typing import Any

from afterimage.contracts.hashing import canonical_sha256


def _selected(value: object, keys: tuple[str, ...]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {key: value[key] for key in keys if key in value}


def evidence_core(summary: dict[str, Any]) -> dict[str, Any]:
    """Return reproducible evidence, excluding UUIDs, timestamps, signatures, and audit rows."""
    snapshot = _selected(
        summary.get("snapshot"),
        ("snapshot_id", "cutoff", "identity", "features", "records", "provenance"),
    )
    candidate = _selected(
        summary.get("candidate"),
        (
            "identity",
            "snapshot_id",
            "symbol",
            "direction",
            "signal_at",
            "features",
            "permitted_structures",
        ),
    )
    risk = _selected(
        summary.get("risk"),
        (
            "status",
            "gates",
            "quantity",
            "modeled_max_loss",
            "strategy_manifest_hash",
            "evidence_commit_hash",
            "quote_hash",
        ),
    )
    tournament = _selected(
        summary.get("tournament"),
        (
            "entries",
            "champion",
            "champion_manifest_hash",
            "result_provenance",
        ),
    )
    core = {
        "schema": "afterimage-evidence-core-v1",
        "mode": summary.get("mode"),
        "config_manifest_hash": summary.get("config_manifest_hash"),
        "snapshot": snapshot,
        "candidate": candidate,
        "agents": summary.get("agents"),
        "agent_provenance": summary.get("agent_provenance"),
        "dataset_hash": summary.get("dataset_hash"),
        "evidence": summary.get("evidence"),
        "evidence_paths": summary.get("evidence_paths"),
        "payoff": summary.get("payoff"),
        "exit_plan": summary.get("exit_plan"),
        "watchdog": summary.get("watchdog"),
        "risk": risk,
        "option_replay": summary.get("option_replay"),
        "tournament": tournament,
    }
    return {key: value for key, value in core.items() if value is not None}


def evidence_core_hash(summary: dict[str, Any]) -> str:
    return canonical_sha256(evidence_core(summary))
