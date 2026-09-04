from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping


ARTIFACTS = ("results.json", "report.md", "order_dry_run.json")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_attempt(
    source: Path,
    attempts_root: Path,
    attempt_id: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Copy a complete result set once and append its hashes to the attempt ledger."""
    target = attempts_root / attempt_id
    if target.exists():
        raise FileExistsError(f"attempt already frozen: {attempt_id}")
    missing = [name for name in ARTIFACTS if not (source / name).is_file()]
    if missing:
        raise FileNotFoundError(f"missing attempt artifacts: {', '.join(missing)}")

    target.mkdir(parents=True)
    artifact_hashes: dict[str, str] = {}
    for name in ARTIFACTS:
        destination = target / name
        shutil.copy2(source / name, destination)
        artifact_hashes[name] = _digest(destination)

    record = {
        "attempt_id": attempt_id,
        "frozen_at": datetime.now(UTC).isoformat(),
        "artifacts": artifact_hashes,
        **dict(metadata),
    }
    ledger_path = attempts_root / "ledger.json"
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    else:
        ledger = {"schema_version": 1, "attempts": []}
    ledger["attempts"].append(record)
    temporary = ledger_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(ledger_path)
    return record
