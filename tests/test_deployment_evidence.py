from __future__ import annotations

import json
from pathlib import Path

import pytest

from afterimage.contracts.hashing import canonical_sha256
from afterimage.orchestration.coordinator import Coordinator
from afterimage.storage import Database
from afterimage.strategies.deployment import (
    DeploymentEvidenceError,
    load_deployment_evidence,
)


def write_bundle(root: Path) -> Path:
    result = {
        "result_hash": "research-result-v1",
        "admission": {"admitted": True, "checks": {"pf": True, "stress": True}},
    }
    result_path = root / "result.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    manifest = {
        "schema_version": "afterimage-deployment-evidence-v1",
        "strategy_id": "winner_v1",
        "strategy_version": "1.0.0",
        "strategy_authority_hash": "a" * 64,
        "strategy_config_hash": "b" * 64,
        "strategy_source_hash": "c" * 64,
        "result_path": "result.json",
        "result_content_hash": canonical_sha256(result),
        "research_result_hash": "research-result-v1",
        "admitted": True,
        "required_gates": {"pf": True, "stress": True},
        "metrics": {
            "sample_count": 95,
            "profit_factor": "2.25",
            "expectancy_r": "0.50",
            "max_drawdown_r": "4.75",
            "positive_month_fraction": "0.72",
            "positive_underlyings": 8,
            "stress_profit_factor": "2.22",
            "neighbor_positive_fraction": "1.0",
            "minimum_target_to_stop": "3.0",
        },
        "limitations": ["pseudo-OOS, not a guaranteed return"],
    }
    manifest["manifest_hash"] = canonical_sha256(manifest)
    path = root / "deployment.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_deployment_evidence_binds_exact_strategy_result_and_every_gate(
    tmp_path: Path,
) -> None:
    decision, manifest = load_deployment_evidence(
        write_bundle(tmp_path),
        strategy_id="winner_v1",
        strategy_version="1.0.0",
        strategy_authority_hash="a" * 64,
        strategy_config_hash="b" * 64,
        strategy_source_hash="c" * 64,
    )

    assert decision.status == "PASS"
    assert decision.metrics.profit_factor == 2.25
    assert decision.commit_hash == manifest.manifest_hash
    assert decision.result_hash == "research-result-v1"


def test_deployment_evidence_fails_when_result_or_gate_is_changed(tmp_path: Path) -> None:
    path = write_bundle(tmp_path)
    (tmp_path / "result.json").write_text('{"changed":true}', encoding="utf-8")

    with pytest.raises(DeploymentEvidenceError, match="RESULT_CONTENT_HASH_MISMATCH"):
        load_deployment_evidence(
            path,
            strategy_id="winner_v1",
            strategy_version="1.0.0",
            strategy_authority_hash="a" * 64,
            strategy_config_hash="b" * 64,
            strategy_source_hash="c" * 64,
        )


def test_deployment_evidence_rejects_a_changed_plugin_implementation(tmp_path: Path) -> None:
    with pytest.raises(DeploymentEvidenceError, match="DEPLOYMENT_STRATEGY_BINDING_MISMATCH"):
        load_deployment_evidence(
            write_bundle(tmp_path),
            strategy_id="winner_v1",
            strategy_version="1.0.0",
            strategy_authority_hash="a" * 64,
            strategy_config_hash="b" * 64,
            strategy_source_hash="changed",
        )


def test_deployment_agent_packet_exposes_admitted_metrics_and_exact_rule(tmp_path: Path) -> None:
    runtime = Coordinator(
        Database(f"sqlite:///{tmp_path / 'deployment-agent-packet.db'}"),
        signing_key_path=tmp_path / "warrant.pem",
    )
    strategy, _ = runtime.resolve_strategy("shadow_clock_shock_reversal_v1")
    _, manifest = runtime._deployment_evidence(strategy)
    configured = runtime.config.strategy(strategy.identity.strategy_id).payload

    packet = runtime._deployment_agent_packet(manifest, configured)

    assert packet["protocol"] == "hash-bound-deployment-evidence-v1"
    assert packet["aggregate_research_metrics_visible"] is True
    assert packet["individual_outcomes_visible"] is False
    assert packet["deployment_evidence"]["admitted"] is True
    assert packet["deployment_evidence"]["metrics"]["sample_count"] == 95
    assert (
        packet["deployment_evidence"]["metrics"]["profit_factor"] == "2.252990790803920449771526138"
    )
    assert packet["strategy_contract"]["signal"]["cross_section"] == (
        "most_negative_normalized_shock"
    )
    assert packet["strategy_contract"]["execution"]["timing"] == ("next_regular_session_open")
    assert packet["strategy_contract"]["shadow_clock"]["skipped_signals_consume_clock"] is True
    assert packet["deployment_evidence"]["limitations"]
