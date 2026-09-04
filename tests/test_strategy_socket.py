from __future__ import annotations

import hashlib
import inspect
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

import pytest

from afterimage.config import load_runtime_config
from afterimage.contracts.hashing import canonical_sha256
from afterimage.orchestration.coordinator import Coordinator
from afterimage.storage import Database
from afterimage.strategies.registry import configured_registry
from afterimage.strategies.socket import StrategyRuntimeSpec


def test_configured_registry_loads_every_declared_plugin_without_code_registration() -> None:
    config = load_runtime_config(Path("configs"))

    registry = configured_registry(config)

    assert registry.list() == [
        "momentum_continuation_v1@1.0.0",
        "opening_range_failure_v1@1.0.0",
        "shadow_clock_shock_reversal_v1@1.0.0",
        "volatility_dislocation_v1@1.0.0",
    ]


def test_runtime_spec_exposes_the_strategy_data_and_execution_contract() -> None:
    config = load_runtime_config(Path("configs"))

    spec = StrategyRuntimeSpec.from_config(config.strategy("opening_range_failure_v1"))

    assert spec.identity.strategy_id == "opening_range_failure_v1"
    assert spec.symbols == ("SPY", "QQQ")
    assert spec.bar_timeframe == "5Min"
    assert spec.lookback_calendar_days == 1
    assert spec.signal_at.isoformat() == "10:00:00"
    assert spec.entry_cutoff.isoformat() == "10:05:00"
    assert spec.execution_kind == "option"


def test_runtime_spec_supports_a_multi_session_equity_strategy_socket(tmp_path: Path) -> None:
    strategy_file = tmp_path / "equity.yaml"
    strategy_file.write_text(
        """
strategy_id: equity_gap_v1
strategy_version: 1.0.0
plugin: afterimage.strategies.opening_range_failure:OpeningRangeFailureStrategy
symbols: [QQQ, IWM, XLK]
runtime:
  bar_timeframe: 15Min
  lookback_calendar_days: 21
  session_start: "09:30"
  signal_at: "09:45"
  entry_cutoff: "10:00"
  execution_kind: equity
  market_scope: universe
""".strip(),
        encoding="utf-8",
    )
    from afterimage.config import StrategyConfig

    payload = __import__("yaml").safe_load(strategy_file.read_text(encoding="utf-8"))
    config = StrategyConfig(
        strategy_id="equity_gap_v1",
        strategy_version="1.0.0",
        payload=payload,
        source_hash="f" * 64,
    )

    spec = StrategyRuntimeSpec.from_config(config)

    assert spec.symbols == ("QQQ", "IWM", "XLK")
    assert spec.bar_timeframe == "15Min"
    assert spec.lookback_calendar_days == 21
    assert spec.execution_kind == "equity"
    assert spec.market_scope == "universe"
    assert Coordinator._market_symbols(spec, None) == ("QQQ", "IWM", "XLK")


def test_primary_market_scope_retains_single_symbol_compatibility() -> None:
    config = load_runtime_config(Path("configs"))
    spec = StrategyRuntimeSpec.from_config(config.strategy("opening_range_failure_v1"))

    assert Coordinator._market_symbols(spec, None) == ("SPY",)
    assert Coordinator._market_symbols(spec, "qqq") == ("QQQ",)


def test_coordinator_resolves_the_runtime_selected_strategy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AFTERIMAGE_ACTIVE_STRATEGY", "momentum_continuation_v1")
    coordinator = Coordinator(
        Database(f"sqlite:///{tmp_path / 'socket.db'}"),
        signing_key_path=tmp_path / "warrant.pem",
    )

    selected, spec = coordinator.resolve_strategy()
    explicit, explicit_spec = coordinator.resolve_strategy("opening_range_failure_v1")

    assert selected.identity.strategy_id == "momentum_continuation_v1"
    assert spec.identity == selected.identity
    assert explicit.identity.strategy_id == "opening_range_failure_v1"
    assert explicit_spec.identity == explicit.identity


def test_default_strategy_is_the_admitted_equity_winner(tmp_path: Path) -> None:
    coordinator = Coordinator(
        Database(f"sqlite:///{tmp_path / 'default-winner.db'}"),
        signing_key_path=tmp_path / "warrant.pem",
    )

    selected, spec = coordinator.resolve_strategy()

    assert selected.identity.strategy_id == "shadow_clock_shock_reversal_v1"
    assert spec.display_name == "GuavaMango"
    assert spec.execution_kind == "equity"


def test_strategy_authority_binds_config_and_plugin_implementation(tmp_path: Path) -> None:
    coordinator = Coordinator(
        Database(f"sqlite:///{tmp_path / 'authority.db'}"),
        signing_key_path=tmp_path / "warrant.pem",
    )
    strategy = coordinator.registry.load("shadow_clock_shock_reversal_v1")
    configured = coordinator.config.strategy(strategy.identity.strategy_id)
    source_file = inspect.getsourcefile(type(strategy))
    assert source_file is not None
    implementation_hash = hashlib.sha256(Path(source_file).read_bytes()).hexdigest()

    assert coordinator._strategy_authority_hash(strategy) == canonical_sha256(
        {
            "identity": strategy.identity.model_dump(mode="json"),
            "strategy_config_hash": configured.source_hash,
            "strategy_implementation_hash": implementation_hash,
            "runtime_config_manifest_hash": coordinator.config.manifest_hash,
            "risk_policy_version": coordinator.config.risk.policy_version,
        }
    )


def test_timeframe_duration_is_parsed_for_completed_bar_cutoffs() -> None:
    assert Coordinator._timeframe_delta("15Min") == timedelta(minutes=15)
    assert Coordinator._timeframe_delta("1Hour") == timedelta(hours=1)

    with pytest.raises(ValueError, match="BAR_TIMEFRAME_UNSUPPORTED"):
        Coordinator._timeframe_delta("banana")


def test_analysis_session_tracks_each_strategy_signal_boundary() -> None:
    before_close = {"timestamp": "2026-09-04T09:31:00-04:00"}
    after_close = {"timestamp": "2026-09-04T16:01:00-04:00"}

    assert Coordinator._analysis_date(before_close, time(16, 0)).isoformat() == "2026-09-03"
    assert Coordinator._analysis_date(after_close, time(16, 0)).isoformat() == "2026-09-04"


def test_daily_bar_becomes_available_at_session_close_not_twenty_four_hours_later() -> None:
    bar_start = datetime(2026, 9, 4, 4, 0, tzinfo=UTC)

    assert not Coordinator._bar_available(
        bar_start, datetime(2026, 9, 4, 19, 59, tzinfo=UTC), "1Day"
    )
    assert Coordinator._bar_available(bar_start, datetime(2026, 9, 4, 20, 0, tzinfo=UTC), "1Day")


def test_daily_signal_dedup_is_scoped_to_the_next_execution_session() -> None:
    assert Coordinator._snapshot_dedup_key(
        "snapshot", "1Day", datetime(2026, 9, 4, 20, 1, tzinfo=UTC)
    ) != Coordinator._snapshot_dedup_key(
        "snapshot", "1Day", datetime(2026, 9, 8, 13, 31, tzinfo=UTC)
    )
    assert (
        Coordinator._snapshot_dedup_key("snapshot", "5Min", datetime(2026, 9, 4, 14, 1, tzinfo=UTC))
        == "snapshot"
    )
