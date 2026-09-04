from __future__ import annotations

import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from acquire_pivots import normalize_stock_sessions
from pivots import MOMENTUM_FAMILIES, STRANGLE_FAMILIES, PivotTrade
from run_pivots import build_attempt_result


def test_stock_normalization_uses_bar_ending_at_signal_not_bar_starting_at_signal() -> None:
    rows = [
        {"t": "2026-04-01T13:30:00Z", "o": 100, "h": 101, "l": 99, "c": 100.5, "v": 10},
        {"t": "2026-04-01T13:55:00Z", "o": 100.5, "h": 102, "l": 100, "c": 101.5, "v": 10},
        {"t": "2026-04-01T14:00:00Z", "o": 101.5, "h": 999, "l": 1, "c": 999, "v": 10},
        {"t": "2026-04-01T19:55:00Z", "o": 102, "h": 103, "l": 101, "c": 102, "v": 10},
    ]

    sessions = normalize_stock_sessions("SPY", rows)

    assert sessions == [
        {
            "symbol": "SPY",
            "session_date": "2026-04-01",
            "session_open": "100",
            "signal_spot": "101.5",
            "signal_source_bar_start": "2026-04-01T09:55:00-04:00",
            "daily_close": "102",
        }
    ]


def pivot_trade(session: str, symbol: str, family: str, pnl: str, return_r: str) -> PivotTrade:
    at = datetime.fromisoformat(f"{session}T14:00:00+00:00")
    value = Decimal(pnl)
    return PivotTrade(
        session_date=session,
        symbol=symbol,
        strategy="directional_debit_momentum",
        family=family,
        direction="bullish",
        entry_at=at,
        exit_at=at,
        entry_value=Decimal(1),
        exit_value=Decimal(1),
        net_pnl=value,
        max_loss=Decimal(100),
        return_r=Decimal(return_r),
        outcome="target" if value > 0 else "stop",
        stop_risk_dollars=Decimal(10),
        target_dollars=Decimal(30),
        operational_target_stop=Decimal(3),
        modeled_fees=Decimal("0.12"),
        modeled_slippage=Decimal(4),
        synchronized_frames=2,
        leg_symbols=("LONG", "SHORT"),
    )


def test_attempt_result_labels_revealed_rolling_folds_and_emits_mandatory_gates() -> None:
    names = tuple(item.name for item in MOMENTUM_FAMILIES)
    rows = {
        names[0]: (
            pivot_trade("2026-04-01", "SPY", names[0], "10", "0.10"),
            pivot_trade("2026-05-01", "SPY", names[0], "-10", "-0.10"),
            pivot_trade("2026-05-01", "QQQ", names[0], "10", "0.10"),
        ),
        names[1]: (pivot_trade("2026-04-01", "SPY", names[1], "-10", "-0.10"),),
        names[2]: (),
    }

    result = build_attempt_result(
        strategy="directional_debit_momentum",
        trades_by_family=rows,
        exclusions={name: () for name in names},
        source_hash="a" * 64,
    )

    assert (
        result["evaluation_label"]
        == "researcher-visible expanding monthly pseudo-OOS; not untouched"
    )
    assert result["rolling"]["operational_target_stop_minimum"] == "3"
    assert "profit_factor_at_least_2" in result["promotion_gates"]
    assert result["promotion_gates"]["promoted"] is False
    assert set(result["all_variants"]) == set(names)
    assert len(result["result_hash"]) == 64


def test_strangle_attempt_declares_all_fixed_families_and_ultra_high_gates() -> None:
    names = tuple(item.name for item in STRANGLE_FAMILIES)
    result = build_attempt_result(
        strategy="expansion_long_strangle",
        trades_by_family={name: () for name in names},
        exclusions={name: () for name in names},
        source_hash="b" * 64,
    )

    assert set(result["all_variants"]) == set(names)
    assert result["promotion_policy"]["profit_factor_minimum"] == "2.0"
    assert result["promotion_policy"]["expectancy_r_minimum"] == "0.25"
    assert result["promotion_policy"]["max_drawdown_r_maximum"] == "6.0"
    assert result["promotion_policy"]["profitable_at_one_and_half_costs"] is True
    assert result["promotion_policy"]["largest_trade_profit_share_maximum"] == "0.25"
    assert result["verdict"] == "rejected"


def test_extension_attempts_reuse_only_their_predeclared_source_family_sets() -> None:
    for strategy, names in (
        ("directional_long_momentum", tuple(item.name for item in MOMENTUM_FAMILIES)),
        ("compression_long_strangle", ("condor_wide", "condor_balanced", "condor_tight")),
        ("directional_long_reversal", tuple(item.name for item in MOMENTUM_FAMILIES)),
        ("directional_debit_reversal", tuple(item.name for item in MOMENTUM_FAMILIES)),
    ):
        result = build_attempt_result(
            strategy=strategy,
            trades_by_family={name: () for name in names},
            exclusions={name: () for name in names},
            source_hash="c" * 64,
        )

        assert tuple(result["all_variants"]) == names
        assert result["verdict"] == "rejected"
