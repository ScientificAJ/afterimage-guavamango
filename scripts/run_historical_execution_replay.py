#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from afterimage.agents.gateway import RecordedGateway, load_featherless_gateway
from afterimage.agents.roles import AgentDesk
from afterimage.agents.schemas import AgentFinding, AgentReport, AgentRole
from afterimage.contracts.hashing import canonical_sha256
from afterimage.contracts.models import AccountSnapshot, ExecutionIntent
from afterimage.execution import build_alpaca_gateway, expected_account_id_hash
from afterimage.execution.alpaca_gateway import AccountPreflight
from afterimage.execution.cli_gateway import AlpacaCLIGateway
from afterimage.orchestration.coordinator import Coordinator
from afterimage.research.historical_execution import (
    HistoricalReplayGateway,
    load_historical_replay_case,
    reveal_equity_outcome,
)
from afterimage.storage import Database

ROOT = Path(__file__).resolve().parents[1]


class _CachedPaperCounterfactualDelegate:
    """Offline risk input plus the official CLI's local dry-run renderer."""

    execution_enabled = False

    def __init__(self, order_gateway: AlpacaCLIGateway) -> None:
        self.order_gateway = order_gateway

    async def preflight(self, expected_account_id_hash: str) -> AccountPreflight:
        return AccountPreflight(
            account=AccountSnapshot(
                account_id_hash=expected_account_id_hash,
                paper=True,
                status="ACTIVE",
                equity=Decimal(100000),
                last_equity=Decimal(100000),
                cash=Decimal(100000),
                options_buying_power=Decimal(100000),
                options_approved_level=3,
                options_trading_level=3,
                trading_blocked=False,
                timestamp=datetime(2026, 9, 4, tzinfo=UTC),
            ),
            market_open=False,
            clock={
                "is_open": False,
                "timestamp": "2026-09-04T00:00:00+00:00",
                "counterfactual_input": True,
            },
            open_orders=(),
            positions=(),
            capabilities={
                "transport": "alpaca-cli/0.0.14-local-dry-run",
                "execution": "disabled",
                "account_fact_source": (
                    "cached authenticated paper preflight observed 2026-09-04; "
                    "no broker read performed by this engineering replay"
                ),
            },
        )

    async def dry_run_order(self, intent: ExecutionIntent, client_order_id: str) -> dict[str, Any]:
        rendered = await self.order_gateway.dry_run_order(intent, client_order_id)
        return {
            **rendered,
            "submitted": False,
            "network_call_performed": False,
            "renderer": "official Alpaca CLI 0.0.14 --dry-run",
        }


def _recorded_replay_desk() -> AgentDesk:
    details = {
        AgentRole.STRATEGIST: (
            "support",
            "The causal candidate and admitted aggregate research packet form a falsifiable long-only shock-reversal thesis.",
            "market.candidate.features",
            "support",
        ),
        AgentRole.REGIME_WITNESS: (
            "support",
            "The causal packet contains the trend, ATR shock, and close-location observations required by the frozen rule.",
            "candidate.features",
            "support",
        ),
        AgentRole.OPTIONS_WITNESS: (
            "support",
            "The declared instrument is an equity bracket, so option fields are not required for this replay path.",
            "strategy_adapter.asset_class",
            "support",
        ),
        AgentRole.PROSECUTOR: (
            "challenge",
            "The pseudo-OOS and daily-bar limitations remain material, but they do not contradict the exact replay packet.",
            "source_packets.evidence_protocol.deployment_evidence.limitations",
            "warning",
        ),
    }
    reports = {}
    for role, (status, thesis, evidence_key, severity) in details.items():
        preimage = {"role": role.value, "status": status, "thesis": thesis}
        reports[role] = AgentReport(
            role=role,
            status=status,  # type: ignore[arg-type]
            thesis=thesis,
            findings=(
                AgentFinding(
                    claim=thesis,
                    evidence_keys=(evidence_key,),
                    severity=severity,  # type: ignore[arg-type]
                ),
            ),
            falsifiers=("Reject if the cited packet path is absent or hash binding fails.",),
            reason_code="RECORDED_HISTORICAL_REPLAY_PACKET",
            model_id="recorded-historical-replay",
            prompt_hash=canonical_sha256({"role": role.value, "mode": "recorded-replay"}),
            response_hash=canonical_sha256(preimage),
            response_preimage=preimage,
            latency_ms=0,
        )
    return AgentDesk(RecordedGateway(reports))


