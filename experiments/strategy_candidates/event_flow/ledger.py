"""Small append-only, hash-chained experiment ledger."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def _digest(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def verify_ledger(path: Path) -> bool:
    if not path.exists():
        return True
    payload = json.loads(path.read_text(encoding="utf-8"))
    previous = "GENESIS"
    for entry in payload.get("attempts", []):
        claimed = entry.get("entry_hash")
        unsigned = {key: value for key, value in entry.items() if key != "entry_hash"}
        if unsigned.get("previous_hash") != previous or claimed != _digest(unsigned):
            return False
        previous = claimed
    return payload.get("head_hash", "GENESIS") == previous


def append_attempt(path: Path, entry: Mapping[str, Any]) -> None:
    if not verify_ledger(path):
        raise ValueError("LEDGER_HASH_INVALID")
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        payload = {
            "schema_version": "afterimage-event-flow-ledger-v1",
            "attempts": [],
            "head_hash": "GENESIS",
        }
    if any(item.get("attempt_id") == entry.get("attempt_id") for item in payload["attempts"]):
        raise ValueError("ATTEMPT_ID_ALREADY_EXISTS")
    unsigned = {**entry, "previous_hash": payload["head_hash"]}
    signed = {**unsigned, "entry_hash": _digest(unsigned)}
    payload["attempts"].append(signed)
    payload["head_hash"] = signed["entry_hash"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
