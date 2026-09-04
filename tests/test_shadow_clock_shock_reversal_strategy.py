from __future__ import annotations

import hashlib
import importlib
import json
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from afterimage.config import load_runtime_config
from afterimage.contracts.hashing import canonical_sha256
from afterimage.contracts.models import MarketRecord
from afterimage.strategies.base import MarketFrame
from afterimage.strategies.deployment import load_deployment_evidence
from afterimage.strategies.registry import configured_registry
from afterimage.strategies.socket import StrategyRuntimeSpec

ET = ZoneInfo("America/New_York")
UNIVERSE = ("QQQ", "IWM", "XLK", "XLF", "XLE", "XLV", "XLY", "XLI", "XLP", "TLT", "GLD")
STRATEGY_ID = "shadow_clock_shock_reversal_v1"
MODULE = "afterimage.strategies.shadow_clock_shock_reversal"
ROOT = Path(__file__).resolve().parents[1]


def _strategy() -> Any:
    module = importlib.import_module(MODULE)
    return module.ShadowClockShockReversalStrategy()


def _business_days_ending(end: date, count: int) -> tuple[date, ...]:
    values: list[date] = []
    cursor = end
    while len(values) < count:
        if cursor.weekday() < 5:
            values.append(cursor)
        cursor -= timedelta(days=1)
    return tuple(reversed(values))


def _records(
    end: date,
    *,
    current_shocks: dict[str, float] | None = None,
    prior_friday_shadow: bool = False,
) -> tuple[MarketRecord, ...]:
    sessions = _business_days_ending(end, 115)
    shocks = current_shocks or {}
    received_at = datetime.combine(end, time(21), UTC)
    result: list[MarketRecord] = []
    for symbol in UNIVERSE:
        for index, session in enumerate(sessions):
            baseline = 100.0 + index * 0.5
            close = baseline
            low = baseline - 1.0
            high = baseline + 1.0
            if prior_friday_shadow and index == len(sessions) - 2 and session.weekday() == 4:
                close = baseline - (8.0 if symbol == "IWM" else 7.0 if symbol == "QQQ" else 0.0)
                low = close - 0.5
            if index == len(sessions) - 1 and symbol in shocks:
                close = baseline - shocks[symbol]
                low = close - 0.5
            timestamp = datetime.combine(session, time(16), ET).astimezone(UTC)
            result.append(
                MarketRecord(
                    symbol=symbol,
                    timestamp=timestamp,
                    received_at=received_at,
                    source="alpaca-cli",
                    feed="iex",
                    kind="bar",
                    values={
                        "open": baseline - 0.1,
                        "high": high,
                        "low": low,
                        "close": close,
                        "volume": 1_000_000 + index,
                    },
                )
            )
    return tuple(sorted(result, key=lambda item: (item.timestamp, item.symbol)))


def _freeze(end: date, records: tuple[MarketRecord, ...] | None = None) -> Any:
    cutoff = datetime.combine(end, time(16), ET).astimezone(UTC)
    return _strategy().freeze(
        MarketFrame(
            symbol="QQQ",
            cutoff=cutoff,
            records=records or _records(end, current_shocks={"QQQ": 6.0, "IWM": 8.0}),
        )
    )


def test_plugin_selects_the_strongest_point_in_time_universe_shock() -> None:
    end = date(2026, 9, 2)  # Wednesday

    snapshot = _freeze(end)
    candidate = _strategy().detect(snapshot)

    assert snapshot.features["complete"] is True
    assert snapshot.features["universe_complete"] is True
    assert snapshot.features["selected_symbol"] == "IWM"
    assert snapshot.features["countertrend_shock_atr"] >= 0.6
    assert snapshot.features["close_location"] <= 0.25
    assert snapshot.features["trend"] == 1
    assert snapshot.features["shadow_blocked"] is False
    assert candidate is not None
    assert candidate.symbol == "IWM"
    assert candidate.direction == "bullish"
    assert candidate.permitted_structures == ("equity_bracket",)
    assert candidate.features["equity_side"] == "buy"
    assert candidate.features["stop_distance"] > 0
    assert candidate.features["target_r"] == 3.0
    assert candidate.features["stop_r"] == -1.0


