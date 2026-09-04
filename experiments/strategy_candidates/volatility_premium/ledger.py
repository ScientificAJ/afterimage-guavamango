"""Append-only, hash-chained research-attempt ledger."""

from __future__ import annotations

import json
from typing import Any

from acquire import canonical_hash

REQUIRED_SUMMARY_FIELDS = frozenset(
    {"verdict", "expectancy_r", "operational_target_stop", "profit_factor"}
)


def append_attempt(
    ledger: dict[str, Any] | None,
    *,
    attempt_id: str,
    artifact_path: str,
    artifact_sha256: str,
    summary: dict[str, Any],
) -> dict[str, Any]:
    if not REQUIRED_SUMMARY_FIELDS.issubset(summary):
        raise ValueError("ATTEMPT_SUMMARY_FIELDS_REQUIRED")
    if len(artifact_sha256) != 64:
        raise ValueError("ARTIFACT_SHA256_REQUIRED")
    current = (
        json.loads(json.dumps(ledger))
        if ledger is not None
        else {"schema_version": "afterimage-attempt-ledger-v1", "entries": []}
    )
    entries = current.get("entries")
    if not isinstance(entries, list):
        raise TypeError("ATTEMPT_LEDGER_ENTRIES_REQUIRED")
    if any(item.get("attempt_id") == attempt_id for item in entries):
        raise ValueError("ATTEMPT_ALREADY_RECORDED")
    if any(item.get("artifact_path") == artifact_path for item in entries):
        raise ValueError("ARTIFACT_ALREADY_RECORDED")
    previous_hash = entries[-1]["entry_hash"] if entries else "GENESIS"
    entry_body = {
        "attempt_id": attempt_id,
        "artifact_path": artifact_path,
        "artifact_sha256": artifact_sha256,
        "previous_entry_hash": previous_hash,
        **summary,
    }
    entries.append({**entry_body, "entry_hash": canonical_hash(entry_body)})
    body = {"schema_version": current["schema_version"], "entries": entries}
    return {**body, "ledger_hash": canonical_hash(body)}


def verify_ledger(ledger: dict[str, Any]) -> bool:
    try:
        if ledger.get("schema_version") != "afterimage-attempt-ledger-v1":
            return False
        entries = ledger["entries"]
        if not isinstance(entries, list):
            return False
        previous_hash = "GENESIS"
        for entry in entries:
            if entry.get("previous_entry_hash") != previous_hash:
                return False
            body = {key: value for key, value in entry.items() if key != "entry_hash"}
            if canonical_hash(body) != entry.get("entry_hash"):
                return False
            previous_hash = entry["entry_hash"]
        ledger_body = {
            "schema_version": ledger["schema_version"],
            "entries": entries,
        }
        return canonical_hash(ledger_body) == ledger.get("ledger_hash")
    except (KeyError, TypeError, ValueError):
        return False
