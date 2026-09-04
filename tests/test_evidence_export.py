from __future__ import annotations

from pathlib import Path

from afterimage.evidence.export import evidence_core, evidence_core_hash
from afterimage.orchestration.coordinator import Coordinator
from afterimage.storage import Database


def _summary(root: Path, name: str) -> dict[str, object]:
    coordinator = Coordinator(
        Database(f"sqlite:///{root / f'{name}.db'}"),
        signing_key_path=root / f"{name}.pem",
    )
    return coordinator.run_demo(accepted=True)


def test_evidence_core_digest_is_stable_across_identical_runs(tmp_path: Path) -> None:
    first = _summary(tmp_path, "first")
    second = _summary(tmp_path, "second")

    assert first["session_id"] != second["session_id"]
    assert evidence_core_hash(first) == evidence_core_hash(second)
    assert "session_id" not in evidence_core(first)
    assert "warrant" not in evidence_core(first)
