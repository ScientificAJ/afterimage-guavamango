from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Coroutine
from pathlib import Path
from typing import Annotated, Any, TypeVar

import typer
import uvicorn

from afterimage.contracts.hashing import canonical_sha256
from afterimage.contracts.models import ExecutionWarrant
from afterimage.execution import ExecutionService, build_alpaca_gateway, expected_account_id
from afterimage.execution.reconciler import Reconciler
from afterimage.orchestration.coordinator import Coordinator
from afterimage.storage import Database

app = typer.Typer(help="AFTERIMAGE evidence-gated options agent", no_args_is_help=True)
tournament_app = typer.Typer(help="Sealed strategy laboratory", no_args_is_help=True)
app.add_typer(tournament_app, name="tournament")
T = TypeVar("T")


def runtime() -> Coordinator:
    return Coordinator(
        Database(os.getenv("AFTERIMAGE_DB_URL", "sqlite:///./afterimage.db")),
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
        result = await gateway.preflight(expected_account_id())
        return result.model_dump(mode="json")
    finally:
        await gateway.close()


@app.command()
def preflight() -> None:
    """Verify the allowlisted paper account and least-privilege MCP boundaries."""
    write_json(None, run_async(_preflight()))


@app.command()
def shadow() -> None:
    """Connect read-only, reconcile broker truth, and emit no order."""
    payload = run_async(_preflight())
    payload["mode"] = "shadow"
    payload["order_authority_used"] = False
    write_json(None, payload)


@tournament_app.command("develop")
def tournament_develop(output: Annotated[Path | None, typer.Option()] = None) -> None:
    """Produce a development tournament without final-holdout promotion authority."""
    summary = runtime().run_demo(accepted=True)
    write_json(output, {"mode": "development", "tournament": summary.get("tournament")})


@tournament_app.command("reveal")
def tournament_reveal(output: Annotated[Path | None, typer.Option()] = None) -> None:
    """Run the sealed recorded fixture and reveal all candidates, including losers."""
    summary = runtime().run_demo(accepted=True)
    write_json(output, {"mode": "sealed-recorded-reveal", "tournament": summary.get("tournament")})


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
        checked = await gateway.preflight(expected_account_id())
        if checked.account.account_id_hash != warrant.intent.account_id_hash:
            raise typer.BadParameter("warrant account does not match the allowlisted paper account")
        service = ExecutionService(gateway, coordinator.warrants, coordinator.repository)
        return (await service.submit(session_id, warrant)).model_dump(mode="json")
    finally:
        await gateway.close()


@app.command()
def execute(session_id: str, warrant_id: str) -> None:
    """Submit one exact, unexpired, single-use warrant to the paper account."""
    write_json(None, run_async(_execute(session_id, warrant_id)))


async def _reconcile(client_order_id: str) -> dict[str, Any]:
    gateway = build_alpaca_gateway()
    try:
        await gateway.connect()
        await gateway.preflight(expected_account_id())
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
    digest = canonical_sha256(summary)
    envelope = {"sha256": digest, "audit_valid": summary["audit"]["valid"], "payload": summary}
    target = output_dir / f"{fixture}-{digest[:12]}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(envelope), encoding="utf-8")
    typer.echo(str(target))


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    uvicorn.run("afterimage.api.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    app()
