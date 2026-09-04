from __future__ import annotations

from typing import Any, Literal

import pytest

from afterimage.agents.roles import AgentDesk
from afterimage.agents.schemas import AgentFinding, AgentReport, AgentRole, DeskReports
from afterimage.contracts.hashing import canonical_sha256
from afterimage.orchestration.coordinator import Coordinator


def agent_report(
    role: AgentRole, status: Literal["support", "challenge", "abstain"] = "support"
) -> AgentReport:
    return AgentReport(
        role=role,
        status=status,
        thesis="packet-bound",
        findings=(
            AgentFinding(
                claim="packet checked",
                evidence_keys=("snapshot.snapshot_id",),
                severity="support",
            ),
        ),
        falsifiers=("hash mismatch",),
        reason_code="TEST",
        model_id="exact-model",
        prompt_hash="p" * 64,
        response_hash=canonical_sha256(role.value),
        latency_ms=1,
    )


def test_every_agent_role_must_return_a_non_abstaining_report() -> None:
    complete = DeskReports(
        strategist=agent_report(AgentRole.STRATEGIST),
        regime_witness=agent_report(AgentRole.REGIME_WITNESS),
        options_witness=agent_report(AgentRole.OPTIONS_WITNESS),
        prosecutor=agent_report(AgentRole.PROSECUTOR, "challenge"),
    )

    for field, role in (
        ("strategist", AgentRole.STRATEGIST),
        ("regime_witness", AgentRole.REGIME_WITNESS),
        ("options_witness", AgentRole.OPTIONS_WITNESS),
        ("prosecutor", AgentRole.PROSECUTOR),
    ):
        reports = complete.model_copy(update={field: agent_report(role, "abstain")})
        assert f"AGENT_ABSTAIN_{role.value.upper()}" in Coordinator._agent_blocks(reports)


@pytest.mark.asyncio
async def test_desk_gives_each_witness_candidate_context_and_prosecutor_all_evidence() -> None:
    class CapturingGateway:
        def __init__(self) -> None:
            self.calls: list[tuple[AgentRole, dict[str, Any], bool]] = []

        async def complete(
            self,
            role: AgentRole,
            packet: dict[str, Any],
            output_type: type[AgentReport],
            deep: bool = False,
        ) -> AgentReport:
            self.calls.append((role, packet, deep))
            return output_type.model_validate(agent_report(role).model_dump())

    candidate = {
        "candidate_id": "candidate-1",
        "permitted_structures": ["call_debit_vertical"],
    }
    market = {"candidate": candidate, "snapshot": {"snapshot_id": "snapshot-1"}}
    regime = {"derived": {"realized_volatility": 0.2}}
    execution = {"contracts": [{"symbol": "SPY-option"}]}
    evidence = {"protocol": "sealed-twins-v1", "outcomes_visible": False}
    gateway = CapturingGateway()

    await AgentDesk(gateway).deliberate(market, regime, execution, evidence)  # type: ignore[arg-type]

    calls = {role: (packet, deep) for role, packet, deep in gateway.calls}
    assert calls[AgentRole.STRATEGIST][0]["market"]["candidate"] == candidate
    assert calls[AgentRole.REGIME_WITNESS][0]["candidate"] == candidate
    assert calls[AgentRole.OPTIONS_WITNESS][0]["candidate"] == candidate
    assert calls[AgentRole.OPTIONS_WITNESS][0]["strategy_adapter"]["asset_class"] == "options"
    prosecutor, prosecutor_deep = calls[AgentRole.PROSECUTOR]
    assert prosecutor["candidate"] == candidate
    assert [report["role"] for report in prosecutor["reports"]] == [
        "strategist",
        "regime_witness",
        "options_witness",
    ]
    assert prosecutor["source_packets"]["market"] == market
    assert prosecutor["source_packets"]["regime"] == regime
    assert prosecutor["source_packets"]["execution"] == execution
    assert calls[AgentRole.STRATEGIST][1] is True
    assert calls[AgentRole.REGIME_WITNESS][1] is False
    assert calls[AgentRole.OPTIONS_WITNESS][1] is False
    assert prosecutor_deep is True


def test_equity_adapter_is_preserved_without_option_assumptions() -> None:
    adapter = {"asset_class": "equity", "order_style": "limit"}

    assert AgentDesk._strategy_adapter({"strategy_adapter": adapter}, {}) == adapter
