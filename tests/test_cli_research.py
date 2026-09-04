from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from test_live_shadow_integration import report
from test_option_research import OptionHistoryGateway
from test_real_holdout import session
from typer.testing import CliRunner

from afterimage.agents.schemas import AgentReport, AgentRole
from afterimage.cli import _validate_models, app
from afterimage.research import (
    build_research_dataset,
    persist_research_dataset,
    validate_option_trade_bars,
)
from afterimage.strategies.registry import default_registry


def test_research_build_command_is_exposed() -> None:
    result = CliRunner().invoke(app, ["research", "build", "--help"])

    assert result.exit_code == 0
    assert "Alpaca" in result.stdout
    assert "private-path" in result.stdout
    assert "public-path" in result.stdout


def test_tournament_reveal_requires_the_real_hash_bound_dataset() -> None:
    result = CliRunner().invoke(app, ["tournament", "reveal", "--help"])

    assert result.exit_code == 0
    assert "dataset-path" in result.stdout
    assert "synthetic" not in result.stdout.lower()


def test_research_option_validation_command_is_exposed() -> None:
    result = CliRunner().invoke(app, ["research", "validate-options", "--help"])

    assert result.exit_code == 0
    assert "trade bars" in result.stdout
    assert "dataset-path" in result.stdout


def test_research_live_model_validation_command_is_exposed() -> None:
    result = CliRunner().invoke(app, ["research", "validate-models", "--help"])

    assert result.exit_code == 0
    assert "exact Featherless" in result.stdout
    assert "dataset-path" in result.stdout


@pytest.mark.usefixtures("monkeypatch")
def test_live_model_validation_packet_is_json_serializable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = build_research_dataset(
        session(date(2026, 6, 29), "target")
        + session(date(2026, 6, 30), "stop")
        + session(date(2026, 7, 1), "target"),
        default_registry(),
        training_start=date(2026, 6, 29),
        training_end=date(2026, 6, 29),
        holdout_start=date(2026, 7, 1),
        holdout_end=date(2026, 7, 1),
        embargo_sessions=1,
    )
    dataset_path = tmp_path / "research.json"
    persist_research_dataset(dataset, dataset_path, tmp_path / "research-public.json")
    option_path = tmp_path / "options.json"
    asyncio.run(
        validate_option_trade_bars(
            OptionHistoryGateway(),
            dataset,
            strategy_id="opening_range_failure_v1",
            public_path=option_path,
        )
    )

    class SerializingGateway:
        async def complete(
            self,
            role: AgentRole,
            packet: dict[str, Any],
            output_type: type[AgentReport],
            deep: bool = False,
        ) -> AgentReport:
            del deep
            json.dumps(packet)
            return output_type.model_validate(report(role).model_dump())

    monkeypatch.setattr("afterimage.cli.load_featherless_gateway", lambda: SerializingGateway())

    receipt = asyncio.run(_validate_models(dataset_path, option_path, "opening_range_failure_v1"))

    assert receipt["exact_routes_verified"] is False
    assert receipt["all_roles_non_abstaining"] is True
