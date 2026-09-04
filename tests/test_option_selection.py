from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from afterimage.contracts.models import CandidateEvent, ContractPolicy, StrategyIdentity
from afterimage.data.option_selection import OptionSelectionError, select_debit_vertical

NOW = datetime(2026, 9, 4, 14, 0, tzinfo=UTC)


def candidate() -> CandidateEvent:
    return CandidateEvent(
        candidate_id=UUID("00000000-0000-0000-0000-000000000001"),
        identity=StrategyIdentity(strategy_id="opening_range_failure_v1", strategy_version="1"),
        snapshot_id="snapshot",
        symbol="SPY",
        direction="bearish",
        signal_at=NOW,
        features={},
        permitted_structures=("put_debit_vertical",),
    )


def policy() -> ContractPolicy:
    return ContractPolicy(
        permitted_structures=("put_debit_vertical",),
        min_dte=2,
        max_dte=7,
        min_open_interest=100,
        max_relative_spread=Decimal("0.05"),
        max_quote_age_seconds=2,
    )


def contracts() -> list[dict[str, object]]:
    return [
        {
            "symbol": "SPY260908P00770000",
            "expiration_date": date(2026, 9, 8).isoformat(),
            "strike_price": "770",
            "type": "put",
            "open_interest": "800",
            "tradable": True,
        },
        {
            "symbol": "SPY260908P00764000",
            "expiration_date": date(2026, 9, 8).isoformat(),
            "strike_price": "764",
            "type": "put",
            "open_interest": "900",
            "tradable": True,
        },
    ]


def chain(timestamp: str = "2026-09-04T14:00:00Z") -> dict[str, object]:
    return {
        "snapshots": {
            "SPY260908P00770000": {
                "latestQuote": {"bp": 0.70, "ap": 0.72, "t": timestamp},
                "greeks": {"delta": -0.30},
            },
            "SPY260908P00764000": {
                "latestQuote": {"bp": 0.20, "ap": 0.21, "t": timestamp},
                "greeks": {"delta": -0.05},
            },
        }
    }


def test_selector_builds_a_liquid_synchronized_three_to_one_vertical() -> None:
    selected = select_debit_vertical(candidate(), contracts(), chain(), policy(), NOW)

    assert [leg.symbol for leg in selected.passport.legs] == [
        "SPY260908P00770000",
        "SPY260908P00764000",
    ]
    assert selected.passport.structural_ratio >= 3
    assert selected.passport.operational_ratio >= 3
    assert selected.relative_spread <= Decimal("0.05")
    assert selected.quote_age_seconds == 0
    assert len(selected.quote_hash) == 64


def test_selector_rejects_stale_or_future_quotes() -> None:
    with pytest.raises(OptionSelectionError, match="NO_POLICY_COMPLIANT_VERTICAL"):
        select_debit_vertical(
            candidate(), contracts(), chain("2026-09-04T13:59:00Z"), policy(), NOW
        )
    with pytest.raises(OptionSelectionError, match="NO_POLICY_COMPLIANT_VERTICAL"):
        select_debit_vertical(
            candidate(), contracts(), chain("2026-09-04T14:00:01Z"), policy(), NOW
        )
