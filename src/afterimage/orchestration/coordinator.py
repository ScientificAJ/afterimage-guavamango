from __future__ import annotations

import hashlib
import inspect
import os
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from afterimage.agents.roles import AgentDesk
from afterimage.agents.schemas import AgentFinding, AgentReport, AgentRole, DeskReports
from afterimage.config import RuntimeConfig, load_runtime_config
from afterimage.contracts.enums import DecisionStatus, EvidenceLevel, SessionState
from afterimage.contracts.hashing import canonical_sha256
from afterimage.contracts.models import (
    AccountSnapshot,
    BlindTwin,
    EvidenceMetrics,
    ExecutionIntent,
    ExecutionWarrant,
    ExitPlan,
    FrozenSnapshot,
    MarketRecord,
    OptionLeg,
    RevealedOutcome,
    SessionEvent,
    StrategyIdentity,
    TournamentEntry,
    VersionStamp,
)
from afterimage.data.equity_selection import EquitySelectionError, select_equity_bracket
from afterimage.data.fixtures import accepted_opening_range_records, accepted_option_frames
from afterimage.data.option_replay import OptionReplay
from afterimage.data.option_selection import OptionSelectionError, select_debit_vertical
from afterimage.evidence import (
    EvidencePolicy,
    HistoricalRow,
    OutcomeVault,
    SealedTwinProtocol,
    evaluate_evidence,
)
from afterimage.execution.client_ids import client_order_id
from afterimage.execution.lifecycle import (
    EXIT_ACTIONS,
    AmbiguousSubmission,
    ExecutionError,
    ExecutionService,
    authorize_equity_position_exit,
    authorize_position_exit,
)
from afterimage.execution.reconciler import Reconciler
from afterimage.execution.watchdog import PositionWatchdog, WatchdogAction
from afterimage.research import ResearchDataset, ResearchDatasetError, load_research_dataset
from afterimage.risk import (
    RiskContext,
    RiskGovernor,
    WarrantAuthority,
    build_debit_vertical_passport,
)
from afterimage.storage import AuditLedger, Database, Repository
from afterimage.strategies.base import MarketFrame
from afterimage.strategies.deployment import (
    DeploymentEvidenceError,
    DeploymentManifest,
    load_deployment_evidence,
)
from afterimage.strategies.registry import StrategyRegistry, configured_registry
from afterimage.strategies.socket import StrategyRuntimeSpec
from afterimage.tournament import (
    CandidateManifest,
    TournamentRunner,
    build_entry,
    select_champion,
)

from .state_machine import StateMachine

ET = ZoneInfo("America/New_York")


