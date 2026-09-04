from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiments.strategy_candidates.mean_reversion.ledger import freeze_attempt


def test_freeze_attempt_copies_complete_artifacts_and_refuses_overwrite(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "results.json").write_text('{"oos":{"sample_size":3}}\n')
    (source / "report.md").write_text("# report\n")
    (source / "order_dry_run.json").write_text('{"submission_allowed":false}\n')

    record = freeze_attempt(
        source,
        tmp_path / "attempts",
        "001_example",
        {"status": "failed", "reason": "negative OOS"},
    )

    assert record["attempt_id"] == "001_example"
    assert set(record["artifacts"]) == {
        "order_dry_run.json",
        "report.md",
        "results.json",
    }
    assert json.loads((tmp_path / "attempts/ledger.json").read_text())["attempts"] == [record]
    with pytest.raises(FileExistsError):
        freeze_attempt(source, tmp_path / "attempts", "001_example", {})
