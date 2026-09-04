from __future__ import annotations

import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from candidate import (
    FAMILIES,
    Contract,
    DataExclusion,
    OptionBar,
    SpreadFrame,
    Trade,
    adverse_entry_credit,
    adverse_exit_debit,
    daily_features,
    freeze_family,
    select_contract_pair,
    simulate_trade,
    summarize,
)


def bar(
    symbol: str,
    timestamp: str,
    *,
    low: str,
    high: str,
) -> OptionBar:
    return OptionBar(
        symbol=symbol,
        timestamp=datetime.fromisoformat(timestamp),
        open=Decimal(low),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(high),
        volume=100,
    )


def frame(
    timestamp: str, *, short_low: str, short_high: str, long_low: str, long_high: str
) -> SpreadFrame:
    return SpreadFrame(
        timestamp=datetime.fromisoformat(timestamp),
        short=bar("SPY-SHORT", timestamp, low=short_low, high=short_high),
        long=bar("SPY-LONG", timestamp, low=long_low, high=long_high),
    )


def test_adverse_trade_bar_prices_charge_slippage_on_every_leg() -> None:
    observation = frame(
        "2026-06-01T14:00:00+00:00",
        short_low="1.20",
        short_high="1.30",
        long_low="0.40",
        long_high="0.50",
    )

    assert adverse_entry_credit(observation) == Decimal("0.68")
    assert adverse_exit_debit(observation) == Decimal("0.92")


def test_mismatched_leg_timestamps_are_excluded() -> None:
    short = bar(
        "SPY-SHORT",
        "2026-06-01T14:00:00+00:00",
        low="1.20",
        high="1.30",
    )
    long = bar(
        "SPY-LONG",
        "2026-06-01T14:05:00+00:00",
        low="0.40",
        high="0.50",
    )

    with pytest.raises(DataExclusion, match="LEG_TIMESTAMP_MISMATCH"):
        SpreadFrame(timestamp=short.timestamp, short=short, long=long)


def test_first_passage_uses_adverse_exit_and_round_trip_fees() -> None:
    frames = (
        frame(
            "2026-06-01T14:00:00+00:00",
            short_low="1.20",
            short_high="1.25",
            long_low="0.40",
            long_high="0.50",
        ),
        frame(
            "2026-06-01T14:05:00+00:00",
            short_low="0.40",
            short_high="0.45",
            long_low="0.18",
            long_high="0.20",
        ),
        frame(
            "2026-06-01T14:10:00+00:00",
            short_low="0.10",
            short_high="0.15",
            long_low="0.03",
            long_high="0.05",
        ),
    )

    trade = simulate_trade(
        session_date="2026-06-01",
        family="balanced",
        short_symbol="SPY-SHORT",
        long_symbol="SPY-LONG",
        width=Decimal(5),
        frames=frames,
    )

    # Entry credit: 1.20 - 0.50 - 0.02 = 0.68.  The second-frame
    # adverse debit is 0.45 - 0.18 + 0.02 = 0.29, crossing 50% credit.
    # Four contract-sides at $0.03 each add $0.12 round-trip fees.
    assert trade.outcome == "target"
    assert trade.exit_debit == Decimal("0.29")
    assert trade.net_pnl == Decimal("38.88")
    assert trade.max_loss == Decimal("432.12")
    assert trade.return_r == Decimal("38.88") / Decimal("432.12")
    assert trade.modeled_fees == Decimal("0.12")
    assert trade.modeled_slippage == Decimal("4.00")


def test_summary_calculates_path_drawdown_and_hit_rate() -> None:
    winning = simulate_trade(
        session_date="2026-06-01",
        family="balanced",
        short_symbol="SPY-SHORT",
        long_symbol="SPY-LONG",
        width=Decimal(5),
        frames=(
            frame(
                "2026-06-01T14:00:00+00:00",
                short_low="1.20",
                short_high="1.25",
                long_low="0.40",
                long_high="0.50",
            ),
            frame(
                "2026-06-01T14:05:00+00:00",
                short_low="0.40",
                short_high="0.45",
                long_low="0.18",
                long_high="0.20",
            ),
        ),
    )
    losing = simulate_trade(
        session_date="2026-06-02",
        family="balanced",
        short_symbol="SPY-SHORT",
        long_symbol="SPY-LONG",
        width=Decimal(5),
        frames=(
            frame(
                "2026-06-02T14:00:00+00:00",
                short_low="1.20",
                short_high="1.25",
                long_low="0.40",
                long_high="0.50",
            ),
            frame(
                "2026-06-02T14:05:00+00:00",
                short_low="2.20",
                short_high="2.30",
                long_low="0.40",
                long_high="0.45",
            ),
        ),
    )

    metrics = summarize((winning, losing))

    assert metrics.sample_count == 2
    assert metrics.wins == 1
    assert metrics.hit_rate == Decimal("0.5")
    assert metrics.net_pnl == Decimal("-85.24")
    assert metrics.max_drawdown == Decimal("124.12")
    assert metrics.expectancy_r == (winning.return_r + losing.return_r) / Decimal(2)
    assert metrics.sample_stddev_r > 0
    assert metrics.mean_ci95_lower_r < metrics.expectancy_r
    assert metrics.mean_ci95_upper_r > metrics.expectancy_r