def test_shadow_clock_consumes_a_skipped_friday_signal_and_blocks_monday() -> None:
    end = date(2026, 9, 7)  # Monday; exchange-holiday knowledge is outside this unit fixture.
    records = _records(
        end,
        current_shocks={"QQQ": 8.0, "IWM": 9.0},
        prior_friday_shadow=True,
    )

    snapshot = _freeze(end, records)

    assert snapshot.features["calendar_allowed"] is True
    assert snapshot.features["shadow_blocked"] is True
    assert snapshot.features["blocking_signal_weekday"] == "Friday"
    assert _strategy().detect(snapshot) is None


def test_thursday_signal_updates_shadow_state_but_is_not_executable() -> None:
    end = date(2026, 9, 3)

    snapshot = _freeze(end)

    assert snapshot.features["selected_symbol"] == "IWM"
    assert snapshot.features["calendar_allowed"] is False
    assert snapshot.features["shadow_signal_started"] is True
    assert _strategy().detect(snapshot) is None


def test_previous_close_signal_is_available_during_the_next_session_open_window() -> None:
    signal_session = date(2026, 9, 2)  # Wednesday
    next_open = datetime(2026, 9, 3, 9, 35, tzinfo=ET)
    records = _records(signal_session, current_shocks={"QQQ": 6.0, "IWM": 8.0})

    snapshot = _strategy().freeze(MarketFrame(symbol="QQQ", cutoff=next_open, records=records))
    candidate = _strategy().detect(snapshot)
    runtime = load_runtime_config(ROOT / "configs")
    spec = StrategyRuntimeSpec.from_config(runtime.strategy(STRATEGY_ID))

    assert snapshot.features["latest_session"] == signal_session.isoformat()
    assert candidate is not None
    assert candidate.symbol == "IWM"
    assert candidate.signal_at == next_open
    assert spec.entry_cutoff.isoformat() == "10:00:00"


def test_post_cutoff_bar_cannot_change_snapshot_or_candidate() -> None:
    end = date(2026, 9, 2)
    records = _records(end, current_shocks={"QQQ": 6.0, "IWM": 8.0})
    future = MarketRecord(
        symbol="IWM",
        timestamp=datetime(2026, 9, 3, 20, tzinfo=UTC),
        received_at=datetime(2026, 9, 3, 21, tzinfo=UTC),
        source="alpaca-cli",
        feed="iex",
        kind="bar",
        values={"open": 150, "high": 200, "low": 100, "close": 200, "volume": 9_000_000},
    )

    base = _freeze(end, records)
    contaminated = _freeze(end, (*records, future))

    assert contaminated.snapshot_id == base.snapshot_id
    assert contaminated.features == base.features
    assert _strategy().detect(contaminated) == _strategy().detect(base)


def test_incomplete_universe_fails_closed() -> None:
    end = date(2026, 9, 2)
    records = tuple(
        item
        for item in _records(end, current_shocks={"QQQ": 6.0, "IWM": 8.0})
        if item.symbol != "GLD"
    )

    snapshot = _freeze(end, records)

    assert snapshot.features["complete"] is False
    assert snapshot.features["universe_complete"] is False
    assert snapshot.features["missing_symbols"] == "GLD"
    assert _strategy().detect(snapshot) is None


