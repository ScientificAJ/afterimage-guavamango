from __future__ import annotations

import copy

import pytest

from experiments.strategy_candidates.cross_asset_regime.run_attempt007_validation import validate_rule
from experiments.strategy_candidates.cross_asset_regime.run_research import canonical_hash


def test_attempt007_rule_hash_rejects_mutation() -> None:
    artifact = {
        "schema_version": "afterimage-attempt007-frozen-rule-v1",
        "selected_variant": "x",
        "rule": {"sector_confirmations": 3},
    }
    artifact["rule_hash"] = canonical_hash(artifact)
    validate_rule(artifact, verify_sources=False)
    changed = copy.deepcopy(artifact)
    changed["rule"]["sector_confirmations"] = 2
    with pytest.raises(ValueError, match="HASH"):
        validate_rule(changed, verify_sources=False)
