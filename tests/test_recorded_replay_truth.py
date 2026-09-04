from __future__ import annotations

from pathlib import Path

from afterimage.orchestration.coordinator import Coordinator
from afterimage.storage import Database


def coordinator(tmp_path: Path) -> Coordinator:
    return Coordinator(
        Database(f"sqlite:///{tmp_path / 'afterimage.db'}"),
        signing_key_path=tmp_path / "warrant.pem",
    )


def test_recorded_dataset_is_fixed_and_contains_losses(tmp_path: Path) -> None:
    runtime = coordinator(tmp_path)

    rows = runtime._historical_rows()

    assert len(rows) >= 80
    assert any(row.return_r > 0 for row in rows)
    assert any(row.return_r < 0 for row in rows)
    assert all(row.placebo_return_r is not None for row in rows)


def test_accept_and_reject_replays_never_claim_broker_fills_or_pnl(tmp_path: Path) -> None:
    runtime = coordinator(tmp_path)

    accepted = runtime.run_demo(accepted=True)
    rejected = runtime.run_demo(accepted=False)
    event_types = {event["event_type"] for event in accepted["events"]}

    assert accepted["dataset_hash"] == rejected["dataset_hash"]
    assert not {"submit_started", "working", "filled", "exit_started", "closed"} & event_types
    assert "broker_pnl" not in str(accepted)
    assert accepted["mode"] == "recorded-replay"
    assert accepted["state"] == "SHADOW_READY"
    assert accepted["option_replay"]["pricing_policy"] == "long_at_ask_short_at_bid"
    assert accepted["evidence_paths"][0] == {"step": 0, "low": "0", "median": "0", "high": "0"}
    assert accepted["evidence_paths"][-1]["high"] == "3"


def test_recorded_agents_are_explicitly_non_live(tmp_path: Path) -> None:
    summary = coordinator(tmp_path).run_demo(accepted=True)

    assert summary["agent_provenance"]["mode"] == "recorded-fixture"
    assert summary["agent_provenance"]["live_inference"] is False
