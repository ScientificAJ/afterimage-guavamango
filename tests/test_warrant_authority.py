from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from afterimage.contracts.enums import DecisionStatus
from afterimage.contracts.hashing import canonical_sha256
from afterimage.contracts.models import (
    ExecutionIntent,
    OptionLeg,
    RiskDecision,
)
from afterimage.risk.warrant import WarrantAuthority, WarrantError
from afterimage.storage import Database


def intent_and_decision() -> tuple[ExecutionIntent, RiskDecision]:
    now = datetime(2026, 9, 4, tzinfo=UTC)
    legs = (
        OptionLeg(
            symbol="SPY260908P00650000",
            ratio_qty=1,
            side="buy",
            position_intent="buy_to_open",
            bid=Decimal("0.72"),
            ask=Decimal("0.75"),
            quote_at=now,
        ),
        OptionLeg(
            symbol="SPY260908P00644000",
            ratio_qty=1,
            side="sell",
            position_intent="sell_to_open",
            bid=Decimal("0.05"),
            ask=Decimal("0.07"),
            quote_at=now,
        ),
    )
    strategy_hash = canonical_sha256({"strategy": "opening_range_failure_v1"})
    evidence_hash = canonical_sha256({"sealed": "commit"})
    quote_hash = canonical_sha256([leg.model_dump(mode="json") for leg in legs])
    intent = ExecutionIntent(
        account_id_hash="a" * 64,
        strategy_manifest_hash=strategy_hash,
        evidence_commit_hash=evidence_hash,
        risk_decision_id=uuid4(),
        legs=legs,
        quantity=1,
        limit_price=Decimal("0.68"),
    )
    decision = RiskDecision(
        decision_id=intent.risk_decision_id,
        status=DecisionStatus.PASS,
        gates=(),
        quantity=1,
        modeled_max_loss=Decimal(48),
        strategy_manifest_hash=strategy_hash,
        evidence_commit_hash=evidence_hash,
        quote_hash=quote_hash,
        decided_at=now,
    )
    return intent, decision


def authority(tmp_path: Path, name: str) -> WarrantAuthority:
    database = Database(f"sqlite:///{tmp_path / (name + '.db')}")
    database.create()
    return WarrantAuthority(tmp_path / f"{name}.pem", database)


def test_verification_uses_authoritys_key_not_key_carried_by_warrant(tmp_path: Path) -> None:
    victim = authority(tmp_path, "victim")
    attacker = authority(tmp_path, "attacker")
    intent, decision = intent_and_decision()

    forged = attacker.mint(intent, decision)

    assert attacker.verify(forged)
    assert not victim.verify(forged)


@pytest.mark.parametrize(
    ("field", "replacement", "reason"),
    [
        ("strategy_manifest_hash", "d" * 64, "strategy"),
        ("evidence_commit_hash", "e" * 64, "evidence"),
        ("risk_decision_id", uuid4(), "decision"),
    ],
)
def test_mint_rejects_unbound_risk_decision(
    tmp_path: Path, field: str, replacement: object, reason: str
) -> None:
    auth = authority(tmp_path, "authority")
    intent, decision = intent_and_decision()
    changed = intent.model_copy(update={field: replacement})

    with pytest.raises(WarrantError, match=reason):
        auth.mint(changed, decision)


def test_mint_rejects_quote_vector_changed_after_risk(tmp_path: Path) -> None:
    auth = authority(tmp_path, "authority")
    intent, decision = intent_and_decision()
    changed_leg = intent.legs[0].model_copy(update={"ask": Decimal("9.99")})
    changed = intent.model_copy(update={"legs": (changed_leg, *intent.legs[1:])})

    with pytest.raises(WarrantError, match="quote"):
        auth.mint(changed, decision)


def test_existing_warrant_key_permissions_are_repaired(tmp_path: Path) -> None:
    auth = authority(tmp_path, "permissions")
    auth.key_path.chmod(0o644)

    authority(tmp_path, "permissions")

    assert auth.key_path.stat().st_mode & 0o777 == 0o600