def test_daily_features_ignore_the_signal_session_close() -> None:
    history = tuple((date(2026, 5, day), Decimal(str(100 + day))) for day in range(1, 22))

    baseline = daily_features(history, date(2026, 5, 22), lookback=20)
    contaminated = daily_features(
        history + ((date(2026, 5, 22), Decimal(9999)),),
        date(2026, 5, 22),
        lookback=20,
    )

    assert contaminated == baseline
    assert baseline.prior_close == Decimal(121)
    assert baseline.sma == Decimal("111.5")
    assert baseline.daily_volatility_fraction > 0


def test_contract_pair_uses_fixed_otm_distance_width_and_expiry_window() -> None:
    balanced = next(item for item in FAMILIES if item.name == "balanced")
    feature = daily_features(
        tuple((date(2026, 5, day), Decimal(str(100 + day / 10))) for day in range(1, 22)),
        date(2026, 5, 22),
        lookback=20,
    )
    contracts = (
        Contract("SPY-C100", date(2026, 5, 29), Decimal(100), "call"),
        Contract("SPY-P100", date(2026, 5, 29), Decimal(100), "put"),
        Contract("SPY-P99", date(2026, 5, 29), Decimal(99), "put"),
        Contract("SPY-P94", date(2026, 5, 29), Decimal(94), "put"),
        Contract("SPY-P93", date(2026, 5, 29), Decimal(93), "put"),
        Contract("SPY-P99-LATE", date(2026, 6, 5), Decimal(99), "put"),
    )

    selection = select_contract_pair(
        balanced,
        session_date=date(2026, 5, 22),
        spot=Decimal(100),
        feature=feature,
        contracts=contracts,
    )

    assert selection.short.symbol == "SPY-P99"
    assert selection.long.symbol == "SPY-P94"
    assert selection.width == Decimal(5)
    assert selection.expiration == date(2026, 5, 29)


def synthetic_trade(session: str, family: str, net_pnl: str, return_r: str) -> Trade:
    at = datetime.fromisoformat(f"{session}T14:00:00+00:00")
    return Trade(
        session_date=session,
        family=family,
        short_symbol=f"{family}-SHORT",
        long_symbol=f"{family}-LONG",
        width=Decimal(5),
        entry_at=at,
        exit_at=at,
        entry_credit=Decimal(1),
        exit_debit=Decimal(1),
        net_pnl=Decimal(net_pnl),
        max_loss=Decimal(400),
        return_r=Decimal(return_r),
        outcome="target" if Decimal(net_pnl) > 0 else "stop",
        modeled_fees=Decimal("0.12"),
        modeled_slippage=Decimal(4),
        synchronized_frames=2,
    )


def test_family_freeze_never_uses_trades_after_training_cutoff() -> None:
    trades = {
        "defensive": (
            synthetic_trade("2026-04-01", "defensive", "4", "0.01"),
            synthetic_trade("2026-05-01", "defensive", "4", "0.01"),
        ),
        "balanced": (
            synthetic_trade("2026-04-01", "balanced", "40", "0.10"),
            synthetic_trade("2026-05-01", "balanced", "40", "0.10"),
        ),
        "tight": (
            synthetic_trade("2026-04-01", "tight", "-40", "-0.10"),
            synthetic_trade("2026-07-02", "tight", "4000", "10"),
        ),
    }

    frozen = freeze_family(trades, training_cutoff=date(2026, 6, 30))

    assert frozen.family.name == "balanced"
    assert frozen.metrics.sample_count == 2
    assert frozen.validation_start == date(2026, 4, 1)
    assert frozen.training_cutoff == date(2026, 6, 30)
