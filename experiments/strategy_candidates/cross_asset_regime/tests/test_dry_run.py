from __future__ import annotations

from decimal import Decimal

import pytest

from experiments.strategy_candidates.cross_asset_regime.dry_run import (
    build_cli_arguments,
    build_debit_payload,
    public_account_capabilities,
    validate_dry_run_arguments,
    _historical_example,
)


def test_debit_mleg_payload_has_positive_price_and_explicit_opening_intents() -> None:
    payload = build_debit_payload(
        long_symbol="QQQ260911C00600000",
        short_symbol="QQQ260911C00605000",
        debit=Decimal("1.239"),
        client_order_id="aft-cross-asset-dry-run",
    )
    assert payload["limit_price"] == "1.24"
    assert payload["order_class"] == "mleg"
    assert payload["legs"] == [
        {"symbol": "QQQ260911C00600000", "ratio_qty": "1", "side": "buy", "position_intent": "buy_to_open"},
        {"symbol": "QQQ260911C00605000", "ratio_qty": "1", "side": "sell", "position_intent": "sell_to_open"},
    ]


def test_cli_arguments_have_exactly_one_terminal_dry_run_guard() -> None:
    payload = build_debit_payload(
        long_symbol="IWM260911P00245000",
        short_symbol="IWM260911P00240000",
        debit=Decimal("0.90"),
        client_order_id="aft-cross-asset-dry-run",
    )
    arguments = build_cli_arguments(payload)
    validate_dry_run_arguments(arguments)
    assert arguments[:2] == ["order", "submit"]
    assert arguments[-1] == "--dry-run"
    assert arguments.count("--dry-run") == 1
    with pytest.raises(ValueError, match="DRY_RUN"):
        validate_dry_run_arguments(arguments[:-1])


def test_account_capability_output_is_public_and_requires_active_level_three() -> None:
    public = public_account_capabilities(
        {"status": "ACTIVE", "options_approved_level": 3, "options_trading_level": 3, "account_number": "secret"},
        {"suspend_trade": False, "api_key": "secret"},
    )
    assert public == {
        "paper": True,
        "status": "ACTIVE",
        "options_approved_level": 3,
        "options_trading_level": 3,
        "trading_blocked": False,
        "level_3_eligible": True,
    }


def test_dry_run_uses_most_recent_three_r_vertical_not_stale_selected_row() -> None:
    backtest = {
        "frozen_candidate": {"variant": "old_3r"},
        "untouched_oos": {"trades": [{"session": "2026-08-01", "long_symbol": "OLDL", "short_symbol": "OLDS"}]},
        "variants": {
            "old_3r": {"untouched_oos_trades": []},
            "new_3r": {"untouched_oos_trades": [{"session": "2026-09-01", "long_symbol": "NEWL", "short_symbol": "NEWS"}]},
        },
    }
    assert _historical_example(backtest) == ("NEWL", "NEWS", "new_3r")
