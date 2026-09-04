from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from afterimage.data.equity_selection import EquitySelectionError, select_equity_bracket

NOW = datetime(2026, 9, 4, 14, 0, 1, tzinfo=UTC)


def snapshot() -> dict[str, object]:
    return {
        "symbol": "QQQ",
        "latestQuote": {
            "bp": "99.98",
            "ap": "100.02",
            "t": "2026-09-04T14:00:00Z",
        },
    }


@pytest.mark.parametrize(("side", "expected_entry"), [("buy", "100.02"), ("sell", "99.98")])
def test_selector_builds_cost_aware_three_r_equity_bracket(side: str, expected_entry: str) -> None:
    selection = select_equity_bracket(
        "QQQ",
        side,
        snapshot(),
        NOW,
        stop_distance=Decimal(1),
        minimum_reward_risk=Decimal(3),
        modeled_round_trip_cost=Decimal("0.02"),
    )

    assert selection.passport.entry_price == Decimal(expected_entry)
    assert selection.passport.operational_ratio >= Decimal(3)
    assert selection.quote_age_seconds == Decimal(1)
    assert selection.relative_spread < Decimal("0.001")
    assert len(selection.quote_hash) == 64
    assert len(selection.market_quote_hash) == 64
    assert selection.quote_hash != selection.market_quote_hash


def test_selector_rebases_fractional_stop_and_slippage_costs_on_live_entry() -> None:
    selection = select_equity_bracket(
        "QQQ",
        "buy",
        snapshot(),
        NOW,
        stop_distance=Decimal(99),
        stop_distance_fraction=Decimal("0.01"),
        minimum_reward_risk=Decimal(3),
        modeled_round_trip_cost=Decimal("0.01"),
        modeled_round_trip_cost_fraction=Decimal("0.0002"),
    )

    assert selection.passport.entry_price == Decimal("100.02")
    assert selection.passport.stop_price == Decimal("99.01")
    assert selection.passport.modeled_costs == Decimal("0.030004")
    assert selection.passport.operational_ratio >= Decimal(3)


def test_selector_rejects_stale_or_crossed_quotes() -> None:
    with pytest.raises(EquitySelectionError, match="STALE_EQUITY_QUOTE"):
        select_equity_bracket(
            "QQQ",
            "buy",
            snapshot(),
            NOW,
            stop_distance=Decimal(1),
            minimum_reward_risk=Decimal(3),
            modeled_round_trip_cost=Decimal("0.02"),
            maximum_quote_age_seconds=Decimal("0.5"),
        )

    bad = snapshot()
    bad["latestQuote"] = {"bp": "100.02", "ap": "99.98", "t": "2026-09-04T14:00:00Z"}
    with pytest.raises(EquitySelectionError, match="CROSSED_EQUITY_QUOTE"):
        select_equity_bracket(
            "QQQ",
            "buy",
            bad,
            NOW,
            stop_distance=Decimal(1),
            minimum_reward_risk=Decimal(3),
            modeled_round_trip_cost=Decimal("0.02"),
        )
