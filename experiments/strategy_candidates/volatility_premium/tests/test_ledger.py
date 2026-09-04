from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ledger import append_attempt, verify_ledger

SUMMARY = {
    "verdict": "rejected",
    "expectancy_r": "-0.047",
    "operational_target_stop": "0.3333333333",
    "profit_factor": "0.25",
}


def test_attempt_ledger_chains_entries_without_rewriting_the_first() -> None:
    first = append_attempt(
        None,
        attempt_id="attempt-01",
        artifact_path="results/attempt-01.json",
        artifact_sha256="a" * 64,
        summary=SUMMARY,
    )
    original_entry = deepcopy(first["entries"][0])

    second = append_attempt(
        first,
        attempt_id="attempt-02",
        artifact_path="results/attempt-02.json",
        artifact_sha256="b" * 64,
        summary={**SUMMARY, "expectancy_r": "0.02"},
    )

    assert second["entries"][0] == original_entry
    assert second["entries"][1]["previous_entry_hash"] == original_entry["entry_hash"]
    assert second["entries"][1]["operational_target_stop"] == "0.3333333333"
    assert second["entries"][1]["profit_factor"] == "0.25"
    assert verify_ledger(second)


def test_attempt_ledger_rejects_duplicate_id_and_artifact_path() -> None:
    first = append_attempt(
        None,
        attempt_id="attempt-01",
        artifact_path="results/attempt-01.json",
        artifact_sha256="a" * 64,
        summary=SUMMARY,
    )

    with pytest.raises(ValueError, match="ATTEMPT_ALREADY_RECORDED"):
        append_attempt(
            first,
            attempt_id="attempt-01",
            artifact_path="results/attempt-02.json",
            artifact_sha256="b" * 64,
            summary=SUMMARY,
        )
    with pytest.raises(ValueError, match="ARTIFACT_ALREADY_RECORDED"):
        append_attempt(
            first,
            attempt_id="attempt-02",
            artifact_path="results/attempt-01.json",
            artifact_sha256="b" * 64,
            summary=SUMMARY,
        )


def test_ledger_verification_detects_summary_tampering() -> None:
    ledger = append_attempt(
        None,
        attempt_id="attempt-01",
        artifact_path="results/attempt-01.json",
        artifact_sha256="a" * 64,
        summary=SUMMARY,
    )
    ledger["entries"][0]["profit_factor"] = "9"

    assert not verify_ledger(ledger)
