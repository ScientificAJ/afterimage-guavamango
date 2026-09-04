from __future__ import annotations

import json

import pytest

from experiments.strategy_candidates.event_flow.ledger import append_attempt, verify_ledger


def test_ledger_is_append_only_and_hash_chained(tmp_path) -> None:
    path = tmp_path / "attempt-ledger.json"
    append_attempt(path, {"attempt_id": "a1", "decision": "REJECT"})
    append_attempt(path, {"attempt_id": "a2", "decision": "ADMIT"})

    payload = json.loads(path.read_text())
    assert len(payload["attempts"]) == 2
    assert payload["attempts"][1]["previous_hash"] == payload["attempts"][0]["entry_hash"]
    assert verify_ledger(path)

    payload["attempts"][0]["decision"] = "ADMIT"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="HASH"):
        append_attempt(path, {"attempt_id": "a3", "decision": "REJECT"})
