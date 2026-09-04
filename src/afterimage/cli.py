from __future__ import annotations

import asyncio
import ipaddress
import json
import os
from collections.abc import Coroutine
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any, TypeVar, cast

import typer
import uvicorn

from afterimage.agents.gateway import load_featherless_gateway
from afterimage.agents.roles import AgentDesk
from afterimage.contracts.hashing import canonical_sha256
from afterimage.contracts.models import ExecutionWarrant
from afterimage.evidence.export import evidence_core, evidence_core_hash
from afterimage.execution import build_alpaca_gateway, expected_account_id_hash
from afterimage.execution.reconciler import Reconciler
from afterimage.orchestration.coordinator import Coordinator
from afterimage.research import (
    OptionHistoryGateway,
    OptionValidationManifest,
    acquire_research_dataset,
    build_forward_trial_precommit,
    load_research_dataset,
    public_research_manifest,
    validate_option_trade_bars,
    verify_forward_trial_precommit,
    write_forward_trial_precommit,
)
from afterimage.storage import Database
from afterimage.strategies.registry import default_registry

app = typer.Typer(help="AFTERIMAGE evidence-gated options agent", no_args_is_help=True)
tournament_app = typer.Typer(help="Sealed strategy laboratory", no_args_is_help=True)
research_app = typer.Typer(help="Hash-bound Alpaca research data", no_args_is_help=True)
app.add_typer(tournament_app, name="tournament")
app.add_typer(research_app, name="research")
T = TypeVar("T")


def runtime() -> Coordinator:
    return Coordinator(
        Database(os.getenv("AFTERIMAGE_DB_URL", "sqlite:///./.afterimage/afterimage.db")),
        signing_key_path=os.getenv(
            "AFTERIMAGE_SIGNING_KEY_PATH", ".afterimage/warrant-ed25519.pem"
        ),
    )


