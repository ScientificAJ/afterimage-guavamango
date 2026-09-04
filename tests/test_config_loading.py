from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from afterimage.config import load_runtime_config
from afterimage.orchestration.coordinator import Coordinator
from afterimage.storage import Database


def test_versioned_yaml_drives_runtime_policies(tmp_path: Path) -> None:
    config = load_runtime_config(Path("configs"))

    assert config.risk.policy_version == "hackathon-v1"
    assert config.risk.maximum_modeled_loss == Decimal(500)
    assert config.risk.minimum_operational_reward_risk == Decimal("3.0")
    assert config.tournament.minimum_n == 30
    assert config.strategy("opening_range_failure_v1").payload["penetration_fraction"] == 0.10
    assert config.strategy("opening_range_failure_v1").payload["entry_cutoff"] == "10:05"
    assert len(config.manifest_hash) == 64

    coordinator = Coordinator(
        Database(f"sqlite:///{tmp_path / 'config.db'}"),
        signing_key_path=tmp_path / "warrant.pem",
        config=config,
    )
    assert coordinator.risk.policy == config.risk
    assert coordinator.promotion_policy == config.tournament