def _warrant_receipt(summary: dict[str, Any]) -> dict[str, Any] | None:
    warrant = summary.get("warrant")
    if not isinstance(warrant, dict):
        return None
    intent = warrant.get("intent")
    public_intent = (
        {key: value for key, value in intent.items() if key != "account_id_hash"}
        if isinstance(intent, dict)
        else None
    )
    return {
        "intent_hash": warrant.get("intent_hash"),
        "risk_vector_hash": warrant.get("risk_vector_hash"),
        "expires_at": warrant.get("expires_at"),
        "intent": public_intent,
        "signature_present": bool(warrant.get("signature")),
        "single_use": True,
    }


def _case_receipt(summary: dict[str, Any], case: Any, jury_mode: str) -> dict[str, Any]:
    payoff = summary.get("payoff")
    risk = summary.get("risk")
    outcome = None
    if (
        summary.get("state") == "SHADOW_READY"
        and isinstance(payoff, dict)
        and isinstance(risk, dict)
    ):
        outcome = reveal_equity_outcome(
            case,
            entry_price=Decimal(str(payoff["entry_price"])),
            stop_price=Decimal(str(payoff["stop_price"])),
            target_price=Decimal(str(payoff["target_price"])),
            modeled_cost_per_share=Decimal(str(payoff["modeled_costs"])),
            quantity=int(risk["quantity"]),
        )
    reports = summary.get("agents")
    provenance = summary.get("agent_provenance")
    if jury_mode == "recorded":
        provenance = {
            "mode": "recorded-historical-replay-jury-after-bounded-live-provider-timeout",
            "live_inference": False,
            "models": ["recorded-historical-replay"],
            "live_routes_verified_separately": "evidence/research/spy-live-model-receipt-v1.json",
        }
    return {
        "label": "DETERMINISTIC COUNTERFACTUAL PATH PROOF",
        "broker_pnl_claim": False,
        "production_authorized": jury_mode == "live",
        "production_ai_gate_outcome": (
            "PASSED" if jury_mode == "live" else "FAIL_CLOSED_PROVIDER_TIMEOUT"
        ),
        "authorization_boundary": (
            "The pre-approved recorded jury is an engineering fixture. It proves downstream "
            "construction only and grants no production or broker authority."
            if jury_mode == "recorded"
            else "Production AI reports completed; execution remained disabled."
        ),
        "counterfactual_state": summary.get("state"),
        "signal_date": case.signal_date.isoformat(),
        "causal_signal_cutoff": case.signal_cutoff.isoformat(),
        "future_data_visible_during_decision": False,
        "strategy": summary.get("strategy"),
        "source": {
            "name": case.source,
            "feed": case.feed,
            "data_content_hash": case.data_content_hash,
            "research_result_hash": case.result_hash,
            "causal_record_count": len(case.causal_frame.records),
        },
        "candidate": summary.get("candidate"),
        "agent_provenance": provenance,
        "agent_reports": reports,
        "deployment_evidence": summary.get("evidence"),
        "payoff": payoff,
        "risk": risk,
        "counterfactual_warrant_receipt": _warrant_receipt(summary),
        "alpaca_cli_dry_run": summary.get("dry_run"),
        "audit": summary.get("audit"),
        "order_submission_performed": bool(summary.get("broker", {}).get("order_sent", False)),
        "future_bars_revealed_after_decision": list(case.future_bars),
        "modeled_historical_outcome": outcome,
        "published_research_trade": case.published_trade,
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    database = Database(args.database_url)
    coordinator = Coordinator(database, signing_key_path=args.signing_key_path)
    broker = build_alpaca_gateway()
    cases = [
        load_historical_replay_case(args.cache, args.result, date.fromisoformat(value))
        for value in args.signal_date
    ]
    receipts: list[dict[str, Any]] = []
    try:
        if args.jury_mode == "live":
            await broker.connect()
            gateway: Any = broker
            desk = AgentDesk(load_featherless_gateway())
        else:
            if not isinstance(broker, AlpacaCLIGateway):
                raise RuntimeError("RECORDED_REPLAY_REQUIRES_OFFICIAL_ALPACA_CLI")
            gateway = _CachedPaperCounterfactualDelegate(broker)
            desk = _recorded_replay_desk()
        account_hash = expected_account_id_hash()
        for case in cases:
            summary = await coordinator.run_live_shadow(
                HistoricalReplayGateway(gateway, case),
                desk,
                account_hash,
                strategy_id="shadow_clock_shock_reversal_v1",
            )
            receipts.append(_case_receipt(summary, case, args.jury_mode))
    finally:
        await broker.close()
    completed = [
        item["modeled_historical_outcome"]
        for item in receipts
        if isinstance(item.get("modeled_historical_outcome"), dict)
    ]
    core = {
        "schema": (
            "afterimage-guavamango-historical-execution-replay-v1"
            if args.jury_mode == "live"
            else "afterimage-guavamango-engineering-replay-v2"
        ),
        "label": (
            "HISTORICAL EXECUTION REPLAY — NOT BROKER P&L"
            if args.jury_mode == "live"
            else "DETERMINISTIC ENGINEERING REPLAY — NOT AI AUTHORIZATION OR BROKER P&L"
        ),
        "purpose": (
            "Exercise the production strategy, AI gate, deterministic risk, signed warrant, and "
            "official Alpaca CLI dry-run on causal historical packets before revealing outcomes."
        ),
        "selection_disclosure": (
            "One known winner and one known loser are deliberately selected for path coverage; "
            "they are not an unbiased performance sample. Use the admitted 95-trade result for aggregate research metrics."
        ),
        "broker_pnl_claim": False,
        "jury_mode": args.jury_mode,
        "production_authorized": args.jury_mode == "live",
        "deterministic_counterfactual_only": args.jury_mode != "live",
        "production_ai_gate_outcome": (
            "PASSED" if args.jury_mode == "live" else "FAIL_CLOSED_PROVIDER_TIMEOUT"
        ),
        "live_jury_attempt": (
            "completed"
            if args.jury_mode == "live"
            else (
                "Not repeated. v1 preserves a completed fail-closed abstention; a later bounded "
                "retry was terminated on provider timeout. Exact routes are proven separately "
                "by evidence/research/spy-live-model-receipt-v1.json."
            )
        ),
        "order_submission_performed": any(
            bool(item["order_submission_performed"]) for item in receipts
        ),
        "cases": receipts,
        "coverage_summary": {
            "requested_cases": len(cases),
            "counterfactual_full_path_cases": len(completed),
            "target_outcomes": sum(item.get("outcome") == "target" for item in completed),
            "stop_outcomes": sum(item.get("outcome") == "stop" for item in completed),
            "counterfactual_modeled_net_pnl_dollars": str(
                sum(
                    (Decimal(str(item["modeled_net_pnl_dollars"])) for item in completed),
                    Decimal(0),
                )
            ),
        },
    }
    return {**core, "receipt_sha256": canonical_sha256(core)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cache",
        type=Path,
        default=ROOT
        / "experiments/strategy_candidates/event_flow/data/alpaca_daily_2015_2026.json",
    )
    parser.add_argument(
        "--result",
        type=Path,
        default=ROOT
        / "experiments/strategy_candidates/event_flow/results/event_flow_04_shadow_turnaround.json",
    )
    parser.add_argument(
        "--signal-date",
        action="append",
        default=None,
        help="Known signal date to replay; repeat for more cases.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--database-url",
        default="sqlite:///./.afterimage/historical-execution-replay.db",
    )
    parser.add_argument(
        "--signing-key-path",
        type=Path,
        default=Path(".afterimage/historical-replay-warrant.pem"),
    )
    parser.add_argument("--jury-mode", choices=("live", "recorded"), default="live")
    args = parser.parse_args()
    if args.signal_date is None:
        args.signal_date = ["2022-01-26", "2022-04-18"]
    if args.output is None:
        suffix = (
            "historical-execution-replay-v1"
            if args.jury_mode == "live"
            else "engineering-replay-v2"
        )
        args.output = ROOT / f"evidence/research/guavamango-{suffix}.json"
    payload = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"output": str(args.output), **payload["coverage_summary"]}, sort_keys=True))


if __name__ == "__main__":
    main()
