from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from afterimage.contracts.models import AccountSnapshot, MarketRecord
from afterimage.execution.alpaca_gateway import AccountPreflight
from afterimage.orchestration.coordinator import Coordinator
from afterimage.research.historical_execution import (
    HistoricalReplayGateway,
    load_historical_replay_case,
    reveal_equity_outcome,
)
from afterimage.strategies.shadow_clock_shock_reversal import (
    ShadowClockShockReversalStrategy,
)

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "experiments/strategy_candidates/event_flow/data/alpaca_daily_2015_2026.json"
RESULT = (
    ROOT / "experiments/strategy_candidates/event_flow/results/event_flow_04_shadow_turnaround.json"
)


def test_historical_case_freezes_real_bars_before_the_signal_cutoff() -> None:
    case = load_historical_replay_case(CACHE, RESULT, date(2022, 4, 18))
    strategy = ShadowClockShockReversalStrategy()
    snapshot = strategy.freeze(case.causal_frame)
    candidate = strategy.detect(snapshot)

    assert case.source == "authenticated Alpaca CLI 0.0.14 historical stock bars"
    assert case.feed == "iex"
    assert case.published_trade["symbol"] == "XLP"
    assert candidate is not None
    assert candidate.symbol == "XLP"
    assert candidate.signal_at == case.signal_cutoff
    assert all(record.timestamp <= case.signal_cutoff for record in case.causal_frame.records)
    assert all(bar["t"] > case.signal_cutoff.isoformat() for bar in case.future_bars)


def test_historical_outcome_reveal_uses_production_levels_for_a_winner_and_loser() -> None:
    winner = load_historical_replay_case(CACHE, RESULT, date(2022, 4, 18))
    loser = load_historical_replay_case(CACHE, RESULT, date(2022, 1, 26))

    winner_outcome = reveal_equity_outcome(
        winner,
        entry_price=Decimal(winner.published_trade["entry_fill"]),
        stop_price=Decimal(winner.published_trade["stop_price"]),
        target_price=Decimal(winner.published_trade["target_price"]),
        modeled_cost_per_share=Decimal(0),
        quantity=int(winner.published_trade["shares"]),
    )
    loser_outcome = reveal_equity_outcome(
        loser,
        entry_price=Decimal(loser.published_trade["entry_fill"]),
        stop_price=Decimal(loser.published_trade["stop_price"]),
        target_price=Decimal(loser.published_trade["target_price"]),
        modeled_cost_per_share=Decimal(0),
        quantity=int(loser.published_trade["shares"]),
    )

    assert winner_outcome["outcome"] == "target"
    assert Decimal(winner_outcome["realized_r"]) >= Decimal(3)
    assert Decimal(winner_outcome["modeled_net_pnl_dollars"]) > 0
    assert winner_outcome["future_bars_revealed_after_decision"] is True
    assert loser_outcome["outcome"] == "stop"
    assert Decimal(loser_outcome["realized_r"]) == Decimal(-1)
    assert Decimal(loser_outcome["modeled_net_pnl_dollars"]) < 0


@pytest.mark.asyncio
async def test_historical_gateway_keeps_future_bars_out_of_the_strategy_packet() -> None:
    case = load_historical_replay_case(CACHE, RESULT, date(2022, 4, 18))

    class Delegate:
        execution_enabled = False

        async def preflight(self, expected: str) -> AccountPreflight:
            assert expected == "a" * 64
            return AccountPreflight(
                account=AccountSnapshot(
                    account_id_hash=expected,
                    paper=True,
                    status="ACTIVE",
                    equity=Decimal(100000),
                    last_equity=Decimal(100000),
                    cash=Decimal(100000),
                    options_buying_power=Decimal(100000),
                    options_approved_level=3,
                    options_trading_level=3,
                    trading_blocked=False,
                    timestamp=datetime(2026, 9, 4, tzinfo=UTC),
                ),
                market_open=False,
                clock={"is_open": False, "timestamp": "2026-09-04T08:00:00-04:00"},
                open_orders=(),
                positions=(),
                capabilities={"transport": "alpaca-cli/0.0.14", "execution": "disabled"},
            )

        async def dry_run_order(self, intent: object, client_order_id: str) -> dict[str, object]:
            return {"intent": intent, "client_order_id": client_order_id, "submitted": False}

    gateway = HistoricalReplayGateway(Delegate(), case)  # type: ignore[arg-type]
    checked = await gateway.preflight("a" * 64)
    bars = await gateway.stock_bars(
        "XLP",
        case.signal_cutoff.replace(year=2021),
        case.signal_cutoff,
        "1Day",
    )
    snapshot = await gateway.stock_snapshot("XLP")
    dry_run = await gateway.dry_run_order("intent", "client-id")  # type: ignore[arg-type]

    assert checked.market_open is True
    assert checked.account.timestamp == gateway.observed_at
    assert checked.clock["historical_replay"] is True
    assert bars
    assert all(datetime.fromisoformat(str(bar["t"])) <= case.signal_cutoff for bar in bars)
    assert snapshot["latestQuote"]["ap"] == case.published_trade["entry_fill"]
    assert dry_run["submitted"] is False


def test_daily_regime_volatility_uses_daily_not_intraday_annualization() -> None:
    records = tuple(
        MarketRecord(
            symbol="SPY",
            timestamp=datetime(2026, 9, day, 20, tzinfo=UTC),
            received_at=datetime(2026, 9, 3, 20, tzinfo=UTC),
            source="test",
            feed="iex",
            kind="bar",
            values={"open": close, "high": close, "low": close, "close": close, "volume": 1},
        )
        for day, close in ((1, 100), (2, 101))
    )

    daily = Coordinator._live_context(records, "1Day")
    intraday = Coordinator._live_context(records, "5Min")

    assert daily["realized_volatility"] == pytest.approx(0.15874508)
    assert intraday["realized_volatility"] > daily["realized_volatility"]


def test_cross_sectional_symbols_are_not_treated_as_time_series_returns() -> None:
    records = tuple(
        MarketRecord(
            symbol=symbol,
            timestamp=datetime(2026, 9, day, 20, tzinfo=UTC),
            received_at=datetime(2026, 9, 3, 20, tzinfo=UTC),
            source="test",
            feed="iex",
            kind="bar",
            values={"open": close, "high": close, "low": close, "close": close, "volume": 1},
        )
        for day in (1, 2)
        for symbol, close in (("GLD", 400), ("QQQ", 700))
    )

    context = Coordinator._live_context(records, "1Day")

    assert context["realized_volatility"] == 0


def test_agent_snapshot_packet_is_hash_bound_without_thousands_of_raw_bars() -> None:
    case = load_historical_replay_case(CACHE, RESULT, date(2022, 4, 18))
    snapshot = ShadowClockShockReversalStrategy().freeze(case.causal_frame)

    packet = Coordinator._agent_snapshot_packet(snapshot)

    assert "records" not in packet
    assert packet["snapshot_id"] == snapshot.snapshot_id
    assert packet["record_count"] == len(snapshot.records)
    assert len(packet["records_sha256"]) == 64
    assert packet["features"] == snapshot.features
