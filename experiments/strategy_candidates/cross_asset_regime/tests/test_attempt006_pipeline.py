from __future__ import annotations

import copy

import pytest

from experiments.strategy_candidates.cross_asset_regime.run_qqq_regime_extension import validate_family
from experiments.strategy_candidates.cross_asset_regime.run_research import canonical_hash


def test_attempt006_family_hash_rejects_mutation() -> None:
    artifact = {
        "schema_version": "afterimage-qqq-regime-frozen-family-v1",
        "focal_variant": "x",
        "rules": {"breadth_required": 5},
    }
    artifact["family_hash"] = canonical_hash(artifact)
    validate_family(artifact)
    changed = copy.deepcopy(artifact)
    changed["rules"]["breadth_required"] = 4
    with pytest.raises(ValueError, match="HASH"):
        validate_family(changed)