def test_exact_runtime_config_registers_an_equity_universe_plugin() -> None:
    config = load_runtime_config(ROOT / "configs")
    configured = config.strategy(STRATEGY_ID)
    spec = StrategyRuntimeSpec.from_config(configured)
    plugin = configured_registry(config).load(STRATEGY_ID)

    assert plugin.identity.strategy_id == STRATEGY_ID
    assert spec.display_name == "GuavaMango"
    assert spec.symbols == UNIVERSE
    assert spec.bar_timeframe == "1Day"
    assert spec.lookback_calendar_days == 366
    assert spec.market_scope == "universe"
    assert spec.execution_kind == "equity"
    assert configured.payload["signal"]["long_only"] is True
    assert configured.payload["signal"]["minimum_shock_atr"] == 0.6
    assert configured.payload["risk"]["after_cost_target_r"] == 3.0
    assert configured.payload["execution"]["timing"] == "next_regular_session_open"
    assert configured.payload["execution"]["modeled_round_trip_cost_per_share"] == 0.01
    assert configured.payload["evidence"]["manifest_path"] == (
        "configs/strategies/evidence/shadow_clock_shock_reversal_v1/manifest.json"
    )


def test_deployment_manifest_binds_source_config_and_immutable_result() -> None:
    manifest_path = (
        ROOT / "configs/strategies/evidence/shadow_clock_shock_reversal_v1/manifest.json"
    )
    deployment_result_path = manifest_path.parent / "result.json"
    source_path = ROOT / "src/afterimage/strategies/shadow_clock_shock_reversal.py"
    config_path = ROOT / "configs/strategies/shadow_clock_shock_reversal_v1.yaml"
    research_result_path = (
        ROOT
        / "experiments/strategy_candidates/event_flow/results/event_flow_04_shadow_turnaround.json"
    )
    runtime = load_runtime_config(ROOT / "configs")
    config = runtime.strategy(STRATEGY_ID)
    plugin = configured_registry(runtime).load(STRATEGY_ID)
    authority_hash = canonical_sha256(
        {
            "identity": plugin.identity.model_dump(mode="json"),
            "strategy_config_hash": config.source_hash,
            "strategy_implementation_hash": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "runtime_config_manifest_hash": runtime.manifest_hash,
            "risk_policy_version": runtime.risk.policy_version,
        }
    )
    decision, manifest = load_deployment_evidence(
        manifest_path,
        strategy_id=STRATEGY_ID,
        strategy_version="1.0.0",
        strategy_authority_hash=authority_hash,
        strategy_config_hash=config.source_hash,
        strategy_source_hash=hashlib.sha256(source_path.read_bytes()).hexdigest(),
    )
    deployment_result = json.loads(deployment_result_path.read_text(encoding="utf-8"))
    research_result = json.loads(research_result_path.read_text(encoding="utf-8"))

    assert decision.status == "PASS"
    assert manifest.schema_version == "afterimage-deployment-evidence-v1"
    assert manifest.strategy_authority_hash == authority_hash
    assert manifest.strategy_config_hash == config.source_hash
    assert manifest.result_content_hash == canonical_sha256(deployment_result)
    assert deployment_result["research"]["result_hash"] == research_result["result_hash"]
    assert (
        deployment_result["deployment_binding"]["strategy_source_sha256"]
        == hashlib.sha256(source_path.read_bytes()).hexdigest()
    )
    assert (
        deployment_result["deployment_binding"]["config_file_sha256"]
        == hashlib.sha256(config_path.read_bytes()).hexdigest()
    )
    assert (
        deployment_result["research"]["result_file_sha256"]
        == hashlib.sha256(research_result_path.read_bytes()).hexdigest()
    )
    assert manifest.research_result_hash == research_result["result_hash"]
    assert manifest.admitted is True
    assert manifest.required_gates == research_result["admission"]["checks"]
    assert deployment_result["admission_metrics"] == research_result["rolling_oos"]["metrics"]
    assert deployment_result["runtime_contract"] == {
        "execution_kind": "equity",
        "market_scope": "universe",
        "order_submission_performed": False,
    }
    assert deployment_result["strategy_identity"]["display_name"] == "GuavaMango"
