from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

from afterimage.contracts.hashing import canonical_sha256

TRACKED_GLOBS = ("src/afterimage/**/*.py", "configs/**/*.yaml")


def _file_sha256(path: Path) -> str:
    metadata = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"PRECOMMIT_TRACKED_FILE_INVALID:{path.as_posix()}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_and_configuration_commitment(root: Path) -> dict[str, Any]:
    files = sorted(
        {
            path
            for pattern in TRACKED_GLOBS
            for path in root.glob(pattern)
            if "__pycache__" not in path.parts
        },
        key=lambda path: path.relative_to(root).as_posix(),
    )
    entries = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": _file_sha256(path),
        }
        for path in files
    ]
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(str(entry["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(entry["sha256"]).encode("ascii"))
        digest.update(b"\n")
    return {
        "algorithm": "sha256(path-nul-file-sha256-newline)-v1",
        "tree_sha256": digest.hexdigest(),
        "tracked_file_count": len(entries),
        "tracked_files": entries,
    }


def build_forward_trial_precommit(
    *,
    root: Path,
    created_at: datetime,
    starts_at: datetime,
    signal_cutoff_at: datetime,
    forced_exit_at: datetime,
    research_dataset_sha256: str,
    supersedes: str | None = None,
) -> dict[str, Any]:
    if not created_at < starts_at < signal_cutoff_at < forced_exit_at:
        raise ValueError("FORWARD_TRIAL_WINDOW_INVALID")
    if len(research_dataset_sha256) != 64:
        raise ValueError("FORWARD_TRIAL_DATASET_HASH_INVALID")
    strategy_path = root / "configs/strategies/opening_range_failure_v1.yaml"
    risk_path = root / "configs/risk/hackathon-v1.yaml"
    commitment = source_and_configuration_commitment(root)
    draft: dict[str, Any] = {
        "schema": "afterimage-forward-paper-trial-v2",
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "status": "precommitted-before-market-open",
        "supersedes": supersedes,
        "supersession_reason": (
            "Pre-market security hardening changed the tracked source tree; no market order "
            "or position existed under the superseded trial."
            if supersedes
            else None
        ),
        "account_scope": (
            "locally-bound Alpaca paper account; identifier hash withheld from public artifact"
        ),
        "broker_transport": (
            "official Alpaca CLI 0.0.14 over a frozen OAuth profile and positively attested "
            "paper endpoint"
        ),
        "symbol": "SPY",
        "strategy": {
            "id": "opening_range_failure_v1",
            "version": "1.0.0",
            "configuration_sha256": _file_sha256(strategy_path),
        },
        "risk_policy": {
            "id": "hackathon-v1",
            "configuration_sha256": _file_sha256(risk_path),
            "maximum_modeled_loss_dollars": "500",
            "minimum_operational_reward_risk": "3.0",
        },
        "models": ["zai-org/GLM-5.3", "zai-org/GLM-5.3-Flash"],
        "research_dataset_sha256": research_dataset_sha256,
        "tree_hash_algorithm": commitment["algorithm"],
        "source_and_configuration_tree_sha256": commitment["tree_sha256"],
        "tracked_file_count": commitment["tracked_file_count"],
        "tracked_files": commitment["tracked_files"],
        "trial_window": {
            "starts_at": starts_at.isoformat().replace("+00:00", "Z"),
            "signal_cutoff_at": signal_cutoff_at.isoformat().replace("+00:00", "Z"),
            "forced_exit_at": forced_exit_at.isoformat().replace("+00:00", "Z"),
            "maximum_new_positions": 1,
        },
        "invariants": [
            "No strategy, model-route, evidence, option-selection, or risk-policy change during the trial window.",
            "No forced trade and no bypass of signal, evidence, jury, option, risk, warrant, or broker gates.",
            "No live-money endpoint or account is permitted.",
            "A no-signal, no-trade, rejection, broker error, fill, partial fill, exit, or P&L outcome is recorded as observed.",
            "Historical proxy and option trade-bar results are never relabeled as broker P&L.",
        ],
        "precommit_sha256": "",
    }
    draft["precommit_sha256"] = canonical_sha256(
        {key: value for key, value in draft.items() if key != "precommit_sha256"}
    )
    return draft


def verify_forward_trial_precommit(
    precommit: dict[str, Any],
    *,
    root: Path,
    research_dataset_sha256: str,
    observed_at: datetime,
) -> dict[str, Any]:
    expected_self_hash = str(precommit.get("precommit_sha256", ""))
    observed_self_hash = canonical_sha256(
        {key: value for key, value in precommit.items() if key != "precommit_sha256"}
    )
    commitment = source_and_configuration_commitment(root)
    created_at = datetime.fromisoformat(str(precommit["created_at"]))
    starts_at = datetime.fromisoformat(str(precommit["trial_window"]["starts_at"]))
    tree_matches = (
        precommit.get("tree_hash_algorithm") == commitment["algorithm"]
        and precommit.get("source_and_configuration_tree_sha256") == commitment["tree_sha256"]
        and precommit.get("tracked_file_count") == commitment["tracked_file_count"]
        and precommit.get("tracked_files") == commitment["tracked_files"]
    )
    data_matches = precommit.get("research_dataset_sha256") == research_dataset_sha256
    self_hash_matches = expected_self_hash == observed_self_hash
    created_before_market = created_at < starts_at
    return {
        "schema": "afterimage-forward-paper-trial-verification-v1",
        "valid": all((tree_matches, data_matches, self_hash_matches, created_before_market)),
        "verified_at": observed_at.isoformat().replace("+00:00", "Z"),
        "verified_before_market_open": observed_at < starts_at,
        "tree_matches": tree_matches,
        "data_matches": data_matches,
        "self_hash_matches": self_hash_matches,
        "created_before_market_open": created_before_market,
        "observed_tree_sha256": commitment["tree_sha256"],
        "precommit_sha256": observed_self_hash,
    }


def write_forward_trial_precommit(path: Path, precommit: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(precommit, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o644,
    )
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)
