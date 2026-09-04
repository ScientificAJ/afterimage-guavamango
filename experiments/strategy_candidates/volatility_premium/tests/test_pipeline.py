from __future__ import annotations

import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from acquire import assert_read_only_arguments, canonical_hash
from candidate import Trade
from dry_run import (
    build_cli_arguments,
    build_entry_payload,
    public_account_capabilities,
    validate_dry_run_arguments,
)
from run_backtest import build_backtest_result, partition_label


def trade(session: str, family: str, pnl: str, return_r: str) -> Trade:
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
        exit_debit=Decimal("0.5"),
        net_pnl=Decimal(pnl),
        max_loss=Decimal(400),
        return_r=Decimal(return_r),
        outcome="target" if Decimal(pnl) > 0 else "stop",
        modeled_fees=Decimal("0.12"),
        modeled_slippage=Decimal(4),
        synchronized_frames=2,
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ("data", "option", "bars", "--symbols", "SPY260101P00100000"),
        ("data", "bars", "--symbol", "SPY"),
        ("option", "contracts", "--underlying-symbols", "SPY"),
    ],
)
def test_acquisition_accepts_only_explicit_read_paths(arguments: tuple[str, ...]) -> None:
    assert_read_only_arguments(arguments)


@pytest.mark.parametrize(
    "arguments",
    [
        ("order", "submit", "--dry-run"),
        ("data", "bars", "order", "cancel"),
        ("position", "list"),
        (),
    ],
)
def test_acquisition_rejects_every_non_data_or_mutation_shape(arguments: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="READ_ONLY_ACQUISITION_COMMAND_REQUIRED"):
        assert_read_only_arguments(arguments)


def test_canonical_hash_is_order_independent_for_object_keys() -> None:
    assert canonical_hash({"b": 2, "a": 1}) == canonical_hash({"a": 1, "b": 2})
    assert len(canonical_hash({"a": 1})) == 64


def test_partition_boundaries_leave_july_through_early_september_oos() -> None:
    assert partition_label(date(2026, 3, 31)) == "burn_in"
    assert partition_label(date(2026, 4, 1)) == "walk_forward"
    assert partition_label(date(2026, 6, 23)) == "walk_forward"
    assert partition_label(date(2026, 6, 24)) == "embargo"
    assert partition_label(date(2026, 7, 1)) == "oos"
    assert partition_label(date(2026, 9, 3)) == "oos"
    assert partition_label(date(2026, 9, 4)) == "outside"


def test_result_freezes_on_walk_forward_and_reports_all_oos_variants() -> None:
    trades = {
        "defensive": (
            trade("2026-04-01", "defensive", "4", "0.01"),
            trade("2026-07-01", "defensive", "-40", "-0.10"),
        ),
        "balanced": (
            trade("2026-04-01", "balanced", "40", "0.10"),
            trade("2026-07-01", "balanced", "20", "0.05"),
        ),
        "tight": (
            trade("2026-04-01", "tight", "-40", "-0.10"),
            trade("2026-07-01", "tight", "4000", "10"),
        ),
    }

    result = build_backtest_result(
        trades,
        exclusions={"defensive": (), "balanced": (), "tight": ()},
        source_hash="a" * 64,
    )

    assert result["selection"]["frozen_family"] == "balanced"
    assert set(result["variants"]) == {"defensive", "balanced", "tight"}
    assert result["variants"]["tight"]["oos"]["net_pnl"] == "4000.00"
    assert result["selected_oos"]["sample_count"] == 1
    assert result["selected_oos"]["net_pnl"] == "20.00"
    assert result["selected_oos"]["mean_ci95_lower_r"] == "0.05"
    assert result["selected_oos"]["mean_ci95_upper_r"] == "0.05"
    assert result["variants"]["balanced"]["walk_forward_folds"]["observed_months"] == 1
    assert result["split"]["oos_start"] == "2026-07-01"
    assert result["pricing_model"]["basis"] == "adverse_synchronized_5min_trade_bar_extremes"
    assert len(result["result_hash"]) == 64


def test_credit_spread_payload_uses_negative_mleg_limit_and_opening_intents() -> None:
    payload = build_entry_payload(
        short_symbol="SPY260911P00750000",
        long_symbol="SPY260911P00745000",
        credit=Decimal("0.68"),
        client_order_id="aft-vrp-dry-run",
    )

    assert payload == {
        "client_order_id": "aft-vrp-dry-run",
        "order_class": "mleg",
        "qty": "1",
        "type": "limit",
        "limit_price": "-0.68",
        "time_in_force": "day",
        "legs": [
            {
                "symbol": "SPY260911P00750000",
                "ratio_qty": "1",
                "side": "sell",
                "position_intent": "sell_to_open",
            },
            {
                "symbol": "SPY260911P00745000",
                "ratio_qty": "1",
                "side": "buy",
                "position_intent": "buy_to_open",
            },
        ],
    }
    arguments = build_cli_arguments(payload)
    validate_dry_run_arguments(arguments)
    assert arguments[-1] == "--dry-run"
    assert "--side" not in arguments


def test_dry_run_boundary_rejects_command_if_terminal_flag_is_removed() -> None:
    payload = build_entry_payload(
        short_symbol="SPY260911P00750000",
        long_symbol="SPY260911P00745000",
        credit=Decimal("0.68"),
        client_order_id="aft-vrp-dry-run",
    )
    unsafe = build_cli_arguments(payload)[:-1]

    with pytest.raises(ValueError, match="DRY_RUN_FLAG_REQUIRED"):
        validate_dry_run_arguments(unsafe)


def test_dry_run_artifact_does_not_expose_account_identity() -> None:
    capabilities = public_account_capabilities(
        {
            "id": "secret-account-id",
            "status": "ACTIVE",
            "options_approved_level": 3,
            "options_trading_level": 3,
            "trading_blocked": False,
        },
        {"max_options_trading_level": 3},
    )

    assert capabilities == {
        "paper": True,
        "status": "ACTIVE",
        "options_approved_level": 3,
        "options_trading_level": 3,
        "trading_blocked": False,
        "level_3_eligible": True,
    }
    assert "secret-account-id" not in str(capabilities)
