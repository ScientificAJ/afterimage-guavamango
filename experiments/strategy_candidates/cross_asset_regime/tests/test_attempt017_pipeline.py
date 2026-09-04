from __future__ import annotations
import copy
import pytest
from experiments.strategy_candidates.cross_asset_regime.run_attempt017_validation import validate_rule
from experiments.strategy_candidates.cross_asset_regime.run_research import canonical_hash
def test_attempt017_frozen_hash_rejects_mutation():
    a={'schema_version':'x','selected_variant':'x','rule':{'breadth_required':6}};a['rule_hash']=canonical_hash(a);validate_rule(a,verify_sources=False);b=copy.deepcopy(a);b['rule']['breadth_required']=5
    with pytest.raises(ValueError,match='HASH'):validate_rule(b,verify_sources=False)
