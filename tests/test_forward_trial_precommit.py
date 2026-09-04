from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from afterimage.research.precommit import (
    build_forward_trial_precommit,
    source_and_configuration_commitment,
    verify_forward_trial_precommit,
)


def fixture_tree(root: Path) -> None:
    source = root / "src" / "afterimage"
    strategy = root / "configs" / "strategies"
    risk = root / "configs" / "risk"
    source.mkdir(parents=True)
    strategy.mkdir(parents=True)
    risk.mkdir(parents=True)
    (source / "agent.py").write_text("PAPER_ONLY = True\n")
    (strategy / "opening_range_failure_v1.yaml").write_text("id: strategy\n")
    (risk / "hackathon-v1.yaml").write_text("id: risk\n")


def test_forward_trial_precommit_is_self_verifying_and_tree_bound(tmp_path: Path) -> None:
    fixture_tree(tmp_path)
    created = datetime(2026, 9, 4, 9, 0, tzinfo=UTC)
    starts = datetime(2026, 9, 4, 13, 30, tzinfo=UTC)
    signal_cutoff = datetime(2026, 9, 4, 13, 55, tzinfo=UTC)
    forced_exit = datetime(2026, 9, 4, 14, 45, tzinfo=UTC)

    precommit = build_forward_trial_precommit(
        root=tmp_path,
        created_at=created,
        starts_at=starts,
        signal_cutoff_at=signal_cutoff,
        forced_exit_at=forced_exit,
        research_dataset_sha256="d" * 64,
        supersedes="forward-paper-trial-v1.json",
    )
    verified = verify_forward_trial_precommit(
        precommit,
        root=tmp_path,
        research_dataset_sha256="d" * 64,
        observed_at=created,
    )

    assert verified["valid"] is True
    assert verified["tree_matches"] is True
    assert precommit["tracked_file_count"] == 3
    assert len(precommit["precommit_sha256"]) == 64

    (tmp_path / "src" / "afterimage" / "agent.py").write_text("PAPER_ONLY = False\n")
    tampered = verify_forward_trial_precommit(
        precommit,
        root=tmp_path,
        research_dataset_sha256="d" * 64,
        observed_at=created,
    )
    assert tampered["valid"] is False
    assert tampered["tree_matches"] is False


def test_tree_commitment_is_path_and_content_stable(tmp_path: Path) -> None:
    fixture_tree(tmp_path)

    first = source_and_configuration_commitment(tmp_path)
    second = source_and_configuration_commitment(tmp_path)

    assert first == second
    assert first["algorithm"] == "sha256(path-nul-file-sha256-newline)-v1"
