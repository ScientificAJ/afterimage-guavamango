from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from afterimage.contracts.hashing import canonical_sha256
from afterimage.contracts.models import ExecutionIntent, RiskDecision
from afterimage.risk.payoff import build_equity_bracket_passport
from afterimage.risk.sizing import size_equity_position
from afterimage.risk.warrant import WarrantAuthority
from afterimage.storage import Database


def equity_intent() -> ExecutionIntent:
    return ExecutionIntent(
        intent_id=UUID("00000000-0000-0000-0000-000000000011"),
        account_id_hash="a" * 64,
        strategy_manifest_hash="b" * 64,
        evidence_commit_hash="c" * 64,
        risk_decision_id=UUID("00000000-0000-0000-0000-000000000012"),
        asset_class="equity",
        symbol="QQQ",
        side="buy",
        quantity=25,
        limit_price=Decimal("100.00"),
        take_profit_price=Decimal("103.40"),
        stop_price=Decimal("99.00"),
        order_class="bracket",
    )


def test_equity_passport_measures_three_to_one_after_costs() -> None:
    passport = build_equity_bracket_passport(
        symbol="QQQ",
        side="buy",
        entry_price=Decimal("100.00"),
        stop_price=Decimal("99.00"),
        target_price=Decimal("103.40"),
        modeled_round_trip_cost=Decimal("0.10"),
    )

    assert passport.asset_class == "equity"
    assert passport.symbol == "QQQ"
    assert passport.stressed_max_loss == Decimal("1.10")
    assert passport.operational_target_profit == Decimal("3.30")
    assert passport.operational_ratio == Decimal(3)


def test_equity_intent_requires_a_complete_bracket_and_no_option_legs() -> None:
    intent = equity_intent()

    assert intent.asset_class == "equity"
    assert intent.order_class == "bracket"
    assert intent.legs == ()

    with pytest.raises(ValidationError):
        equity_intent().model_copy(update={"stop_price": None}).model_validate(
            equity_intent().model_copy(update={"stop_price": None}).model_dump()
        )


def test_equity_warrant_binds_the_exact_symbol_side_and_bracket(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'equity-warrant.db'}")
    database.create()
    intent = equity_intent()
    decision = RiskDecision(
        decision_id=intent.risk_decision_id,
        status="PASS",
        gates=(),
        quantity=intent.quantity,
        modeled_max_loss=Decimal("27.50"),
        strategy_manifest_hash=intent.strategy_manifest_hash,
        evidence_commit_hash=intent.evidence_commit_hash,
        quote_hash=canonical_sha256(intent.quote_material()),
        decided_at=datetime.now(UTC),
    )

    warrant = WarrantAuthority(tmp_path / "equity.pem", database).mint(intent, decision)

    assert warrant.intent.asset_class == "equity"
    assert warrant.intent.symbol == "QQQ"
    assert warrant.intent.take_profit_price == Decimal("103.40")


def test_equity_sizing_caps_both_loss_and_notional() -> None:
    assert (
        size_equity_position(
            stressed_loss_per_share=Decimal("1.10"),
            share_price=Decimal(100),
            equity=Decimal(100000),
            fixed_loss_cap=Decimal(500),
            notional_cap=Decimal(10000),
        )
        == 100
    )
    assert (
        size_equity_position(
            stressed_loss_per_share=Decimal(10),
            share_price=Decimal(100),
            equity=Decimal(100000),
            fixed_loss_cap=Decimal(500),
            notional_cap=Decimal(10000),
        )
        == 50
    )


def test_equity_exit_intent_supports_a_warrant_bound_market_close() -> None:
    intent = ExecutionIntent(
        account_id_hash="a" * 64,
        strategy_manifest_hash="b" * 64,
        evidence_commit_hash="c" * 64,
        risk_decision_id=UUID("00000000-0000-0000-0000-000000000013"),
        asset_class="equity",
        symbol="QQQ",
        side="sell",
        quantity=25,
        limit_price=Decimal(0),
        order_class="simple",
        order_type="market",
        reduce_only=True,
    )

    assert intent.take_profit_price is None
    assert intent.stop_price is None
    assert intent.quote_material()["reduce_only"] is True
