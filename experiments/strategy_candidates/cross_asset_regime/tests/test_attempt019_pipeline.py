from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from experiments.strategy_candidates.cross_asset_regime.run_attempt019_history_exhaustion import (
    HERE,
    validate_audit,
)


def test_attempt019_audit_is_frozen_before_full_history_acquisition() -> None:
    path = HERE / "results" / "attempt019_frozen_audit.json"
    audit = json.loads(path.read_text(encoding="utf-8"))
    validate_audit(audit)
    assert audit["requested_history"]["start"] == "2000-01-01"
    assert audit["requested_history"]["end_exclusive"] == "2021-01-01"
    assert audit["source_rule"]["changes_from_frozen_rule"] == "none"


def test_attempt019_audit_hash_rejects_post_freeze_mutation() -> None:
    audit = json.loads(
        (HERE / "results" / "attempt019_frozen_audit.json").read_text(encoding="utf-8")
    )
    changed = copy.deepcopy(audit)
    changed["evaluation"]["stress_cost_multiplier"] = "1.4"
    with pytest.raises(ValueError, match="AUDIT_HASH_MISMATCH"):
        validate_audit(changed, verify_sources=False)


def test_attempt019_does_not_modify_attempts_001_007_snapshot() -> None:
    snapshot = json.loads(
        (HERE / "results" / "attempts_001_007_snapshot.json").read_text(encoding="utf-8")
    )
    body = {
        key: value
        for key, value in snapshot.items()
        if key not in {"snapshot_hash", "snapshot_hash_scope"}
    }
    from experiments.strategy_candidates.cross_asset_regime.run_research import canonical_hash

    assert canonical_hash(body) == snapshot["snapshot_hash"]


def test_attempt019_result_forbids_production_integration() -> None:
    result_path = HERE / "results" / "attempt019_history_exhaustion.json"
    if not result_path.exists():
        pytest.skip("result is produced by the authenticated audit run")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    contract = result["production_integration_contract"]
    assert contract["status"] == "NONE_NOT_ADMITTED"
    assert contract["orders_submitted"] is False
    assert all(contract[key] is None for key in ("signal_module", "scheduler", "risk_allocation", "order_route"))
