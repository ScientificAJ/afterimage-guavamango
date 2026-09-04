from __future__ import annotations

import copy

import pytest

from experiments.strategy_candidates.cross_asset_regime.validate_frozen_extension import validate_frozen_rule


def test_frozen_rule_hash_detects_any_parameter_mutation() -> None:
    artifact = {
        "schema_version": "afterimage-equity-gap-frozen-rule-v1",
        "frozen_at": "2026-09-04T16:44:27+05:30",
        "selected_variant": "equity_gap_b4_m10_s15",
        "evidence_seen_through": "2026-09-03",
        "fresh_backward_extension": {"start": "2025-01-02", "end": "2025-12-31", "previously_used": False},
        "rule": {"breadth_required": 4},
    }
    from experiments.strategy_candidates.cross_asset_regime.run_research import canonical_hash
    artifact["rule_hash"] = canonical_hash(artifact)
    validate_frozen_rule(artifact)
    changed = copy.deepcopy(artifact)
    changed["rule"]["breadth_required"] = 5
    with pytest.raises(ValueError, match="HASH"):
        validate_frozen_rule(changed)