def render(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


def write_json(output: Path | None, payload: Any) -> None:
    text = render(payload)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    typer.echo(text)


def run_async(operation: Coroutine[Any, Any, T]) -> T:
    try:
        return asyncio.run(operation)
    except Exception as exc:
        typer.echo(render({"status": "blocked", "reason": str(exc)}), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def replay(
    fixture: Annotated[
        str, typer.Option(help="accepted or rejected deterministic replay")
    ] = "accepted",
    output: Annotated[Path | None, typer.Option()] = None,
) -> None:
    if fixture not in {"accepted", "rejected"}:
        raise typer.BadParameter("fixture must be accepted or rejected")
    write_json(output, runtime().run_demo(accepted=fixture == "accepted"))


@app.command(hidden=True)
def demo(
    fixture: Annotated[str, typer.Option()] = "accepted",
    output: Annotated[Path | None, typer.Option()] = None,
) -> None:
    replay(fixture, output)


async def _preflight() -> dict[str, Any]:
    gateway = build_alpaca_gateway()
    try:
        await gateway.connect()
        result = await gateway.preflight(expected_account_id_hash())
        return result.model_dump(mode="json")
    finally:
        await gateway.close()


@app.command()
def preflight() -> None:
    """Verify the allowlisted paper account and least-privilege MCP boundaries."""
    write_json(None, run_async(_preflight()))


async def _build_research(
    symbol: str,
    training_start: date,
    training_end: date,
    holdout_start: date,
    holdout_end: date,
    embargo_sessions: int,
    private_path: Path,
    public_path: Path,
) -> dict[str, object]:
    gateway = build_alpaca_gateway()
    try:
        await gateway.connect()
        await gateway.preflight(expected_account_id_hash())
        dataset = await acquire_research_dataset(
            gateway,
            default_registry(),
            symbol=symbol.upper(),
            training_start=training_start,
            training_end=training_end,
            holdout_start=holdout_start,
            holdout_end=holdout_end,
            embargo_sessions=embargo_sessions,
            private_path=private_path,
            public_path=public_path,
            received_at=datetime.now(UTC),
        )
        return public_research_manifest(dataset)
    finally:
        await gateway.close()


@research_app.command("build")
def research_build(
    symbol: str = "SPY",
    training_start: Annotated[str, typer.Option()] = "2025-01-02",
    training_end: Annotated[str, typer.Option()] = "2026-06-23",
    holdout_start: Annotated[str, typer.Option()] = "2026-07-01",
    holdout_end: Annotated[str, typer.Option()] = "2026-09-03",
    embargo_sessions: Annotated[int, typer.Option(min=1)] = 5,
    private_path: Annotated[Path, typer.Option()] = Path(".afterimage/research/spy-real-v1.json"),
    public_path: Annotated[Path, typer.Option()] = Path(
        "evidence/research/spy-real-v1-manifest.json"
    ),
) -> None:
    """Acquire real Alpaca bars and seal train/holdout strategy evidence."""
    try:
        boundaries = tuple(
            date.fromisoformat(value)
            for value in (training_start, training_end, holdout_start, holdout_end)
        )
    except ValueError as exc:
        raise typer.BadParameter("research dates must be ISO YYYY-MM-DD") from exc
    write_json(
        None,
        run_async(
            _build_research(
                symbol,
                boundaries[0],
                boundaries[1],
                boundaries[2],
                boundaries[3],
                embargo_sessions,
                private_path,
                public_path,
            )
        ),
    )


async def _validate_options(
    dataset_path: Path, strategy_id: str, public_path: Path
) -> dict[str, Any]:
    gateway = build_alpaca_gateway()
    try:
        await gateway.connect()
        await gateway.preflight(expected_account_id_hash())
        if not callable(getattr(gateway, "option_bars", None)):
            raise TypeError("OPTION_HISTORY_REQUIRES_OFFICIAL_CLI_TRANSPORT")
        manifest = await validate_option_trade_bars(
            cast(OptionHistoryGateway, gateway),
            load_research_dataset(dataset_path),
            strategy_id=strategy_id,
            public_path=public_path,
        )
        return manifest.model_dump(mode="json")
    finally:
        await gateway.close()


@research_app.command("validate-options")
def research_validate_options(
    dataset_path: Annotated[Path, typer.Option()] = Path(".afterimage/research/spy-real-v1.json"),
    strategy_id: Annotated[str, typer.Option()] = "opening_range_failure_v1",
    public_path: Annotated[Path, typer.Option()] = Path(
        "evidence/research/spy-option-trade-bars-v3.json"
    ),
) -> None:
    """Validate holdout signals with real Alpaca historical option trade bars."""
    write_json(
        None,
        run_async(_validate_options(dataset_path, strategy_id, public_path)),
    )


def _aware_datetime(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise typer.BadParameter(f"{name} must include a UTC offset")
    return parsed


@research_app.command("precommit-paper")
def research_precommit_paper(
    dataset_path: Annotated[Path, typer.Option()] = Path(".afterimage/research/spy-real-v1.json"),
    output: Annotated[Path, typer.Option()] = Path("evidence/research/forward-paper-trial-v2.json"),
    starts_at: Annotated[str, typer.Option()] = "2026-09-04T13:30:00+00:00",
    signal_cutoff_at: Annotated[str, typer.Option()] = "2026-09-04T13:55:00+00:00",
    forced_exit_at: Annotated[str, typer.Option()] = "2026-09-04T14:45:00+00:00",
    supersedes: Annotated[str | None, typer.Option()] = "forward-paper-trial-v1.json",
) -> None:
    """Freeze a self-verifying paper trial before its market window."""
    if output.exists():
        raise typer.BadParameter("precommit output already exists")
    dataset = load_research_dataset(dataset_path)
    precommit = build_forward_trial_precommit(
        root=Path.cwd(),
        created_at=datetime.now(UTC),
        starts_at=_aware_datetime(starts_at, "starts-at"),
        signal_cutoff_at=_aware_datetime(signal_cutoff_at, "signal-cutoff-at"),
        forced_exit_at=_aware_datetime(forced_exit_at, "forced-exit-at"),
        research_dataset_sha256=dataset.dataset_hash,
        supersedes=supersedes,
    )
    write_forward_trial_precommit(output, precommit)
    verification = verify_forward_trial_precommit(
        precommit,
        root=Path.cwd(),
        research_dataset_sha256=dataset.dataset_hash,
        observed_at=datetime.now(UTC),
    )
    write_json(None, {"path": str(output), "verification": verification})


@research_app.command("verify-paper-precommit")
def research_verify_paper_precommit(
    precommit_path: Annotated[Path, typer.Option()] = Path(
        "evidence/research/forward-paper-trial-v2.json"
    ),
    dataset_path: Annotated[Path, typer.Option()] = Path(".afterimage/research/spy-real-v1.json"),
) -> None:
    """Recompute every public forward-trial commitment from the current tree."""
    try:
        precommit = json.loads(precommit_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise typer.BadParameter("precommit artifact is missing or invalid") from exc
    if not isinstance(precommit, dict):
        raise typer.BadParameter("precommit artifact must be an object")
    dataset = load_research_dataset(dataset_path)
    verification = verify_forward_trial_precommit(
        precommit,
        root=Path.cwd(),
        research_dataset_sha256=dataset.dataset_hash,
        observed_at=datetime.now(UTC),
    )
    write_json(None, verification)
    if not verification["valid"]:
        raise typer.Exit(code=1)


async def _validate_models(
    dataset_path: Path, option_path: Path, strategy_id: str
) -> dict[str, Any]:
    dataset = load_research_dataset(dataset_path)
    option_manifest = OptionValidationManifest.model_validate_json(
        option_path.read_text(encoding="utf-8")
    )
    if option_manifest.dataset_hash != dataset.dataset_hash:
        raise ValueError("MODEL_VALIDATION_DATASET_HASH_MISMATCH")
    evaluation = dataset.holdout.evaluations.get(strategy_id)
    if evaluation is None or not evaluation.rows or not option_manifest.results:
        raise ValueError("MODEL_VALIDATION_PACKET_UNAVAILABLE")
    option_by_signal = {item.signal_id: item for item in option_manifest.results}
    try:
        row = next(item for item in evaluation.rows if item.private_row_id in option_by_signal)
    except StopIteration as exc:
        raise ValueError("MODEL_VALIDATION_OPTION_SIGNAL_MISMATCH") from exc
    option = option_by_signal[row.private_row_id]
    market_packet = {
        "source": dataset.source,
        "feed": dataset.feed,
        "dataset_hash": dataset.dataset_hash,
        "signal_id": row.private_row_id,
        "signal_at": row.signal_at.isoformat() if row.signal_at else None,
        "direction": row.direction,
        "signal_price": str(row.signal_price) if row.signal_price is not None else None,
        "features": row.features,
        "outcomes_visible": False,
    }
    regime_packet = {
        "partition": "chronological-evaluation",
        "partition_source_hash": dataset.holdout.source_hash,
        "session_date": row.session_date.isoformat(),
        "outcomes_visible": False,
    }
    options_packet = {
        "source": option_manifest.source,
        "pricing_basis": option_manifest.pricing_basis,
        "long_symbol": option.long_symbol,
        "short_symbol": option.short_symbol,
        "expiration_date": option.expiration_date.isoformat(),
        "entry_at": option.entry_at.isoformat(),
        "entry_debit": str(option.entry_debit),
        "future_path_visible": False,
    }
    evidence_packet = {
        "protocol": "sealed-twins-v1",
        "dataset_hash": dataset.dataset_hash,
        "outcomes_visible": False,
    }
    reports = await AgentDesk(load_featherless_gateway()).deliberate(
        market_packet, regime_packet, options_packet, evidence_packet
    )
    report_values = (
        reports.strategist,
        reports.regime_witness,
        reports.options_witness,
        reports.prosecutor,
    )
    expected_models = {"zai-org/GLM-5.3", "zai-org/GLM-5.3-Flash"}
    observed_models = {report.model_id for report in report_values}
    return {
        "schema": "afterimage-live-model-receipt-v1",
        "mode": "live Featherless inference over a real Alpaca historical candidate",
        "dataset_hash": dataset.dataset_hash,
        "candidate_packet_hash": canonical_sha256(market_packet),
        "outcomes_visible": False,
        "expected_models": sorted(expected_models),
        "observed_models": sorted(observed_models),
        "exact_routes_verified": observed_models == expected_models,
        "all_roles_non_abstaining": not Coordinator._agent_blocks(reports),
        "blocking_reasons": Coordinator._agent_blocks(reports),
        "reports": reports.model_dump(mode="json"),
    }


@research_app.command("validate-models")
def research_validate_models(
    dataset_path: Annotated[Path, typer.Option()] = Path(".afterimage/research/spy-real-v1.json"),
    option_path: Annotated[Path, typer.Option()] = Path(
        "evidence/research/spy-option-trade-bars-v3.json"
    ),
    strategy_id: Annotated[str, typer.Option()] = "opening_range_failure_v1",
    output: Annotated[Path, typer.Option()] = Path(
        "evidence/research/spy-live-model-receipt-v1.json"
    ),
) -> None:
    """Call the exact Featherless routes on one real, outcome-blind Alpaca packet."""
    write_json(
        output,
        run_async(_validate_models(dataset_path, option_path, strategy_id)),
    )


async def _bind_account() -> dict[str, Any]:
    gateway = build_alpaca_gateway()
    try:
        await gateway.connect()
        bind = getattr(gateway, "bind_account", None)
        if bind is None:
            raise RuntimeError("ACCOUNT_BINDING_REQUIRES_CLI_TRANSPORT")
        account_hash = await bind()
        return {"status": "bound", "paper": True, "account_hash_prefix": account_hash[:12]}
    finally:
        await gateway.close()


@app.command("bind-account")
def bind_account() -> None:
    """One-way bind AFTERIMAGE to the OAuth profile's current paper account."""
    write_json(None, run_async(_bind_account()))


async def _shadow(symbol: str | None = None, strategy_id: str | None = None) -> dict[str, Any]:
    gateway = build_alpaca_gateway()
    coordinator = runtime()
    try:
        await gateway.connect()
        return await coordinator.run_live_shadow(
            gateway,
            AgentDesk(load_featherless_gateway()),
            expected_account_id_hash(),
            symbol=symbol.upper() if symbol is not None else None,
            strategy_id=strategy_id,
        )
    finally:
        await gateway.close()


@app.command()
def shadow(
    symbol: str | None = None,
    strategy_id: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Run live Alpaca/Featherless analysis through a local Alpaca order dry-run."""
    write_json(None, run_async(_shadow(symbol, strategy_id)))


async def _autopilot(
    symbol: str | None,
    strategy_id: str | None,
    execute: bool,
    cycles: int,
    interval_seconds: float,
) -> list[dict[str, Any]]:
    if cycles < 0:
        raise ValueError("cycles must be zero (continuous) or positive")
    gateway = build_alpaca_gateway()
    coordinator = runtime()
    desk = AgentDesk(load_featherless_gateway())
    results: list[dict[str, Any]] = []
    try:
        await gateway.connect()
        completed = 0
        while cycles == 0 or completed < cycles:
            active_sessions = coordinator.managed_session_ids()
            if active_sessions:
                if not execute:
                    raise RuntimeError("ACTIVE_PAPER_LIFECYCLE_REQUIRES_EXECUTION_MODE")
                for session_id in active_sessions:
                    results.append(
                        await coordinator.manage_live_position(
                            gateway, expected_account_id_hash(), session_id
                        )
                    )
            else:
                results.append(
                    await coordinator.run_live_cycle(
                        gateway,
                        desk,
                        expected_account_id_hash(),
                        symbol=symbol.upper() if symbol is not None else None,
                        strategy_id=strategy_id,
                        execute=execute,
                    )
                )
            completed += 1
            if cycles == 0 or completed < cycles:
                await asyncio.sleep(max(5.0, interval_seconds))
        return results
    finally:
        await gateway.close()


@app.command()
def autopilot(
    symbol: str | None = None,
    strategy_id: Annotated[str | None, typer.Option()] = None,
    execute: Annotated[
        bool,
        typer.Option(help="Permit paper submission after every gate; also requires env gate."),
    ] = False,
    cycles: Annotated[int, typer.Option(help="Number of cycles; zero runs continuously.")] = 1,
    interval_seconds: Annotated[float, typer.Option(min=5.0)] = 60.0,
) -> None:
    """Run deduplicated autonomous paper cycles; execution remains double-gated."""
    write_json(
        None,
        run_async(_autopilot(symbol, strategy_id, execute, cycles, interval_seconds)),
    )


@tournament_app.command("develop")
def tournament_develop(output: Annotated[Path | None, typer.Option()] = None) -> None:
    """Show the recorded fixture without making a performance claim."""
    write_json(
        output,
        {
            "mode": "recorded-engineering-fixture",
            "performance_claim": False,
            "tournament": runtime()._recorded_fixture_tournament(),
        },
    )


@tournament_app.command("reveal")
def tournament_reveal(
    dataset_path: Annotated[Path, typer.Option()] = Path(".afterimage/research/spy-real-v1.json"),
    output: Annotated[Path, typer.Option()] = Path("evidence/tournament/spy-real-v1-results.json"),
) -> None:
    """Score every strategy implementation on the real Alpaca holdout."""
    tournament = runtime().run_research_tournament(dataset_path)
    write_json(output, {"mode": "real-chronological-holdout", "tournament": tournament})


async def _execute(session_id: str, warrant_id: str) -> dict[str, Any]:
    if os.getenv("AFTERIMAGE_ENABLE_PAPER_EXECUTION", "false").lower() != "true":
        raise typer.BadParameter("paper execution is disabled by AFTERIMAGE_ENABLE_PAPER_EXECUTION")
    coordinator = runtime()
    payload = coordinator.repository.warrant_by_id(warrant_id)
    if payload is None:
        raise typer.BadParameter("warrant ID not found")
    warrant = ExecutionWarrant.model_validate(payload)
    gateway = build_alpaca_gateway()
    try:
        await gateway.connect()
        checked = await gateway.preflight(expected_account_id_hash())
        if checked.account.account_id_hash != warrant.intent.account_id_hash:
            raise typer.BadParameter("warrant account does not match the allowlisted paper account")
        return await coordinator.submit_shadow_session(
            gateway, expected_account_id_hash(), session_id, warrant
        )
    finally:
        await gateway.close()


@app.command()
def execute(session_id: str, warrant_id: str) -> None:
    """Submit one exact, unexpired, single-use warrant to the paper account."""
    write_json(None, run_async(_execute(session_id, warrant_id)))


async def _manage(session_id: str) -> dict[str, Any]:
    if os.getenv("AFTERIMAGE_ENABLE_PAPER_EXECUTION", "false").lower() != "true":
        raise typer.BadParameter("paper execution is disabled by AFTERIMAGE_ENABLE_PAPER_EXECUTION")
    gateway = build_alpaca_gateway()
    coordinator = runtime()
    try:
        await gateway.connect()
        return await coordinator.manage_live_position(
            gateway, expected_account_id_hash(), session_id
        )
    finally:
        await gateway.close()


@app.command()
def manage(session_id: str) -> None:
    """Reconcile and watchdog one existing paper position through signed exit/autopsy."""
    write_json(None, run_async(_manage(session_id)))


async def _reconcile(client_order_id: str) -> dict[str, Any]:
    gateway = build_alpaca_gateway()
    try:
        await gateway.connect()
        await gateway.preflight(expected_account_id_hash())
        return (await Reconciler(gateway).by_client_id(client_order_id)).__dict__
    finally:
        await gateway.close()


@app.command()
def reconcile(client_order_id: str) -> None:
    """Treat Alpaca broker state as truth for a known idempotent client order ID."""
    write_json(None, run_async(_reconcile(client_order_id)))


@app.command("export-evidence")
def export_evidence(
    fixture: Annotated[str, typer.Option()] = "accepted",
    output_dir: Annotated[Path, typer.Option()] = Path("evidence/submission"),
) -> None:
    if fixture not in {"accepted", "rejected"}:
        raise typer.BadParameter("fixture must be accepted or rejected")
    summary = runtime().run_demo(accepted=fixture == "accepted")
    digest = evidence_core_hash(summary)
    envelope = {
        "schema": "afterimage-evidence-envelope-v1",
        "evidence_core_sha256": digest,
        "audit_valid": summary["audit"]["valid"],
        "evidence_core": evidence_core(summary),
        "run_record": summary,
    }
    target = output_dir / f"{fixture}-{digest[:12]}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(envelope), encoding="utf-8")
    typer.echo(str(target))


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    try:
        loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        if not os.getenv("AFTERIMAGE_OPERATOR_TOKEN", "").strip():
            raise typer.BadParameter("remote binding requires AFTERIMAGE_OPERATOR_TOKEN")
        os.environ["AFTERIMAGE_REQUIRE_OPERATOR_AUTH"] = "true"
    uvicorn.run("afterimage.api.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    app()
