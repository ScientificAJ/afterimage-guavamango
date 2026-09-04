from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from afterimage.agents.schemas import AgentFinding, AgentReport, AgentRole, DeskReports
from afterimage.contracts.enums import DecisionStatus, EvidenceLevel
from afterimage.contracts.hashing import canonical_sha256
from afterimage.contracts.models import (
    AccountSnapshot,
    EvidenceMetrics,
    ExecutionIntent,
    OptionLeg,
    SessionEvent,
    VersionStamp,
)
from afterimage.data.fixtures import accepted_opening_range_records
from afterimage.evidence import EvidencePolicy, HistoricalRow, OutcomeVault, SealedTwinProtocol
from afterimage.risk import (
    RiskContext,
    RiskGovernor,
    WarrantAuthority,
    build_debit_vertical_passport,
)
from afterimage.storage import AuditLedger, Database, Repository
from afterimage.strategies.base import MarketFrame
from afterimage.strategies.registry import StrategyRegistry, default_registry
from afterimage.tournament import CandidateManifest, PromotionPolicy, TournamentRunner

from .state_machine import StateMachine


class Coordinator:
    def __init__(
        self,
        database: Database,
        registry: StrategyRegistry | None = None,
        signing_key_path: str | Path = ".afterimage/warrant-ed25519.pem",
    ) -> None:
        self.database = database
        self.database.create()
        self.repository = Repository(database)
        self.ledger = AuditLedger(database)
        self.registry = registry or default_registry()
        self.risk = RiskGovernor()
        self.warrants = WarrantAuthority(signing_key_path, database)

    @staticmethod
    def _historical_rows(accepted: bool) -> tuple[HistoricalRow, ...]:
        base = date(2024, 2, 1)
        rows = []
        for index in range(48):
            success = accepted or index % 5 == 0
            rows.append(
                HistoricalRow(
                    private_row_id=f"history-{index:03d}",
                    session_date=base + timedelta(days=index),
                    cluster_id=f"week-{index // 2:02d}",
                    features={
                        "range_high": 652.0 + (index % 7) * 0.02,
                        "range_low": 649.5 - (index % 5) * 0.02,
                        "range_width": 2.5 + (index % 3) * 0.03,
                        "close_0955": 651.4 + (index % 4) * 0.01,
                        "relative_volume": 1.0 + (index % 6) * 0.02,
                        "realized_volatility": 0.15 + (index % 8) * 0.002,
                    },
                    target_first=success,
                    return_r=Decimal(3) if success else Decimal(-1),
                    path=(Decimal(0), Decimal(1), Decimal(3))
                    if success
                    else (Decimal(0), Decimal(-1)),
                )
            )
        return tuple(rows)

    @staticmethod
    def _recorded_agents(candidate_id: str) -> DeskReports:
        def report(
            role: AgentRole,
            status: Literal["support", "challenge", "abstain"],
            thesis: str,
            severity: Literal["support", "warning", "fatal"] = "support",
        ) -> AgentReport:
            body = {"candidate": candidate_id, "role": role, "thesis": thesis}
            return AgentReport(
                role=role,
                status=status,
                thesis=thesis,
                findings=(
                    AgentFinding(
                        claim=thesis, evidence_keys=("candidate.features",), severity=severity
                    ),
                ),
                falsifiers=("The sealed outcomes fail the declared statistical gates.",),
                reason_code="RECORDED_DEMO_PACKET",
                model_id="recorded-demo",
                prompt_hash=canonical_sha256({"role": role}),
                response_hash=canonical_sha256(body),
                latency_ms=0,
            )

        return DeskReports(
            strategist=report(
                AgentRole.STRATEGIST,
                "support",
                "The re-entry is a falsifiable failed-breakout claim.",
            ),
            regime_witness=report(
                AgentRole.REGIME_WITNESS, "support", "The recorded regime packet is compatible."
            ),
            options_witness=report(
                AgentRole.OPTIONS_WITNESS,
                "support",
                "The defined-risk vertical passes the recorded liquidity screen.",
            ),
            prosecutor=report(
                AgentRole.PROSECUTOR, "challenge", "Evidence must still survive reveal.", "warning"
            ),
        )

    @staticmethod
    def _demo_account(at: datetime) -> AccountSnapshot:
        return AccountSnapshot(
            account_id_hash=canonical_sha256("verified-paper-account"),
            paper=True,
            status="ACTIVE",
            equity=Decimal(100000),
            cash=Decimal(100000),
            options_buying_power=Decimal(100000),
            options_approved_level=3,
            options_trading_level=3,
            trading_blocked=False,
            timestamp=at,
        )

    def _emit(
        self,
        machine: StateMachine,
        events: list[SessionEvent],
        name: str,
        payload: dict[str, Any],
        level: EvidenceLevel = EvidenceLevel.L0_INVARIANT,
    ) -> SessionEvent:
        event = machine.transition(name, payload, level)
        events.append(event)
        return event

    def run_demo(self, accepted: bool = True) -> dict[str, Any]:
        session_id = uuid4()
        strategy = self.registry.load("opening_range_failure_v1")
        machine = StateMachine(session_id, strategy.identity, self.repository, self.ledger)
        events: list[SessionEvent] = []
        records = accepted_opening_range_records()
        cutoff = records[-1].timestamp
        account = self._demo_account(cutoff)
        self._emit(
            machine,
            events,
            "precheck_passed",
            {"account": account.model_dump(mode="json"), "mode": "recorded-paper"},
        )
        self._emit(
            machine,
            events,
            "observe",
            {"symbol": "SPY", "strategy": strategy.identity.model_dump()},
        )
        frame = MarketFrame(
            symbol="SPY",
            cutoff=cutoff,
            records=records,
            context={"relative_volume": 1.18, "realized_volatility": 0.16},
        )
        snapshot = strategy.freeze(frame)
        self.repository.save_artifact(
            str(session_id),
            "frozen_snapshot",
            snapshot.model_dump(mode="json"),
            snapshot.snapshot_id,
        )
        self._emit(
            machine,
            events,
            "snapshot_frozen",
            {"snapshot_id": snapshot.snapshot_id},
            EvidenceLevel.L1_UNDERLYING_REPLAY,
        )
        candidate = strategy.detect(snapshot)
        if candidate is None:
            self._emit(machine, events, "no_signal", {"reason": "DETERMINISTIC_RULE_NOT_MET"})
            return self._summary(session_id, machine, events, None)
        self._emit(
            machine,
            events,
            "candidate_created",
            candidate.model_dump(mode="json"),
            EvidenceLevel.L1_UNDERLYING_REPLAY,
        )

        agents = self._recorded_agents(str(candidate.candidate_id))
        agents_hash = self.repository.save_artifact(
            str(session_id), "agent_reports", agents.model_dump(mode="json")
        )
        vault = OutcomeVault(self._historical_rows(accepted), salt=f"sealed-{session_id}")
        protocol = SealedTwinProtocol(vault, self.repository, EvidencePolicy())
        query = strategy.evidence_query(candidate).model_copy(update={"k": 40})
        versions = VersionStamp(
            strategy_id=strategy.identity.strategy_id,
            strategy_version=strategy.identity.strategy_version,
            model_id="recorded-demo",
            prompt_hash=agents_hash,
            data_snapshot_id=snapshot.snapshot_id,
        )
        dataset_hash = canonical_sha256(
            [row.model_dump(mode="json") for row in self._historical_rows(accepted)]
        )
        manifest = protocol.commit(str(session_id), query, versions, dataset_hash)
        self._emit(
            machine,
            events,
            "evidence_committed",
            {
                "commit_hash": manifest.commit_hash,
                "twin_count": len(manifest.twins),
                "outcomes_visible": False,
            },
            EvidenceLevel.L3_SEALED_TRIAL,
        )
        decision = protocol.reveal(str(session_id), manifest)
        self._emit(
            machine,
            events,
            "evidence_revealed",
            decision.model_dump(mode="json"),
            EvidenceLevel.L3_SEALED_TRIAL,
        )
        if decision.status != DecisionStatus.PASS:
            transition = (
                "insufficient_evidence"
                if decision.status == DecisionStatus.INSUFFICIENT_EVIDENCE
                else "rejected"
            )
            self._emit(
                machine,
                events,
                transition,
                {"reasons": decision.reasons},
                EvidenceLevel.L3_SEALED_TRIAL,
            )
            return self._summary(
                session_id,
                machine,
                events,
                {
                    "snapshot": snapshot.model_dump(mode="json"),
                    "candidate": candidate.model_dump(mode="json"),
                    "agents": agents.model_dump(mode="json"),
                    "evidence": decision.model_dump(mode="json"),
                    "tournament": self._demo_tournament(str(session_id), decision.metrics),
                },
            )

        quote_at = cutoff
        legs = (
            OptionLeg(
                symbol="SPY260908P00650000",
                ratio_qty=1,
                side="buy",
                position_intent="buy_to_open",
                bid="0.72",
                ask="0.75",
                quote_at=quote_at,
            ),
            OptionLeg(
                symbol="SPY260908P00644000",
                ratio_qty=1,
                side="sell",
                position_intent="sell_to_open",
                bid="0.05",
                ask="0.07",
                quote_at=quote_at,
            ),
        )
        payoff = build_debit_vertical_passport(
            "put_debit_vertical", legs, Decimal(6), Decimal("1.67"), Decimal("0.46")
        )
        strategy_hash = canonical_sha256(strategy.identity)
        quote_hash = canonical_sha256([leg.model_dump(mode="json") for leg in legs])
        risk_decision = self.risk.evaluate(
            RiskContext(
                account=account,
                evidence=decision,
                payoff=payoff,
                strategy_manifest_hash=strategy_hash,
                expected_account_id_hash=account.account_id_hash,
                quote_hash=quote_hash,
                observed_quote_age_seconds=Decimal("0.2"),
                observed_leg_skew_seconds=Decimal("0.1"),
                relative_spread=Decimal("0.04"),
            )
        )
        risk_payload = {
            "decision": risk_decision.model_dump(mode="json"),
            "payoff": payoff.model_dump(mode="json"),
        }
        if risk_decision.status != DecisionStatus.PASS:
            self._emit(machine, events, "rejected", risk_payload, EvidenceLevel.L3_SEALED_TRIAL)
            return self._summary(session_id, machine, events, risk_payload)
        self._emit(machine, events, "risk_approved", risk_payload, EvidenceLevel.L3_SEALED_TRIAL)
        intent = ExecutionIntent(
            account_id_hash=account.account_id_hash,
            strategy_manifest_hash=strategy_hash,
            evidence_commit_hash=manifest.commit_hash,
            risk_decision_id=risk_decision.decision_id,
            legs=legs,
            quantity=risk_decision.quantity,
            limit_price=payoff.entry_net_debit,
        )
        warrant = self.warrants.mint(intent, risk_decision)
        warrant_hash = self.repository.save_artifact(
            str(session_id), "warrant", warrant.model_dump(mode="json")
        )
        self._emit(
            machine,
            events,
            "warrant_minted",
            {"warrant": warrant.model_dump(mode="json"), "warrant_hash": warrant_hash},
            EvidenceLevel.L3_SEALED_TRIAL,
        )
        self._emit(
            machine,
            events,
            "submit_started",
            {"simulated": True, "intent_hash": warrant.intent_hash},
            EvidenceLevel.L4_SHADOW,
        )
        self._emit(
            machine,
            events,
            "working",
            {"simulated": True, "client_order_id": f"demo-{str(session_id)[:8]}"},
            EvidenceLevel.L4_SHADOW,
        )
        self._emit(
            machine,
            events,
            "filled",
            {"simulated": True, "fill_debit": str(payoff.entry_net_debit)},
            EvidenceLevel.L4_SHADOW,
        )
        self._emit(
            machine,
            events,
            "exit_started",
            {"reason": "TARGET", "simulated": True},
            EvidenceLevel.L4_SHADOW,
        )
        self._emit(
            machine,
            events,
            "closed",
            {"broker_pnl": "93.00", "conservative_modeled_pnl": "89.00", "simulated": True},
            EvidenceLevel.L4_SHADOW,
        )
        self._emit(
            machine,
            events,
            "autopsy_saved",
            {
                "audit_valid": self.ledger.verify(str(session_id)).valid,
                "claim": "recorded demonstration; not live P&L",
            },
            EvidenceLevel.L4_SHADOW,
        )

        extras = {
            "snapshot": snapshot.model_dump(mode="json"),
            "candidate": candidate.model_dump(mode="json"),
            "agents": agents.model_dump(mode="json"),
            "evidence": decision.model_dump(mode="json"),
            "payoff": payoff.model_dump(mode="json"),
            "risk": risk_decision.model_dump(mode="json"),
            "warrant": warrant.model_dump(mode="json"),
            "tournament": self._demo_tournament(str(session_id), decision.metrics),
        }
        return self._summary(session_id, machine, events, extras)

    def _demo_tournament(self, session_id: str, metrics: EvidenceMetrics) -> dict[str, Any]:
        start = datetime(2026, 7, 1, tzinfo=UTC)
        end = datetime(2026, 9, 1, tzinfo=UTC)
        candidates = tuple(
            CandidateManifest(
                identity=self.registry.load(strategy_id).identity,
                parameters={"source": "recorded-demo"},
                code_revision="uncommitted-implementation",
                dataset_hash="recorded-demo-dataset",
                training_end=start - timedelta(days=7),
                embargo_sessions=5,
                final_holdout_start=start,
                final_holdout_end=end,
                fee_per_contract=Decimal(0),
                slippage_per_leg=Decimal("0.01"),
                baselines=("random_direction", "buy_and_hold_underlying"),
            )
            for strategy_id in (
                "opening_range_failure_v1",
                "momentum_continuation_v1",
                "volatility_dislocation_v1",
            )
        )
        runner = TournamentRunner(self.repository)
        policy = PromotionPolicy()
        seal = runner.preregister(session_id, candidates, policy, "recorded-holdout")
        results = {}
        for index, candidate in enumerate(candidates):
            candidate_hash = canonical_sha256(candidate)
            if index == 0:
                results[candidate_hash] = metrics
            else:
                results[candidate_hash] = metrics.model_copy(
                    update={
                        "expected_value_r": Decimal("0.02") - Decimal(index) / Decimal(10),
                        "lower_confidence_bound": Decimal("0.20"),
                    }
                )
        result = runner.reveal(session_id, seal, candidates, policy, results)
        return result.model_dump(mode="json")

    def _summary(
        self,
        session_id: UUID,
        machine: StateMachine,
        events: list[SessionEvent],
        extras: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload = {
            "session_id": str(session_id),
            "state": machine.state.value,
            "events": [event.model_dump(mode="json") for event in events],
            "audit": self.ledger.verify(str(session_id)).__dict__,
            "mode": "recorded-demo",
        }
        if extras:
            payload.update(extras)
        self.repository.save_artifact(str(session_id), "session_summary", payload)
        return payload