class Coordinator:
    def __init__(
        self,
        database: Database,
        registry: StrategyRegistry | None = None,
        signing_key_path: str | Path = ".afterimage/warrant-ed25519.pem",
        config: RuntimeConfig | None = None,
    ) -> None:
        self.database = database
        self.database.create()
        self.repository = Repository(database)
        self.ledger = AuditLedger(database)
        self.config = config or load_runtime_config()
        self.registry = registry or configured_registry(self.config)
        configured = {
            f"{item.strategy_id}@{item.strategy_version}"
            for item in self.config.strategies.values()
        }
        if set(self.registry.list()) != configured:
            raise RuntimeError("CONFIG_STRATEGY_REGISTRY_MISMATCH")
        self.risk = RiskGovernor(self.config.risk)
        self.promotion_policy = self.config.tournament
        self.warrants = WarrantAuthority(signing_key_path, database)

    def resolve_strategy(self, strategy_id: str | None = None) -> tuple[Any, StrategyRuntimeSpec]:
        selected_id = (
            strategy_id
            or os.getenv("AFTERIMAGE_ACTIVE_STRATEGY")
            or "shadow_clock_shock_reversal_v1"
        )
        configured = self.config.strategy(selected_id)
        strategy = self.registry.load(selected_id, configured.strategy_version)
        return strategy, StrategyRuntimeSpec.from_config(configured)

    @staticmethod
    def _timeframe_delta(value: str) -> timedelta:
        units = {
            "Min": "minutes",
            "Hour": "hours",
            "Day": "days",
        }
        for suffix, keyword in units.items():
            if value.endswith(suffix) and value[: -len(suffix)].isdigit():
                amount = int(value[: -len(suffix)])
                if amount > 0:
                    return timedelta(**{keyword: amount})
        raise ValueError(f"BAR_TIMEFRAME_UNSUPPORTED:{value}")

    @staticmethod
    def _bar_available(timestamp: datetime, cutoff: datetime, timeframe: str) -> bool:
        if timeframe == "1Day":
            bar_session = timestamp.astimezone(ET).date()
            local_cutoff = cutoff.astimezone(ET)
            return bar_session < local_cutoff.date() or (
                bar_session == local_cutoff.date() and local_cutoff.time() >= time(16)
            )
        return timestamp + Coordinator._timeframe_delta(timeframe) <= cutoff

    @staticmethod
    def _snapshot_dedup_key(snapshot_id: str, timeframe: str, broker_now: datetime) -> str:
        if timeframe != "1Day":
            return snapshot_id
        return canonical_sha256(
            {
                "snapshot_id": snapshot_id,
                "execution_session": broker_now.astimezone(ET).date().isoformat(),
            }
        )

    @staticmethod
    def _market_symbols(
        runtime_spec: StrategyRuntimeSpec, requested_symbol: str | None
    ) -> tuple[str, ...]:
        if runtime_spec.market_scope == "universe":
            if (
                requested_symbol is not None
                and requested_symbol.upper() not in runtime_spec.symbols
            ):
                raise ValueError(f"SYMBOL_OUTSIDE_STRATEGY_UNIVERSE:{requested_symbol.upper()}")
            return runtime_spec.symbols
        return ((requested_symbol or runtime_spec.symbols[0]).upper(),)

    @staticmethod
    def _strategy_implementation_hash(strategy: Any) -> str:
        source_file = inspect.getsourcefile(type(strategy))
        if source_file is None:
            raise RuntimeError("STRATEGY_IMPLEMENTATION_SOURCE_UNAVAILABLE")
        return hashlib.sha256(Path(source_file).read_bytes()).hexdigest()

    def _strategy_authority_hash(self, strategy: Any) -> str:
        configured = self.config.strategy(strategy.identity.strategy_id)
        return canonical_sha256(
            {
                "identity": strategy.identity.model_dump(mode="json"),
                "strategy_config_hash": configured.source_hash,
                "strategy_implementation_hash": self._strategy_implementation_hash(strategy),
                "runtime_config_manifest_hash": self.config.manifest_hash,
                "risk_policy_version": self.config.risk.policy_version,
            }
        )

    def _deployment_evidence(self, strategy: Any) -> tuple[Any, DeploymentManifest]:
        configured = self.config.strategy(strategy.identity.strategy_id)
        evidence = configured.payload.get("evidence")
        if not isinstance(evidence, dict) or not evidence.get("manifest_path"):
            raise DeploymentEvidenceError("DEPLOYMENT_MANIFEST_NOT_CONFIGURED")
        return load_deployment_evidence(
            str(evidence["manifest_path"]),
            strategy_id=configured.strategy_id,
            strategy_version=configured.strategy_version,
            strategy_authority_hash=self._strategy_authority_hash(strategy),
            strategy_config_hash=configured.source_hash,
            strategy_source_hash=self._strategy_implementation_hash(strategy),
        )

    @staticmethod
    def _deployment_agent_packet(
        manifest: DeploymentManifest, strategy_config: dict[str, Any]
    ) -> dict[str, Any]:
        """Expose the admitted aggregate evidence and rule without revealing future rows."""

        contract = {
            key: strategy_config[key]
            for key in ("signal", "shadow_clock", "execution", "risk", "costs")
            if isinstance(strategy_config.get(key), dict)
        }
        return {
            "protocol": "hash-bound-deployment-evidence-v1",
            "manifest_hash": manifest.manifest_hash,
            "research_result_hash": manifest.research_result_hash,
            "aggregate_research_metrics_visible": True,
            "individual_outcomes_visible": False,
            "outcomes_visible": False,
            "deployment_evidence": {
                "admitted": manifest.admitted,
                "required_gates": manifest.required_gates,
                "metrics": manifest.metrics.model_dump(mode="json"),
                "limitations": list(manifest.limitations),
            },
            "strategy_contract": contract,
        }

    @staticmethod
    def _agent_snapshot_packet(snapshot: FrozenSnapshot) -> dict[str, Any]:
        records = [record.model_dump(mode="json") for record in snapshot.records]
        return {
            "snapshot_id": snapshot.snapshot_id,
            "cutoff": snapshot.cutoff.isoformat(),
            "identity": snapshot.identity.model_dump(mode="json"),
            "features": snapshot.features,
            "provenance": snapshot.provenance,
            "record_count": len(records),
            "records_sha256": canonical_sha256(records),
        }

    @staticmethod
    def _live_research_evidence(
        strategy_id: str, symbol: str
    ) -> tuple[tuple[HistoricalRow, ...], str, dict[str, Any]]:
        path = Path(
            os.getenv(
                "AFTERIMAGE_RESEARCH_DATASET_PATH",
                ".afterimage/research/spy-real-v1.json",
            )
        )
        dataset = load_research_dataset(path)
        if dataset.symbol != symbol:
            raise ResearchDatasetError("RESEARCH_SYMBOL_MISMATCH")
        evaluation = dataset.training.evaluations.get(strategy_id)
        if evaluation is None or not evaluation.rows:
            raise ResearchDatasetError("RESEARCH_STRATEGY_EVIDENCE_MISSING")
        return (
            evaluation.rows,
            dataset.dataset_hash,
            {
                "source": dataset.source,
                "feed": dataset.feed,
                "timeframe": dataset.timeframe,
                "partition": "training",
                "partition_start": dataset.training.start.isoformat(),
                "partition_end": dataset.training.end.isoformat(),
                "partition_source_hash": dataset.training.source_hash,
                "record_count": len(dataset.training.records),
                "strategy_signal_count": len(evaluation.rows),
                "result_type": "underlying-path R proxy; not option or broker P&L",
            },
        )

    @staticmethod
    def _historical_rows() -> tuple[HistoricalRow, ...]:
        """Immutable mixed-outcome fixture; selection changes, outcomes never do."""
        current = date(2024, 2, 1)
        session_dates: list[date] = []
        while len(session_dates) < 96:
            if current.weekday() < 5:
                session_dates.append(current)
            current += timedelta(days=1)
        rows = []
        for index, session_date in enumerate(session_dates):
            good_regime = index < 48
            local_index = index if good_regime else index - 48
            success = local_index % 4 != 0 if good_regime else local_index % 6 == 0
            relative_volume = (
                1.18 + ((local_index % 7) - 3) * 0.01
                if good_regime
                else 0.45 + ((local_index % 7) - 3) * 0.01
            )
            realized_volatility = (
                0.16 + ((local_index % 5) - 2) * 0.002
                if good_regime
                else 0.45 + ((local_index % 5) - 2) * 0.004
            )
            rows.append(
                HistoricalRow(
                    private_row_id=f"history-{index:03d}",
                    session_date=session_date,
                    cluster_id=f"week-{index // 2:02d}",
                    features={
                        "range_high": 652.0 + (index % 7) * 0.02,
                        "range_low": 649.5 - (index % 5) * 0.02,
                        "range_width": 2.5 + (index % 3) * 0.03,
                        "close_0955": 651.4 + (index % 4) * 0.01,
                        "relative_volume": relative_volume,
                        "realized_volatility": realized_volatility,
                    },
                    target_first=success,
                    return_r=Decimal(3) if success else Decimal(-1),
                    placebo_return_r=(Decimal("0.05") if local_index % 2 else Decimal("-0.08")),
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
            account_id_hash=canonical_sha256("recorded-fixture-account"),
            paper=True,
            status="ACTIVE",
            equity=Decimal(100000),
            last_equity=Decimal(100000),
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

    @staticmethod
    def _path_bands(outcomes: tuple[RevealedOutcome, ...]) -> list[dict[str, int | str]]:
        paths = [outcome.path for outcome in outcomes if outcome.path]
        if not paths:
            return []
        bands: list[dict[str, int | str]] = []
        for step in range(max(len(path) for path in paths)):
            values = sorted(path[min(step, len(path) - 1)] for path in paths)
            midpoint = len(values) // 2
            median = (
                values[midpoint]
                if len(values) % 2
                else (values[midpoint - 1] + values[midpoint]) / Decimal(2)
            )
            bands.append(
                {
                    "step": step,
                    "low": str(values[0]),
                    "median": str(median),
                    "high": str(values[-1]),
                }
            )
        return bands

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
        exit_plan = strategy.exit_plan(candidate)

        agents = self._recorded_agents(str(candidate.candidate_id))
        agents_hash = self.repository.save_artifact(
            str(session_id), "agent_reports", agents.model_dump(mode="json")
        )
        historical_rows = self._historical_rows()
        vault = OutcomeVault(historical_rows, salt="recorded-historical-v1")
        protocol = SealedTwinProtocol(vault, self.repository, EvidencePolicy())
        query = strategy.evidence_query(candidate).model_copy(update={"k": 40})
        if not accepted:
            rejected_values = list(query.feature_values)
            rejected_values[-2:] = [0.45, 0.45]
            query = query.model_copy(update={"feature_values": tuple(rejected_values)})
        versions = VersionStamp(
            strategy_id=strategy.identity.strategy_id,
            strategy_version=strategy.identity.strategy_version,
            model_id="recorded-demo",
            prompt_hash=agents_hash,
            data_snapshot_id=snapshot.snapshot_id,
        )
        dataset_hash = canonical_sha256([row.model_dump(mode="json") for row in historical_rows])
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
        evidence_paths = self._path_bands(vault.reveal(twin.twin_id for twin in manifest.twins))
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
                    "agent_provenance": {
                        "mode": "recorded-fixture",
                        "live_inference": False,
                        "model_id": "recorded-demo",
                    },
                    "evidence": decision.model_dump(mode="json"),
                    "evidence_paths": evidence_paths,
                    "exit_plan": exit_plan.model_dump(mode="json"),
                    "dataset_hash": dataset_hash,
                    "tournament": self._recorded_fixture_tournament(),
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
        strategy_hash = self._strategy_authority_hash(strategy)
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
                realized_daily_pnl=Decimal(0),
                worst_open_loss=Decimal(0),
                high_water_equity=account.equity,
                entry_cutoff_passed=False,
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
        option_replay = OptionReplay(slippage_per_leg=Decimal("0.01")).first_passage(
            accepted_option_frames(),
            target_profit=payoff.operational_target_profit,
            stop_loss=payoff.operational_stop_loss,
        )
        self._emit(
            machine,
            events,
            "shadow_ready",
            {
                "audit_valid": self.ledger.verify(str(session_id)).valid,
                "order_sent": False,
                "execution_enabled": False,
                "option_replay": option_replay.model_dump(mode="json"),
                "claim": "recorded replay only; no broker fill or broker P&L",
            },
            EvidenceLevel.L2_OPTION_QUOTE_REPLAY,
        )

        extras = {
            "snapshot": snapshot.model_dump(mode="json"),
            "candidate": candidate.model_dump(mode="json"),
            "agents": agents.model_dump(mode="json"),
            "evidence": decision.model_dump(mode="json"),
            "evidence_paths": evidence_paths,
            "payoff": payoff.model_dump(mode="json"),
            "risk": risk_decision.model_dump(mode="json"),
            "warrant": warrant.model_dump(mode="json"),
            "dataset_hash": dataset_hash,
            "option_replay": option_replay.model_dump(mode="json"),
            "exit_plan": exit_plan.model_dump(mode="json"),
            "watchdog": {
                "status": "armed-after-fill",
                "target_profit": str(payoff.operational_target_profit),
                "stop_loss": str(payoff.operational_stop_loss),
                "exit_at": exit_plan.exit_at.isoformat(),
                "maximum_quote_age_seconds": str(self.config.risk.maximum_quote_age_seconds),
            },
            "agent_provenance": {
                "mode": "recorded-fixture",
                "live_inference": False,
                "model_id": "recorded-demo",
            },
            "tournament": self._recorded_fixture_tournament(),
        }
        return self._summary(session_id, machine, events, extras)

    @staticmethod
    def _analysis_date(clock: dict[str, Any], signal_at: time = time(10, 0)) -> date:
        timestamp = datetime.fromisoformat(str(clock["timestamp"]))
        local = timestamp.astimezone(ET)
        analysis_date = local.date()
        if local.time() < signal_at:
            analysis_date -= timedelta(days=1)
        while analysis_date.weekday() >= 5:
            analysis_date -= timedelta(days=1)
        return analysis_date

    @staticmethod
    def _market_records(
        symbol: str, bars: list[dict[str, Any]], received_at: datetime
    ) -> tuple[MarketRecord, ...]:
        records = []
        for bar in bars:
            timestamp = datetime.fromisoformat(str(bar["t"]))
            records.append(
                MarketRecord(
                    symbol=symbol,
                    timestamp=timestamp,
                    received_at=received_at,
                    source="alpaca-cli",
                    feed=os.getenv("AFTERIMAGE_STOCK_FEED", "iex"),
                    kind="bar",
                    values={
                        "open": bar["o"],
                        "high": bar["h"],
                        "low": bar["l"],
                        "close": bar["c"],
                        "volume": bar["v"],
                    },
                )
            )
        return tuple(sorted(records, key=lambda record: record.timestamp))

    @staticmethod
    def _live_context(
        records: tuple[MarketRecord, ...], timeframe: str = "5Min"
    ) -> dict[str, float]:
        by_symbol: dict[str, list[MarketRecord]] = {}
        for record in records:
            by_symbol.setdefault(record.symbol, []).append(record)
        returns: list[float] = []
        volume_ratios: list[float] = []
        for rows in by_symbol.values():
            ordered = sorted(rows, key=lambda item: item.timestamp)
            closes = [float(record.values["close"]) for record in ordered]
            volumes = [float(record.values["volume"]) for record in ordered]
            returns.extend(
                (closes[index] / closes[index - 1]) - 1
                for index in range(1, len(closes))
                if closes[index - 1] > 0
            )
            midpoint = max(1, len(volumes) // 2)
            first = sum(volumes[:midpoint]) / max(1, len(volumes[:midpoint]))
            second = sum(volumes[midpoint:]) / max(1, len(volumes[midpoint:]))
            if first > 0:
                volume_ratios.append(second / first)
        relative_volume = sum(volume_ratios) / len(volume_ratios) if volume_ratios else 0.0
        if timeframe == "1Day":
            annual_periods = 252.0
        else:
            interval_seconds = Coordinator._timeframe_delta(timeframe).total_seconds()
            annual_periods = 252.0 * 6.5 * 60.0 * 60.0 / interval_seconds
        realized_volatility = (
            (sum(value * value for value in returns) / len(returns)) ** 0.5 * annual_periods**0.5
            if returns
            else 0.0
        )
        return {
            "relative_volume": round(relative_volume, 8),
            "realized_volatility": round(realized_volatility, 8),
        }

    @staticmethod
    def _agent_blocks(reports: DeskReports) -> tuple[str, ...]:
        all_reports = (
            reports.strategist,
            reports.regime_witness,
            reports.options_witness,
            reports.prosecutor,
        )
        reasons = [
            f"AGENT_FATAL_{report.role.value.upper()}"
            for report in all_reports
            if any(finding.severity == "fatal" for finding in report.findings)
        ]
        reasons.extend(
            f"AGENT_ABSTAIN_{report.role.value.upper()}"
            for report in all_reports
            if report.status == "abstain"
        )
        return tuple(reasons)

    async def run_live_cycle(
        self,
        gateway: Any,
        desk: AgentDesk,
        expected_account_id_hash: str,
        symbol: str | None = None,
        strategy_id: str | None = None,
        execute: bool = False,
    ) -> dict[str, Any]:
        """Run one live paper cycle; execution requires two explicit independent gates."""
        session_id = uuid4()
        strategy, runtime_spec = self.resolve_strategy(strategy_id)
        market_symbols = self._market_symbols(runtime_spec, symbol)
        primary_symbol = symbol.upper() if symbol is not None else market_symbols[0]
        machine = StateMachine(session_id, strategy.identity, self.repository, self.ledger)
        events: list[SessionEvent] = []
        checked = await gateway.preflight(expected_account_id_hash)
        self._emit(
            machine,
            events,
            "precheck_passed",
            {
                "account": checked.account.model_dump(mode="json"),
                "transport": checked.capabilities.get("transport", "alpaca"),
                "execution": checked.capabilities.get("execution", "disabled"),
            },
            EvidenceLevel.L4_SHADOW,
        )
        analysis_date = self._analysis_date(checked.clock, runtime_spec.signal_at)
        high_water_equity = self.repository.observe_account_equity(
            checked.account.account_id_hash,
            analysis_date,
            checked.account.equity,
        )
        cutoff = datetime.combine(analysis_date, runtime_spec.signal_at, ET).astimezone(UTC)
        broker_now = datetime.fromisoformat(str(checked.clock["timestamp"]))
        self._emit(
            machine,
            events,
            "observe",
            {
                "symbols": list(market_symbols),
                "primary_symbol": primary_symbol,
                "analysis_date": analysis_date.isoformat(),
            },
            EvidenceLevel.L4_SHADOW,
        )
        if broker_now < cutoff:
            self._emit(
                machine,
                events,
                "no_signal",
                {
                    "reason": "SIGNAL_WINDOW_INCOMPLETE",
                    "available_at": cutoff.isoformat(),
                    "order_sent": False,
                    "downstream_inference_skipped": True,
                },
                EvidenceLevel.L4_SHADOW,
            )
            return self._summary(
                session_id,
                machine,
                events,
                {"broker": {"connected": True, "order_sent": False}},
                mode="live-shadow",
            )
        start_date = analysis_date - timedelta(days=runtime_spec.lookback_calendar_days - 1)
        start = datetime.combine(start_date, runtime_spec.session_start, ET).astimezone(UTC)
        end = cutoff
        collected_records: list[MarketRecord] = []
        for market_symbol in market_symbols:
            bars = await gateway.stock_bars(market_symbol, start, end, runtime_spec.bar_timeframe)
            collected_records.extend(
                self._market_records(market_symbol, bars, checked.account.timestamp)
            )
        records = tuple(
            sorted(collected_records, key=lambda record: (record.timestamp, record.symbol))
        )
        records = tuple(
            record
            for record in records
            if self._bar_available(record.timestamp, cutoff, runtime_spec.bar_timeframe)
        )
        if not records:
            self._emit(
                machine,
                events,
                "no_signal",
                {"reason": "NO_ALPACA_BARS", "order_sent": False},
                EvidenceLevel.L4_SHADOW,
            )
            return self._summary(
                session_id,
                machine,
                events,
                {"broker": {"connected": True, "order_sent": False}},
                mode="live-shadow",
            )
        context = self._live_context(records, runtime_spec.bar_timeframe)
        frame = MarketFrame(symbol=primary_symbol, cutoff=cutoff, records=records, context=context)
        snapshot = strategy.freeze(frame)
        snapshot_dedup_key = self._snapshot_dedup_key(
            snapshot.snapshot_id, runtime_spec.bar_timeframe, broker_now
        )
        already_analyzed = self.repository.get_artifact("live_snapshot_seen", snapshot_dedup_key)
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
            {"snapshot_id": snapshot.snapshot_id, "record_count": len(records)},
            EvidenceLevel.L4_SHADOW,
        )
        if already_analyzed is not None:
            self._emit(
                machine,
                events,
                "no_signal",
                {
                    "reason": "SNAPSHOT_ALREADY_ANALYZED",
                    "order_sent": False,
                    "downstream_inference_skipped": True,
                },
                EvidenceLevel.L4_SHADOW,
            )
            return self._summary(
                session_id,
                machine,
                events,
                {
                    "snapshot": snapshot.model_dump(mode="json"),
                    "agent_provenance": {
                        "mode": "not-invoked-duplicate-snapshot",
                        "live_inference": False,
                        "models": [],
                    },
                    "broker": {
                        "connected": True,
                        "transport": checked.capabilities.get("transport", "alpaca"),
                        "execution_enabled": False,
                        "order_sent": False,
                        "positions": len(checked.positions),
                        "open_orders": len(checked.open_orders),
                    },
                    "market_data": {
                        "source": "alpaca-cli",
                        "analysis_date": analysis_date.isoformat(),
                        "bar_count": len(records),
                        "contract_count": 0,
                        "chain_snapshot_count": 0,
                        "downstream_fetch_skipped": True,
                    },
                },
                mode="live-shadow",
            )
        self.repository.save_artifact(
            str(session_id),
            "live_snapshot_seen",
            {
                "snapshot_id": snapshot.snapshot_id,
                "strategy": strategy.identity.model_dump(mode="json"),
            },
            snapshot_dedup_key,
        )
        candidate = strategy.detect(snapshot)
        if candidate is None:
            self._emit(
                machine,
                events,
                "no_signal",
                {
                    "reason": "DETERMINISTIC_RULE_NOT_MET",
                    "order_sent": False,
                    "downstream_inference_skipped": True,
                },
                EvidenceLevel.L4_SHADOW,
            )
            return self._summary(
                session_id,
                machine,
                events,
                {
                    "snapshot": snapshot.model_dump(mode="json"),
                    "agent_provenance": {
                        "mode": "not-invoked-no-signal",
                        "live_inference": False,
                        "models": [],
                    },
                    "broker": {
                        "connected": True,
                        "transport": checked.capabilities.get("transport", "alpaca"),
                        "execution_enabled": False,
                        "order_sent": False,
                        "positions": len(checked.positions),
                        "open_orders": len(checked.open_orders),
                    },
                    "market_data": {
                        "source": "alpaca-cli",
                        "analysis_date": analysis_date.isoformat(),
                        "bar_count": len(records),
                        "contract_count": 0,
                        "chain_snapshot_count": 0,
                        "downstream_fetch_skipped": True,
                    },
                },
                mode="live-shadow",
            )
        self._emit(
            machine,
            events,
            "candidate_created",
            candidate.model_dump(mode="json"),
            EvidenceLevel.L4_SHADOW,
        )
        deployment_decision: Any | None = None
        deployment_manifest: DeploymentManifest | None = None
        historical_rows: tuple[HistoricalRow, ...] = ()
        selection: Any
        try:
            if runtime_spec.execution_kind == "equity":
                deployment_decision, deployment_manifest = self._deployment_evidence(strategy)
                dataset_hash = deployment_manifest.result_content_hash
                research_provenance = {
                    "source": "hash-bound-deployment-manifest",
                    "manifest_hash": deployment_manifest.manifest_hash,
                    "research_result_hash": deployment_manifest.research_result_hash,
                    "limitations": list(deployment_manifest.limitations),
                }
            else:
                historical_rows, dataset_hash, research_provenance = self._live_research_evidence(
                    strategy.identity.strategy_id, candidate.symbol
                )
        except (DeploymentEvidenceError, ResearchDatasetError, OSError, ValueError) as exc:
            self._emit(
                machine,
                events,
                "rejected",
                {
                    "reasons": [
                        str(exc)
                        if isinstance(exc, DeploymentEvidenceError)
                        else "REAL_RESEARCH_DATASET_UNAVAILABLE"
                    ],
                    "order_sent": False,
                    "downstream_inference_skipped": True,
                },
                EvidenceLevel.L3_SEALED_TRIAL,
            )
            return self._summary(
                session_id,
                machine,
                events,
                {
                    "snapshot": snapshot.model_dump(mode="json"),
                    "candidate": candidate.model_dump(mode="json"),
                    "agent_provenance": {
                        "mode": "not-invoked-research-unavailable",
                        "live_inference": False,
                        "models": [],
                    },
                    "broker": {
                        "connected": True,
                        "transport": checked.capabilities.get("transport", "alpaca"),
                        "execution_enabled": False,
                        "order_sent": False,
                        "positions": len(checked.positions),
                        "open_orders": len(checked.open_orders),
                    },
                },
                mode="live-shadow",
            )
        contracts: list[dict[str, Any]] = []
        chain_snapshots: dict[str, Any] = {}
        chain: dict[str, Any] = {}
        equity_snapshot: dict[str, Any] | None = None
        if runtime_spec.execution_kind == "option":
            candidate_records = [record for record in records if record.symbol == candidate.symbol]
            if not candidate_records:
                raise RuntimeError("CANDIDATE_SYMBOL_MARKET_DATA_MISSING")
            spot = Decimal(str(candidate_records[-1].values["close"]))
            expiration_gte = checked.account.timestamp.date() + timedelta(days=2)
            expiration_lte = checked.account.timestamp.date() + timedelta(days=7)
            contract_filters = {
                "expiration_date_gte": expiration_gte.isoformat(),
                "expiration_date_lte": expiration_lte.isoformat(),
                "strike_price_gte": str(spot - Decimal(10)),
                "strike_price_lte": str(spot + Decimal(10)),
                "limit": 100,
            }
            contracts = await gateway.option_contracts(candidate.symbol, **contract_filters)
            chain = await gateway.option_chain(candidate.symbol, **contract_filters)
            raw_snapshots = chain.get("snapshots", {}) if isinstance(chain, dict) else {}
            chain_snapshots = raw_snapshots if isinstance(raw_snapshots, dict) else {}
            execution_packet = {
                "asset_class": "options",
                "snapshot_id": snapshot.snapshot_id,
                "contract_count": len(contracts),
                "chain_snapshot_count": len(chain_snapshots),
                "contracts": contracts[:20],
                "snapshots": dict(list(chain_snapshots.items())[:20]),
            }
            evidence_protocol_packet = {
                "protocol": "sealed-twins-v1",
                "dataset_hash": dataset_hash,
                "outcomes_visible": False,
            }
        else:
            equity_snapshot = await gateway.stock_snapshot(candidate.symbol)
            execution_packet = {
                "asset_class": "equities",
                "snapshot_id": snapshot.snapshot_id,
                "symbol": candidate.symbol,
                "latest_stock_snapshot": equity_snapshot,
                "order_class": "bracket",
            }
            if deployment_manifest is None:
                raise RuntimeError("DEPLOYMENT_EVIDENCE_MISSING")
            evidence_protocol_packet = self._deployment_agent_packet(
                deployment_manifest,
                self.config.strategy(strategy.identity.strategy_id).payload,
            )
        market_packet = {
            "snapshot": self._agent_snapshot_packet(snapshot),
            "candidate": candidate.model_dump(mode="json") if candidate else None,
            "strategy_adapter": {
                "display_name": runtime_spec.display_name,
                "asset_class": "options" if runtime_spec.execution_kind == "option" else "equities",
                "execution_kind": runtime_spec.execution_kind,
                "market_scope": runtime_spec.market_scope,
                "symbols": list(runtime_spec.symbols),
            },
            "account": {
                "paper": checked.account.paper,
                "equity": str(checked.account.equity),
                "options_level": checked.account.options_trading_level,
            },
        }
        regime_packet = {
            "snapshot_id": snapshot.snapshot_id,
            "analysis_date": analysis_date.isoformat(),
            "clock": checked.clock,
            "derived": context,
        }
        reports = await desk.deliberate(
            market_packet,
            regime_packet,
            execution_packet,
            evidence_protocol_packet,
        )
        reports_hash = self.repository.save_artifact(
            str(session_id), "agent_reports", reports.model_dump(mode="json")
        )
        models = sorted(
            {
                reports.strategist.model_id,
                reports.regime_witness.model_id,
                reports.options_witness.model_id,
                reports.prosecutor.model_id,
            }
        )
        provenance = {
            "mode": "live-featherless",
            "live_inference": True,
            "models": models,
            "reports_hash": reports_hash,
        }
        common: dict[str, Any] = {
            "snapshot": snapshot.model_dump(mode="json"),
            "agents": reports.model_dump(mode="json"),
            "agent_provenance": provenance,
            "dataset_hash": dataset_hash,
            "research_provenance": research_provenance,
            "broker": {
                "connected": True,
                "transport": checked.capabilities.get("transport", "alpaca"),
                "execution_enabled": False,
                "order_sent": False,
                "positions": len(checked.positions),
                "open_orders": len(checked.open_orders),
            },
            "market_data": {
                "source": "alpaca-cli",
                "analysis_date": analysis_date.isoformat(),
                "symbols": list(market_symbols),
                "bar_count": len(records),
                "execution_kind": runtime_spec.execution_kind,
                "contract_count": len(contracts),
                "chain_snapshot_count": len(chain_snapshots),
            },
        }
        exit_plan = strategy.exit_plan(candidate)
        agent_blocks = self._agent_blocks(reports)
        if agent_blocks:
            self._emit(
                machine,
                events,
                "rejected",
                {"reasons": agent_blocks, "order_sent": False},
                EvidenceLevel.L4_SHADOW,
            )
            return self._summary(session_id, machine, events, common, mode="live-shadow")
        evidence_paths: list[dict[str, Any]] = []
        if runtime_spec.execution_kind == "equity":
            if deployment_decision is None or deployment_manifest is None:
                raise RuntimeError("DEPLOYMENT_EVIDENCE_MISSING")
            evidence = deployment_decision
            evidence_commit_hash = deployment_manifest.manifest_hash
            self._emit(
                machine,
                events,
                "evidence_committed",
                {
                    "commit_hash": evidence_commit_hash,
                    "research_result_hash": deployment_manifest.research_result_hash,
                    "outcomes_visible": False,
                },
                EvidenceLevel.L3_SEALED_TRIAL,
            )
        else:
            vault = OutcomeVault(historical_rows, salt=f"real-training:{dataset_hash}")
            protocol = SealedTwinProtocol(vault, self.repository, EvidencePolicy())
            query = strategy.evidence_query(candidate).model_copy(update={"k": 40})
            versions = VersionStamp(
                strategy_id=strategy.identity.strategy_id,
                strategy_version=strategy.identity.strategy_version,
                model_id="+".join(models),
                prompt_hash=reports_hash,
                data_snapshot_id=snapshot.snapshot_id,
            )
            manifest = protocol.commit(str(session_id), query, versions, dataset_hash)
            evidence_commit_hash = manifest.commit_hash
            self._emit(
                machine,
                events,
                "evidence_committed",
                {"commit_hash": manifest.commit_hash, "outcomes_visible": False},
                EvidenceLevel.L3_SEALED_TRIAL,
            )
            evidence = protocol.reveal(str(session_id), manifest)
            evidence_paths = self._path_bands(vault.reveal(twin.twin_id for twin in manifest.twins))
        self._emit(
            machine,
            events,
            "evidence_revealed",
            evidence.model_dump(mode="json"),
            EvidenceLevel.L3_SEALED_TRIAL,
        )
        common["candidate"] = candidate.model_dump(mode="json")
        common["exit_plan"] = exit_plan.model_dump(mode="json")
        common["evidence"] = evidence.model_dump(mode="json")
        common["evidence_paths"] = evidence_paths
        if evidence.status != DecisionStatus.PASS:
            transition = (
                "insufficient_evidence"
                if evidence.status == DecisionStatus.INSUFFICIENT_EVIDENCE
                else "rejected"
            )
            self._emit(
                machine,
                events,
                transition,
                {"reasons": evidence.reasons, "order_sent": False},
                EvidenceLevel.L3_SEALED_TRIAL,
            )
            return self._summary(session_id, machine, events, common, mode="live-shadow")
        try:
            strategy_config = self.config.strategy(strategy.identity.strategy_id).payload
            if runtime_spec.execution_kind == "option":
                contract_config = strategy_config.get("contract", {})
                policy = strategy.contract_policy(candidate).model_copy(
                    update={
                        "min_dte": int(contract_config.get("min_dte", 2)),
                        "max_dte": int(contract_config.get("max_dte", 7)),
                        "min_delta": Decimal(str(contract_config.get("min_delta", "0.15"))),
                        "max_delta": Decimal(str(contract_config.get("max_delta", "0.40"))),
                        "min_open_interest": self.config.risk.minimum_open_interest,
                        "max_relative_spread": self.config.risk.maximum_relative_spread,
                        "max_quote_age_seconds": int(self.config.risk.maximum_quote_age_seconds),
                        "max_leg_timestamp_skew_seconds": (
                            self.config.risk.maximum_leg_timestamp_skew_seconds
                        ),
                    }
                )
                selection = select_debit_vertical(
                    candidate,
                    contracts,
                    chain,
                    policy,
                    checked.account.timestamp,
                )
                observed_leg_skew = selection.leg_skew_seconds
            else:
                execution_config = strategy_config.get("execution", {})
                if not isinstance(execution_config, dict):
                    raise EquitySelectionError("EQUITY_EXECUTION_CONFIG_INVALID")
                stop_distance = candidate.features.get("stop_distance")
                if not isinstance(stop_distance, (float, int)) or stop_distance <= 0:
                    raise EquitySelectionError("EQUITY_STOP_DISTANCE_MISSING")
                if equity_snapshot is None:
                    raise EquitySelectionError("EQUITY_QUOTE_MISSING")
                side = "buy" if candidate.direction == "bullish" else "sell"
                selection = select_equity_bracket(
                    candidate.symbol,
                    side,
                    equity_snapshot,
                    checked.account.timestamp,
                    stop_distance=Decimal(str(stop_distance)),
                    stop_distance_fraction=(
                        Decimal(str(candidate.features["stop_distance_fraction"]))
                        if candidate.features.get("stop_distance_fraction") is not None
                        else None
                    ),
                    minimum_reward_risk=self.config.risk.minimum_operational_reward_risk,
                    modeled_round_trip_cost=Decimal(
                        str(execution_config.get("modeled_round_trip_cost_per_share", "0.02"))
                    ),
                    modeled_round_trip_cost_fraction=(
                        Decimal(
                            str(strategy_config.get("costs", {}).get("slippage_bps_per_fill", 0))
                        )
                        * Decimal(2)
                        / Decimal(10000)
                        if isinstance(strategy_config.get("costs", {}), dict)
                        else Decimal(0)
                    ),
                    maximum_quote_age_seconds=self.config.risk.maximum_quote_age_seconds,
                )
                observed_leg_skew = Decimal(0)
        except (EquitySelectionError, OptionSelectionError) as exc:
            self._emit(
                machine,
                events,
                "rejected",
                {"reasons": (str(exc),), "order_sent": False},
                EvidenceLevel.L4_SHADOW,
            )
            return self._summary(session_id, machine, events, common, mode="live-shadow")
        strategy_hash = self._strategy_authority_hash(strategy)
        unrealized_net = Decimal(0)
        worst_open_loss = Decimal(0)
        for position in checked.positions:
            if position.get("unrealized_pl") is None:
                raise RuntimeError("POSITION_UNREALIZED_PNL_MISSING")
            unrealized = Decimal(str(position["unrealized_pl"]))
            unrealized_net += unrealized
            if unrealized < 0:
                worst_open_loss += -unrealized
        realized_daily_pnl = checked.account.equity - checked.account.last_equity - unrealized_net
        entry_cutoff = runtime_spec.entry_cutoff
        clock_at = datetime.fromisoformat(str(checked.clock["timestamp"]))
        entry_cutoff_passed = clock_at.astimezone(ET).time() > entry_cutoff
        risk = self.risk.evaluate(
            RiskContext(
                account=checked.account,
                evidence=evidence,
                payoff=selection.passport,
                strategy_manifest_hash=strategy_hash,
                expected_account_id_hash=expected_account_id_hash,
                quote_hash=selection.quote_hash,
                observed_quote_age_seconds=selection.quote_age_seconds,
                observed_leg_skew_seconds=observed_leg_skew,
                relative_spread=selection.relative_spread,
                open_strategy_positions=len(checked.positions),
                unknown_orders=len(checked.open_orders),
                realized_daily_pnl=realized_daily_pnl,
                worst_open_loss=worst_open_loss,
                high_water_equity=high_water_equity,
                entry_cutoff_passed=entry_cutoff_passed,
                market_open=checked.market_open,
            )
        )
        common["risk_state"] = {
            "daily_realized_pnl_estimate": str(realized_daily_pnl),
            "worst_open_loss": str(worst_open_loss),
            "intraday_high_water_equity": str(high_water_equity),
            "entry_cutoff": entry_cutoff.isoformat(),
            "entry_cutoff_passed": entry_cutoff_passed,
        }
        common["payoff"] = selection.passport.model_dump(mode="json")
        common["watchdog"] = {
            "status": "armed-after-fill",
            "target_profit": str(selection.passport.operational_target_profit),
            "stop_loss": str(selection.passport.operational_stop_loss),
            "exit_at": exit_plan.exit_at.isoformat(),
            "maximum_quote_age_seconds": str(self.config.risk.maximum_quote_age_seconds),
        }
        common["risk"] = risk.model_dump(mode="json")
        if risk.status != DecisionStatus.PASS:
            self._emit(
                machine,
                events,
                "rejected",
                {"decision": risk.model_dump(mode="json"), "order_sent": False},
                EvidenceLevel.L4_SHADOW,
            )
            return self._summary(session_id, machine, events, common, mode="live-shadow")
        self._emit(
            machine,
            events,
            "risk_approved",
            {"decision": risk.model_dump(mode="json"), "payoff": common["payoff"]},
            EvidenceLevel.L4_SHADOW,
        )
        if runtime_spec.execution_kind == "equity":
            passport = selection.passport
            intent = ExecutionIntent(
                account_id_hash=checked.account.account_id_hash,
                strategy_manifest_hash=strategy_hash,
                evidence_commit_hash=evidence_commit_hash,
                risk_decision_id=risk.decision_id,
                asset_class="equity",
                symbol=passport.symbol,
                side=passport.side,
                legs=(),
                quantity=risk.quantity,
                limit_price=passport.entry_price or passport.entry_net_debit,
                take_profit_price=passport.target_price,
                stop_price=passport.stop_price,
                order_class="bracket",
            )
        else:
            intent = ExecutionIntent(
                account_id_hash=checked.account.account_id_hash,
                strategy_manifest_hash=strategy_hash,
                evidence_commit_hash=evidence_commit_hash,
                risk_decision_id=risk.decision_id,
                legs=selection.passport.legs,
                quantity=risk.quantity,
                limit_price=selection.passport.entry_net_debit,
            )
        warrant = self.warrants.mint(intent, risk)
        warrant_hash = self.repository.save_artifact(
            str(session_id), "warrant", warrant.model_dump(mode="json")
        )
        self._emit(
            machine,
            events,
            "warrant_minted",
            {"warrant_id": str(warrant.warrant_id), "warrant_hash": warrant_hash},
            EvidenceLevel.L4_SHADOW,
        )
        order_client_id = client_order_id(str(session_id), canonical_sha256(intent))
        dry_run_order = getattr(gateway, "dry_run_order", None)
        if callable(dry_run_order):
            dry_run = await dry_run_order(intent, order_client_id)
        elif intent.asset_class == "option":
            dry_run = await gateway.dry_run_option_order(intent, order_client_id)
        else:
            raise RuntimeError("EQUITY_DRY_RUN_UNSUPPORTED_BY_GATEWAY")
        common["warrant"] = warrant.model_dump(mode="json")
        common["dry_run"] = dry_run
        if not execute:
            self._emit(
                machine,
                events,
                "shadow_ready",
                {"dry_run": dry_run, "execution_enabled": False, "order_sent": False},
                EvidenceLevel.L4_SHADOW,
            )
            return self._summary(session_id, machine, events, common, mode="live-shadow")
        try:
            if runtime_spec.execution_kind == "equity":
                if deployment_manifest is None:
                    raise ExecutionError("DEPLOYMENT_MANIFEST_MISSING")
                common["promotion"] = {
                    "status": "PROMOTED",
                    "protocol": deployment_manifest.schema_version,
                    "manifest_hash": deployment_manifest.manifest_hash,
                    "research_result_hash": deployment_manifest.research_result_hash,
                    "metrics": deployment_manifest.metrics.model_dump(mode="json"),
                }
            else:
                common["promotion"] = self._require_promoted_strategy(
                    strategy.identity.strategy_id, strategy_hash
                )
        except ExecutionError as exc:
            common["promotion"] = {"status": "BLOCKED", "reason": str(exc)}
            self._emit(
                machine,
                events,
                "insufficient_evidence",
                {"reason": str(exc), "order_sent": False},
                EvidenceLevel.L3_SEALED_TRIAL,
            )
            return self._summary(session_id, machine, events, common, mode="live-paper")
        if os.getenv("AFTERIMAGE_ENABLE_PAPER_EXECUTION", "false").lower() != "true":
            raise RuntimeError("PAPER_EXECUTION_ENV_GATE_DISABLED")
        if not bool(getattr(gateway, "execution_enabled", False)):
            raise RuntimeError("BROKER_EXECUTION_GATE_DISABLED")
        self._emit(
            machine,
            events,
            "submit_started",
            {"client_order_id": order_client_id},
            EvidenceLevel.L5_PAPER_EXECUTION,
        )
        try:
            order = await ExecutionService(gateway, self.warrants, self.repository).submit(
                str(session_id), warrant
            )
        except AmbiguousSubmission as exc:
            self._emit(
                machine,
                events,
                "ambiguous",
                {"reason": str(exc), "order_sent": True},
                EvidenceLevel.L5_PAPER_EXECUTION,
            )
            common["broker"]["order_sent"] = True
            pending = self.repository.broker_orders(str(session_id))
            if pending:
                common["broker_order"] = pending[-1]
            return self._summary(session_id, machine, events, common, mode="live-paper")
        event_type = "filled" if order.status.lower() == "filled" else "working"
        self._emit(
            machine,
            events,
            event_type,
            {"order": order.model_dump(mode="json")},
            EvidenceLevel.L5_PAPER_EXECUTION,
        )
        common["broker"]["order_sent"] = True
        common["broker_order"] = order.model_dump(mode="json")
        summary = self._summary(session_id, machine, events, common, mode="live-paper")
        if event_type == "filled":
            return await self.manage_live_position(
                gateway, expected_account_id_hash, str(session_id)
            )
        return summary

    def managed_session_ids(self) -> list[str]:
        return self.repository.active_session_ids()

    async def submit_shadow_session(
        self,
        gateway: Any,
        expected_account_id_hash: str,
        session_id: str,
        warrant: ExecutionWarrant,
    ) -> dict[str, Any]:
        """Submit a persisted SHADOW_READY warrant into the durable lifecycle."""
        summaries = self.repository.session_artifacts(session_id, "session_summary")
        if not summaries or not isinstance(summaries[-1].get("payload"), dict):
            raise ExecutionError("SESSION_SUMMARY_MISSING")
        previous = summaries[-1]["payload"]
        prior_events = [SessionEvent.model_validate(event) for event in previous.get("events", [])]
        if not prior_events or previous.get("state") != SessionState.SHADOW_READY.value:
            raise ExecutionError("SESSION_NOT_SHADOW_READY")
        session_warrants = self.repository.session_artifacts(session_id, "warrant")
        if not any(
            str(item.get("payload", {}).get("warrant_id")) == str(warrant.warrant_id)
            for item in session_warrants
            if isinstance(item.get("payload"), dict)
        ):
            raise ExecutionError("WARRANT_SESSION_MISMATCH")
        checked = await gateway.preflight(expected_account_id_hash)
        if checked.account.account_id_hash != warrant.intent.account_id_hash:
            raise ExecutionError("WARRANT_ACCOUNT_MISMATCH")
        if os.getenv("AFTERIMAGE_ENABLE_PAPER_EXECUTION", "false").lower() != "true":
            raise ExecutionError("PAPER_EXECUTION_ENV_GATE_DISABLED")
        if not bool(getattr(gateway, "execution_enabled", False)):
            raise ExecutionError("BROKER_EXECUTION_GATE_DISABLED")

        identity = StrategyIdentity(
            strategy_id=prior_events[0].versions.strategy_id,
            strategy_version=prior_events[0].versions.strategy_version,
        )
        machine = StateMachine(
            UUID(session_id),
            identity,
            self.repository,
            self.ledger,
            state=SessionState.SHADOW_READY,
            sequence=max(event.sequence for event in prior_events),
        )
        events = list(prior_events)
        common = {
            key: value
            for key, value in previous.items()
            if key not in {"session_id", "state", "events", "audit", "mode", "config_manifest_hash"}
        }
        try:
            strategy, runtime_spec = self.resolve_strategy(identity.strategy_id)
            if runtime_spec.execution_kind == "equity":
                _, deployment_manifest = self._deployment_evidence(strategy)
                if (
                    deployment_manifest.strategy_authority_hash
                    != warrant.intent.strategy_manifest_hash
                ):
                    raise ExecutionError("DEPLOYMENT_STRATEGY_BINDING_MISMATCH")
                common["promotion"] = {
                    "status": "PROMOTED",
                    "protocol": deployment_manifest.schema_version,
                    "manifest_hash": deployment_manifest.manifest_hash,
                    "research_result_hash": deployment_manifest.research_result_hash,
                }
            else:
                common["promotion"] = self._require_promoted_strategy(
                    identity.strategy_id, warrant.intent.strategy_manifest_hash
                )
        except ExecutionError as exc:
            common["promotion"] = {"status": "BLOCKED", "reason": str(exc)}
            self._emit(
                machine,
                events,
                "insufficient_evidence",
                {"reason": str(exc), "order_sent": False},
                EvidenceLevel.L3_SEALED_TRIAL,
            )
            return self._summary(UUID(session_id), machine, events, common, mode="live-paper")
        order_client_id = client_order_id(session_id, warrant.intent_hash)
        self._emit(
            machine,
            events,
            "submit_started",
            {"client_order_id": order_client_id},
            EvidenceLevel.L5_PAPER_EXECUTION,
        )
        try:
            order = await ExecutionService(gateway, self.warrants, self.repository).submit(
                session_id, warrant
            )
        except AmbiguousSubmission as exc:
            self._emit(
                machine,
                events,
                "ambiguous",
                {"reason": str(exc), "order_sent": True},
                EvidenceLevel.L5_PAPER_EXECUTION,
            )
            common["broker"] = {
                **dict(common.get("broker", {})),
                "order_sent": True,
                "execution_enabled": True,
            }
            pending = self.repository.broker_orders(session_id)
            if pending:
                common["broker_order"] = pending[-1]
            return self._summary(UUID(session_id), machine, events, common, mode="live-paper")
        event_type = "filled" if order.status.lower() == "filled" else "working"
        self._emit(
            machine,
            events,
            event_type,
            {"order": order.model_dump(mode="json")},
            EvidenceLevel.L5_PAPER_EXECUTION,
        )
        common["broker"] = {
            **dict(common.get("broker", {})),
            "order_sent": True,
            "execution_enabled": True,
        }
        common["broker_order"] = order.model_dump(mode="json")
        summary = self._summary(UUID(session_id), machine, events, common, mode="live-paper")
        if event_type == "filled":
            return await self.manage_live_position(gateway, expected_account_id_hash, session_id)
        return summary

    @staticmethod
    def _broker_autopsy(
        orders: list[dict[str, Any]], entry_warrant: ExecutionWarrant
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source": "alpaca-broker-order-receipts",
            "order_count": len(orders),
            "pnl_status": "awaiting_complete_fill_prices",
        }
        if len(orders) < 2:
            return payload
        entry_price = orders[0].get("filled_avg_price")
        exit_price = orders[-1].get("filled_avg_price")
        if entry_price is None or exit_price is None:
            return payload
        multiplier = Decimal(100) if entry_warrant.intent.asset_class == "option" else Decimal(1)
        direction = Decimal(1) if entry_warrant.intent.side != "sell" else Decimal(-1)
        gross_pnl = (
            (Decimal(str(exit_price)) - Decimal(str(entry_price)))
            * multiplier
            * entry_warrant.intent.quantity
            * direction
        )
        payload.update(
            {
                "pnl_status": "broker_fill_gross_only",
                "entry_fill_price": str(entry_price),
                "exit_fill_price": str(exit_price),
                "gross_pnl": str(gross_pnl),
                "net_pnl": None,
                "net_pnl_reason": "broker fees and final activities not yet reconciled",
            }
        )
        return payload

    async def manage_live_position(
        self,
        gateway: Any,
        expected_account_id_hash: str,
        session_id: str,
    ) -> dict[str, Any]:
        """Resume one durable broker lifecycle without creating a new market candidate."""
        summaries = self.repository.session_artifacts(session_id, "session_summary")
        if not summaries:
            raise RuntimeError("SESSION_SUMMARY_MISSING")
        previous = summaries[-1]["payload"]
        if not isinstance(previous, dict):
            raise TypeError("SESSION_SUMMARY_INVALID")
        prior_events = [SessionEvent.model_validate(event) for event in previous.get("events", [])]
        if not prior_events:
            raise RuntimeError("SESSION_EVENTS_MISSING")
        identity = StrategyIdentity(
            strategy_id=prior_events[0].versions.strategy_id,
            strategy_version=prior_events[0].versions.strategy_version,
        )
        machine = StateMachine(
            UUID(session_id),
            identity,
            self.repository,
            self.ledger,
            state=SessionState(str(previous["state"])),
            sequence=max(event.sequence for event in prior_events),
        )
        events = list(prior_events)
        common = {
            key: value
            for key, value in previous.items()
            if key not in {"session_id", "state", "events", "audit", "mode", "config_manifest_hash"}
        }
        checked = await gateway.preflight(expected_account_id_hash, allow_existing_exposure=True)
        common["broker"] = {
            **dict(common.get("broker", {})),
            "connected": True,
            "transport": checked.capabilities.get("transport", "alpaca"),
            "execution_enabled": bool(getattr(gateway, "execution_enabled", False)),
            "positions": len(checked.positions),
            "open_orders": len(checked.open_orders),
        }
        if machine.state in {SessionState.WORKING, SessionState.AMBIGUOUS}:
            orders = self.repository.broker_orders(session_id)
            if not orders:
                raise RuntimeError("ENTRY_BROKER_ORDER_MISSING")
            client_id = str(orders[-1]["client_order_id"])
            reconciled = await Reconciler(gateway).by_client_id(client_id)
            common["reconciliation"] = {
                "status": reconciled.status,
                "attempts": reconciled.attempts,
            }
            if reconciled.order is None:
                return self._summary(UUID(session_id), machine, events, common, mode="live-paper")
            raw = reconciled.order
            expected_broker_order_id = str(orders[-1].get("id", ""))
            if not expected_broker_order_id or (
                not expected_broker_order_id.startswith("pending:")
                and str(raw.get("id", "")) != expected_broker_order_id
            ):
                self._emit(
                    machine,
                    events,
                    "anomaly",
                    {"reason": "ENTRY_BROKER_ORDER_ID_MISMATCH"},
                    EvidenceLevel.L5_PAPER_EXECUTION,
                )
                return self._summary(UUID(session_id), machine, events, common, mode="live-paper")
            self.repository.save_broker_order(
                session_id, raw, str(orders[-1].get("intent_hash", ""))
            )
            status = str(raw.get("status", "unknown")).lower()
            if status == "filled":
                self._emit(
                    machine,
                    events,
                    "filled",
                    {"broker_order_hash": canonical_sha256(raw)},
                    EvidenceLevel.L5_PAPER_EXECUTION,
                )
            elif status in {"canceled", "cancelled", "expired", "rejected"}:
                self._emit(
                    machine,
                    events,
                    "rejected",
                    {"broker_status": status},
                    EvidenceLevel.L5_PAPER_EXECUTION,
                )
                return self._summary(UUID(session_id), machine, events, common, mode="live-paper")
            else:
                entry_cutoff = StrategyRuntimeSpec.from_config(
                    self.config.strategy(identity.strategy_id)
                ).entry_cutoff
                broker_now = datetime.fromisoformat(str(checked.clock["timestamp"]))
                cutoff_passed = broker_now.astimezone(ET).time() > entry_cutoff
                common["entry_order_management"] = {
                    "broker_status": status,
                    "entry_cutoff": entry_cutoff.isoformat(),
                    "entry_cutoff_passed": cutoff_passed,
                }
                if cutoff_passed:
                    broker_order_id = raw.get("id")
                    if not broker_order_id:
                        self._emit(
                            machine,
                            events,
                            "anomaly",
                            {"reason": "ENTRY_ORDER_ID_MISSING_AT_CUTOFF"},
                            EvidenceLevel.L5_PAPER_EXECUTION,
                        )
                        return self._summary(
                            UUID(session_id), machine, events, common, mode="live-paper"
                        )
                    await gateway.cancel_order(str(broker_order_id))
                    post_cancel = await Reconciler(gateway).by_client_id(client_id)
                    common["entry_order_management"].update(
                        {
                            "cancel_requested": True,
                            "post_cancel_status": post_cancel.status,
                            "post_cancel_attempts": post_cancel.attempts,
                        }
                    )
                    if post_cancel.order is None:
                        self._emit(
                            machine,
                            events,
                            "anomaly",
                            {"reason": "ENTRY_CANCEL_AMBIGUOUS"},
                            EvidenceLevel.L5_PAPER_EXECUTION,
                        )
                        return self._summary(
                            UUID(session_id), machine, events, common, mode="live-paper"
                        )
                    raw = post_cancel.order
                    if str(raw.get("id", "")) != expected_broker_order_id:
                        self._emit(
                            machine,
                            events,
                            "anomaly",
                            {"reason": "ENTRY_BROKER_ORDER_ID_MISMATCH_AFTER_CANCEL"},
                            EvidenceLevel.L5_PAPER_EXECUTION,
                        )
                        return self._summary(
                            UUID(session_id), machine, events, common, mode="live-paper"
                        )
                    self.repository.save_broker_order(
                        session_id, raw, str(orders[-1].get("intent_hash", ""))
                    )
                    status = str(raw.get("status", "unknown")).lower()
                    if status == "filled":
                        self._emit(
                            machine,
                            events,
                            "filled",
                            {
                                "broker_order_hash": canonical_sha256(raw),
                                "reason": "FILLED_DURING_CUTOFF_CANCEL_RACE",
                            },
                            EvidenceLevel.L5_PAPER_EXECUTION,
                        )
                    elif status in {"canceled", "cancelled", "expired", "rejected"}:
                        self._emit(
                            machine,
                            events,
                            "rejected",
                            {
                                "broker_status": status,
                                "reason": "ENTRY_CUTOFF_CANCELLED",
                            },
                            EvidenceLevel.L5_PAPER_EXECUTION,
                        )
                        return self._summary(
                            UUID(session_id), machine, events, common, mode="live-paper"
                        )
                    else:
                        self._emit(
                            machine,
                            events,
                            "anomaly",
                            {
                                "broker_status": status,
                                "reason": "ENTRY_CANCEL_UNCONFIRMED",
                            },
                            EvidenceLevel.L5_PAPER_EXECUTION,
                        )
                        return self._summary(
                            UUID(session_id), machine, events, common, mode="live-paper"
                        )
                elif machine.state == SessionState.AMBIGUOUS:
                    self._emit(
                        machine,
                        events,
                        "working",
                        {"broker_status": status},
                        EvidenceLevel.L5_PAPER_EXECUTION,
                    )
                else:
                    return self._summary(
                        UUID(session_id), machine, events, common, mode="live-paper"
                    )
        warrant_payload = previous.get("warrant")
        if not isinstance(warrant_payload, dict):
            raise TypeError("ENTRY_WARRANT_MISSING")
        entry_warrant = ExecutionWarrant.model_validate(warrant_payload)
        if machine.state == SessionState.FILLED:
            plan = ExitPlan.model_validate(previous.get("exit_plan"))
            payoff = previous.get("payoff")
            if not isinstance(payoff, dict):
                raise RuntimeError("PAYOFF_PASSPORT_MISSING")
            if entry_warrant.intent.asset_class == "equity":
                symbol = entry_warrant.intent.symbol
                if symbol is None:
                    raise RuntimeError("EQUITY_INTENT_SYMBOL_MISSING")
                matching_positions = [
                    position
                    for position in checked.positions
                    if str(position.get("symbol", "")).upper() == symbol
                    and Decimal(str(position.get("qty", "0"))) != 0
                ]
                if not matching_positions:
                    self._emit(
                        machine,
                        events,
                        "exit_started",
                        {"action": "broker_bracket_flattened", "symbol": symbol},
                        EvidenceLevel.L5_PAPER_EXECUTION,
                    )
                    self._emit(
                        machine,
                        events,
                        "closed",
                        {"reason": "BROKER_POSITION_FLAT"},
                        EvidenceLevel.L5_PAPER_EXECUTION,
                    )
                else:
                    position = matching_positions[0]
                    raw_quantity = abs(Decimal(str(position.get("qty", "0"))))
                    quantity = int(raw_quantity)
                    if (
                        raw_quantity != quantity
                        or quantity < 1
                        or quantity > entry_warrant.intent.quantity
                    ):
                        self._emit(
                            machine,
                            events,
                            "halt",
                            {"reason": "EQUITY_POSITION_QUANTITY_MISMATCH"},
                            EvidenceLevel.L5_PAPER_EXECUTION,
                        )
                        return self._summary(
                            UUID(session_id), machine, events, common, mode="live-paper"
                        )
                    now = datetime.fromisoformat(str(checked.clock["timestamp"]))
                    if now < plan.exit_at:
                        common["watchdog_assessment"] = {
                            "action": "hold_broker_bracket",
                            "symbol": symbol,
                            "quantity": quantity,
                            "time_exit_at": plan.exit_at.isoformat(),
                        }
                        return self._summary(
                            UUID(session_id), machine, events, common, mode="live-paper"
                        )
                    exit_warrant, exit_decision = authorize_equity_position_exit(
                        self.warrants, entry_warrant, quantity
                    )
                    exit_warrant_hash = self.repository.save_artifact(
                        session_id,
                        "exit_warrant",
                        exit_warrant.model_dump(mode="json"),
                    )
                    self._emit(
                        machine,
                        events,
                        "exit_started",
                        {
                            "action": "time_exit",
                            "exit_warrant_hash": exit_warrant_hash,
                            "risk_decision_hash": canonical_sha256(exit_decision),
                        },
                        EvidenceLevel.L5_PAPER_EXECUTION,
                    )
                    exit_order = await ExecutionService(
                        gateway, self.warrants, self.repository
                    ).submit(session_id, exit_warrant)
                    common["exit_order"] = exit_order.model_dump(mode="json")
                    if exit_order.status.lower() == "filled":
                        self._emit(
                            machine,
                            events,
                            "closed",
                            {"broker_order": exit_order.model_dump(mode="json")},
                            EvidenceLevel.L5_PAPER_EXECUTION,
                        )
                if machine.state.value == SessionState.CLOSED.value:
                    autopsy = self._broker_autopsy(
                        self.repository.broker_orders(session_id), entry_warrant
                    )
                    common["broker_autopsy"] = autopsy
                    self._emit(
                        machine,
                        events,
                        "autopsy_saved",
                        autopsy,
                        EvidenceLevel.L5_PAPER_EXECUTION,
                    )
                return self._summary(UUID(session_id), machine, events, common, mode="live-paper")
            assessment = await PositionWatchdog(
                gateway,
                maximum_quote_age_seconds=self.config.risk.maximum_quote_age_seconds,
            ).assess(
                entry_warrant.intent,
                plan,
                target_profit=Decimal(str(payoff["operational_target_profit"])),
                stop_loss=Decimal(str(payoff["operational_stop_loss"])),
                now=datetime.fromisoformat(str(checked.clock["timestamp"])),
            )
            common["watchdog_assessment"] = assessment.model_dump(mode="json")
            if assessment.action == WatchdogAction.HALT_POSITION_MISMATCH:
                self._emit(
                    machine,
                    events,
                    "halt",
                    {"reason": assessment.action.value},
                    EvidenceLevel.L5_PAPER_EXECUTION,
                )
                return self._summary(UUID(session_id), machine, events, common, mode="live-paper")
            if assessment.action == WatchdogAction.HALT_STALE_QUOTES:
                common["watchdog_assessment"]["retry_required"] = True
                return self._summary(UUID(session_id), machine, events, common, mode="live-paper")
            if assessment.action == WatchdogAction.HOLD:
                return self._summary(UUID(session_id), machine, events, common, mode="live-paper")
            if assessment.action not in EXIT_ACTIONS:
                raise RuntimeError("WATCHDOG_ACTION_INVALID")
            exit_warrant, exit_decision = authorize_position_exit(
                self.warrants, entry_warrant, assessment
            )
            exit_warrant_hash = self.repository.save_artifact(
                session_id, "exit_warrant", exit_warrant.model_dump(mode="json")
            )
            self._emit(
                machine,
                events,
                "exit_started",
                {
                    "action": assessment.action.value,
                    "exit_warrant_hash": exit_warrant_hash,
                    "risk_decision_hash": canonical_sha256(exit_decision),
                },
                EvidenceLevel.L5_PAPER_EXECUTION,
            )
            exit_order = await ExecutionService(gateway, self.warrants, self.repository).submit(
                session_id, exit_warrant
            )
            common["exit_order"] = exit_order.model_dump(mode="json")
            if exit_order.status.lower() != "filled":
                return self._summary(UUID(session_id), machine, events, common, mode="live-paper")
            self._emit(
                machine,
                events,
                "closed",
                {"broker_order": exit_order.model_dump(mode="json")},
                EvidenceLevel.L5_PAPER_EXECUTION,
            )
        if machine.state == SessionState.EXITING:
            orders = self.repository.broker_orders(session_id)
            if len(orders) < 2:
                raise RuntimeError("EXIT_BROKER_ORDER_MISSING")
            reconciled = await Reconciler(gateway).by_client_id(str(orders[-1]["client_order_id"]))
            if reconciled.order is None:
                common["exit_reconciliation"] = {"status": "ambiguous"}
                return self._summary(UUID(session_id), machine, events, common, mode="live-paper")
            raw = reconciled.order
            self.repository.save_broker_order(
                session_id, raw, str(orders[-1].get("intent_hash", ""))
            )
            status = str(raw.get("status", "unknown")).lower()
            if status == "filled":
                self._emit(
                    machine,
                    events,
                    "closed",
                    {"broker_order_hash": canonical_sha256(raw)},
                    EvidenceLevel.L5_PAPER_EXECUTION,
                )
            elif status in {"canceled", "cancelled", "expired", "rejected"}:
                self._emit(
                    machine,
                    events,
                    "anomaly",
                    {"broker_status": status},
                    EvidenceLevel.L5_PAPER_EXECUTION,
                )
                return self._summary(UUID(session_id), machine, events, common, mode="live-paper")
        if machine.state == SessionState.CLOSED:
            autopsy = self._broker_autopsy(self.repository.broker_orders(session_id), entry_warrant)
            common["broker_autopsy"] = autopsy
            self._emit(
                machine,
                events,
                "autopsy_saved",
                autopsy,
                EvidenceLevel.L5_PAPER_EXECUTION,
            )
        return self._summary(UUID(session_id), machine, events, common, mode="live-paper")

    async def run_live_shadow(
        self,
        gateway: Any,
        desk: AgentDesk,
        expected_account_id_hash: str,
        symbol: str | None = None,
        strategy_id: str | None = None,
    ) -> dict[str, Any]:
        return await self.run_live_cycle(
            gateway,
            desk,
            expected_account_id_hash,
            symbol=symbol,
            strategy_id=strategy_id,
            execute=False,
        )

    @staticmethod
    def _score_tournament_rows(
        strategy_id: str,
        rows: tuple[HistoricalRow, ...],
        dataset_hash: str,
    ) -> EvidenceMetrics:
        twins = tuple(
            BlindTwin(
                twin_id=f"holdout_{row.private_row_id[:20]}",
                features=tuple(row.features[key] for key in sorted(row.features)),
                distance=Decimal(index) / Decimal(1000),
                weight=Decimal(1),
                cluster_id=row.cluster_id,
            )
            for index, row in enumerate(rows)
        )
        outcomes = tuple(
            RevealedOutcome(
                twin_id=twin.twin_id,
                session_date=row.session_date,
                target_first=row.target_first,
                return_r=row.return_r,
                placebo_return_r=row.placebo_return_r,
                censored=row.censored,
                path=row.path,
            )
            for twin, row in zip(twins, rows, strict=True)
        )
        outcome_hash = canonical_sha256([row.model_dump(mode="json") for row in rows])
        return evaluate_evidence(
            twins,
            outcomes,
            canonical_sha256(
                {
                    "dataset_hash": dataset_hash,
                    "strategy": strategy_id,
                    "kind": "tournament-commit",
                }
            ),
            canonical_sha256(
                {
                    "dataset_hash": dataset_hash,
                    "strategy": strategy_id,
                    "outcome_hash": outcome_hash,
                    "kind": "tournament-reveal",
                }
            ),
            EvidencePolicy(),
        ).metrics

    @staticmethod
    def _recorded_fixture_tournament() -> dict[str, Any]:
        return {
            "entries": [],
            "champion": None,
            "champion_manifest_hash": None,
            "evaluation_label": "not run in synthetic engineering replay",
            "mode": "recorded-fixture-no-performance-claim",
        }

    def run_research_tournament(self, dataset_path: str | Path) -> dict[str, Any]:
        dataset = load_research_dataset(Path(dataset_path))
        holdout_hash = dataset.holdout.source_hash
        candidates = self._research_candidates(dataset)
        runner = TournamentRunner(self.repository)
        policy = self.promotion_policy
        session_id = str(uuid4())
        seal = runner.preregister(session_id, candidates, policy, holdout_hash)
        results = {
            canonical_sha256(candidate): self._score_tournament_rows(
                candidate.identity.strategy_id,
                dataset.holdout.evaluations[candidate.identity.strategy_id].rows,
                dataset.dataset_hash,
            )
            for candidate in candidates
        }
        result = runner.reveal(session_id, seal, candidates, policy, results)
        payload = result.model_dump(mode="json")
        payload["result_provenance"] = {
            canonical_sha256(candidate): {
                "strategy_id": candidate.identity.strategy_id,
                "outcome_series_hash": canonical_sha256(
                    [
                        row.model_dump(mode="json")
                        for row in dataset.holdout.evaluations[candidate.identity.strategy_id].rows
                    ]
                ),
                "observations": len(
                    dataset.holdout.evaluations[candidate.identity.strategy_id].rows
                ),
                "source_record_hash": holdout_hash,
                "strategy_implementation": (
                    f"{candidate.identity.strategy_id}@{candidate.identity.strategy_version}"
                ),
                "cost_model": {
                    "applies_to": "underlying-path proxy only",
                    "fee_per_contract": str(candidate.fee_per_contract),
                    "slippage_per_leg": str(candidate.slippage_per_leg),
                },
            }
            for candidate in candidates
        }
        payload["dataset_hash"] = dataset.dataset_hash
        payload["holdout_source_hash"] = holdout_hash
        payload["evaluation_label"] = (
            "real Alpaca chronological holdout; underlying-path R proxy; not broker P&L"
        )
        payload["holdout_disclosure"] = (
            "This chronological partition is hash-bound and strategy-derived. It is not "
            "described as developer-blind after its first reveal."
        )
        return payload

    def _research_candidates(self, dataset: ResearchDataset) -> tuple[CandidateManifest, ...]:
        training_end = datetime.combine(dataset.training.end, time.max, ET).astimezone(UTC)
        start = datetime.combine(dataset.holdout.start, time.min, ET).astimezone(UTC)
        end = datetime.combine(dataset.holdout.end, time.max, ET).astimezone(UTC)
        return tuple(
            CandidateManifest(
                identity=(strategy := self.registry.load(strategy_id)).identity,
                parameters={
                    "source": dataset.source,
                    "feed": dataset.feed,
                    "timeframe": dataset.timeframe,
                    "result_type": "underlying-path-r-proxy",
                    "strategy_authority_hash": self._strategy_authority_hash(strategy),
                },
                code_revision=os.getenv("AFTERIMAGE_CODE_REVISION", "workspace-source"),
                dataset_hash=dataset.dataset_hash,
                training_end=training_end,
                embargo_sessions=dataset.embargo_sessions,
                final_holdout_start=start,
                final_holdout_end=end,
                fee_per_contract=Decimal(0),
                slippage_per_leg=Decimal(0),
                baselines=("opposite-direction-placebo",),
            )
            for strategy_id in sorted(dataset.holdout.evaluations)
        )

    def _research_tournament_entries(
        self, dataset: ResearchDataset, candidates: tuple[CandidateManifest, ...]
    ) -> tuple[TournamentEntry, ...]:
        return tuple(
            build_entry(
                candidate,
                canonical_sha256(candidate),
                self._score_tournament_rows(
                    candidate.identity.strategy_id,
                    dataset.holdout.evaluations[candidate.identity.strategy_id].rows,
                    dataset.dataset_hash,
                ),
                self.promotion_policy,
            )
            for candidate in candidates
        )

    def _require_promoted_strategy(
        self, strategy_id: str, strategy_authority_hash: str
    ) -> dict[str, Any]:
        dataset_path = Path(
            os.getenv(
                "AFTERIMAGE_RESEARCH_DATASET_PATH",
                ".afterimage/research/spy-real-v1.json",
            )
        )
        dataset = load_research_dataset(dataset_path)
        candidates = self._research_candidates(dataset)
        champion = select_champion(self._research_tournament_entries(dataset, candidates))
        if champion is None:
            raise ExecutionError("STRATEGY_NOT_PROMOTED:NO_CHAMPION")
        if champion.identity.strategy_id != strategy_id:
            raise ExecutionError("STRATEGY_NOT_PROMOTED:DIFFERENT_CHAMPION")
        candidate = next(
            item for item in candidates if canonical_sha256(item) == champion.manifest_hash
        )
        if candidate.parameters.get("strategy_authority_hash") != strategy_authority_hash:
            raise ExecutionError("STRATEGY_NOT_PROMOTED:AUTHORITY_HASH_MISMATCH")
        return {
            "status": "PROMOTED",
            "champion_manifest_hash": champion.manifest_hash,
            "strategy_authority_hash": strategy_authority_hash,
            "dataset_hash": dataset.dataset_hash,
            "promotion_policy_hash": canonical_sha256(self.promotion_policy),
        }

    def _summary(
        self,
        session_id: UUID,
        machine: StateMachine,
        events: list[SessionEvent],
        extras: dict[str, Any] | None,
        mode: str = "recorded-replay",
    ) -> dict[str, Any]:
        payload = {
            "session_id": str(session_id),
            "state": machine.state.value,
            "strategy": {
                **machine.identity.model_dump(mode="json"),
                "display_name": str(
                    self.config.strategy(machine.identity.strategy_id).payload.get(
                        "display_name", machine.identity.strategy_id
                    )
                ),
            },
            "events": [event.model_dump(mode="json") for event in events],
            "audit": self.ledger.verify(str(session_id)).__dict__,
            "mode": mode,
            "config_manifest_hash": self.config.manifest_hash,
        }
        if extras:
            payload.update(extras)
        self.repository.save_artifact(str(session_id), "session_summary", payload)
        return payload
