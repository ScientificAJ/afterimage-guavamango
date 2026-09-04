from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from afterimage.agents.gateway import FeatherlessGateway, load_featherless_gateway
from afterimage.agents.prompts import PROMPT_VERSION
from afterimage.agents.schemas import AgentReport, AgentRole
from afterimage.contracts.hashing import canonical_sha256


def valid_report() -> dict[str, object]:
    return {
        "status": "support",
        "thesis": "The claim is falsifiable and packet-bound.",
        "findings": [
            {
                "claim": "The packet contains a frozen snapshot.",
                "evidence_keys": ["snapshot.snapshot_id"],
                "severity": "support",
            }
        ],
        "falsifiers": ["Reject if the snapshot hash cannot be reproduced."],
        "reason_code": "PACKET_BOUND_SUPPORT",
    }


def test_gateway_uses_real_routed_models_and_application_headers() -> None:
    observed: dict[str, object] = {}

    async def respond(request: httpx.Request) -> httpx.Response:
        observed["headers"] = dict(request.headers)
        observed["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            headers={"x-request-id": "provider-request-123"},
            json={
                "id": "completion-123",
                "created": 1788510000,
                "system_fingerprint": "fp-test",
                "choices": [{"message": {"content": json.dumps(valid_report())}}],
            },
        )

    gateway = FeatherlessGateway(api_key="secret", transport=httpx.MockTransport(respond))

    report = asyncio.run(
        gateway.complete(
            AgentRole.STRATEGIST, {"snapshot": {"snapshot_id": "abc"}}, AgentReport, deep=True
        )
    )

    body = observed["body"]
    headers = observed["headers"]
    assert isinstance(body, dict)
    assert body["model"] == "zai-org/GLM-5.3"
    assert body["reasoning_effort"] == "high"
    assert body["max_tokens"] == 6000
    assert "response_format" not in body
    assert isinstance(headers, dict)
    assert headers["x-title"] == "AFTERIMAGE"
    assert headers["http-referer"] == "https://github.com/afterimage-agent/afterimage"
    assert report.model_id == "zai-org/GLM-5.3"
    assert report.role == AgentRole.STRATEGIST
    assert report.prompt_version == PROMPT_VERSION
    assert report.input_packet_hash == canonical_sha256({"snapshot": {"snapshot_id": "abc"}})
    assert report.response_preimage == valid_report()
    assert report.response_hash == canonical_sha256(report.response_preimage)
    assert report.provider_request_id == "provider-request-123"
    assert report.provider_created_at == 1788510000
    assert report.provider_system_fingerprint == "fp-test"


def test_gateway_extracts_json_after_reasoning_text() -> None:
    content = 'analysis with {"draft": true}\n' + json.dumps(valid_report())
    observed: dict[str, object] = {}

    async def respond(request: httpx.Request) -> httpx.Response:
        observed["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    gateway = FeatherlessGateway(api_key="secret", transport=httpx.MockTransport(respond))

    report = asyncio.run(
        gateway.complete(
            AgentRole.REGIME_WITNESS,
            {"snapshot": {"snapshot_id": "abc"}},
            AgentReport,
        )
    )

    assert report.status == "support"
    assert report.model_id == "zai-org/GLM-5.3-Flash"
    body = observed["body"]
    assert isinstance(body, dict)
    assert body["reasoning_effort"] == "low"


def test_gateway_fails_closed_to_abstention_on_invalid_output() -> None:
    async def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    gateway = FeatherlessGateway(api_key="secret", transport=httpx.MockTransport(respond))

    report = asyncio.run(gateway.complete(AgentRole.OPTIONS_WITNESS, {"chain": {}}, AgentReport))

    assert report.status == "abstain"
    assert report.reason_code == "JSONDECODEERROR"


def test_gateway_role_routing_is_fixed_even_when_deep_hint_is_wrong() -> None:
    observed: list[dict[str, object]] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        observed.append(body)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(valid_report())}}]},
        )

    gateway = FeatherlessGateway(api_key="secret", transport=httpx.MockTransport(respond))

    async def invoke_all() -> None:
        packet = {"snapshot": {"snapshot_id": "abc"}}
        await gateway.complete(AgentRole.STRATEGIST, packet, AgentReport, deep=False)
        await gateway.complete(AgentRole.REGIME_WITNESS, packet, AgentReport, deep=True)
        await gateway.complete(AgentRole.OPTIONS_WITNESS, packet, AgentReport, deep=True)
        await gateway.complete(AgentRole.PROSECUTOR, packet, AgentReport, deep=False)

    asyncio.run(invoke_all())

    assert [body["model"] for body in observed] == [
        "zai-org/GLM-5.3",
        "zai-org/GLM-5.3-Flash",
        "zai-org/GLM-5.3-Flash",
        "zai-org/GLM-5.3",
    ]
    assert [body["reasoning_effort"] for body in observed] == [
        "high",
        "low",
        "low",
        "high",
    ]


def test_system_prompts_encode_grounding_abstention_and_role_mandates() -> None:
    prompts = {role: FeatherlessGateway._prompt(role) for role in AgentRole}

    for prompt in prompts.values():
        assert f"Prompt version: {PROMPT_VERSION}" in prompt
        assert "falsifiable" in prompt
        assert "Distinguish direct observations from inferences" in prompt
        assert "Cite precise dot/bracket field paths" in prompt
        assert "Never invent or backfill" in prompt
        assert "Abstain when" in prompt
        assert "Pydantic output schema" in prompt
        assert "return only its single" in prompt

    assert "trade-or-no-trade thesis" in prompts[AgentRole.STRATEGIST]
    assert "Do not defer to or imitate the strategist" in prompts[AgentRole.REGIME_WITNESS]
    assert "If it is equities" in prompts[AgentRole.OPTIONS_WITNESS]
    assert "look-ahead leakage" in prompts[AgentRole.PROSECUTOR]
    assert "every prior report" in prompts[AgentRole.PROSECUTOR]


def test_static_output_contract_precedes_dynamic_evidence_packet() -> None:
    observed: dict[str, object] = {}

    async def respond(request: httpx.Request) -> httpx.Response:
        observed["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(valid_report())}}]},
        )

    gateway = FeatherlessGateway(api_key="secret", transport=httpx.MockTransport(respond))
    asyncio.run(
        gateway.complete(
            AgentRole.STRATEGIST,
            {"snapshot": {"snapshot_id": "dynamic-value"}},
            AgentReport,
        )
    )

    body = observed["body"]
    assert isinstance(body, dict)
    messages = body["messages"]
    assert isinstance(messages, list)
    assert messages[0]["role"] == "system"
    user_content = messages[1]["content"]
    assert user_content.index('"output_schema"') < user_content.index('"evidence_packet"')

    request_contract = json.loads(user_content)
    assert request_contract["allowed_evidence_paths"] == [
        "snapshot",
        "snapshot.snapshot_id",
    ]
    required = request_contract["output_schema"]["required"]
    assert "status" in required
    assert "findings" in required
    assert "model_id" not in required
    assert "prompt_hash" not in required
    assert "response_hash" not in required
    assert "latency_ms" not in required


def test_gateway_repairs_only_invalid_citations_once() -> None:
    invalid = valid_report()
    invalid["findings"] = [
        {
            "claim": "The packet contains a frozen snapshot.",
            "evidence_keys": ["snapshot.id"],
            "severity": "support",
            "basis": "observation",
        }
    ]
    repaired = valid_report()
    calls: list[dict[str, object]] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        content = invalid if len(calls) == 1 else repaired
        return httpx.Response(
            200,
            headers={"x-request-id": f"provider-request-{len(calls)}"},
            json={"choices": [{"message": {"content": json.dumps(content)}}]},
        )

    gateway = FeatherlessGateway(api_key="secret", transport=httpx.MockTransport(respond))
    report = asyncio.run(
        gateway.complete(
            AgentRole.STRATEGIST,
            {"snapshot": {"snapshot_id": "abc"}},
            AgentReport,
        )
    )

    assert len(calls) == 2
    assert report.status == "support"
    assert report.findings[0].evidence_keys == ("snapshot.snapshot_id",)
    assert report.provider_request_id == "provider-request-2"
    assert report.response_preimage == repaired
    repair_messages = calls[1]["messages"]
    assert isinstance(repair_messages, list)
    repair_contract = json.loads(repair_messages[-1]["content"])
    assert repair_contract["task"] == "repair_evidence_citations_only"
    assert repair_contract["allowed_evidence_paths"] == [
        "snapshot",
        "snapshot.snapshot_id",
    ]


def test_gateway_rejects_a_citation_repair_that_changes_the_thesis() -> None:
    invalid = valid_report()
    invalid["findings"] = [
        {
            "claim": "The packet contains a frozen snapshot.",
            "evidence_keys": ["snapshot.id"],
            "severity": "support",
            "basis": "observation",
        }
    ]
    changed = valid_report()
    changed["thesis"] = "A different trading conclusion."
    calls = 0

    async def respond(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        content = invalid if calls == 1 else changed
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(content)}}]},
        )

    gateway = FeatherlessGateway(api_key="secret", transport=httpx.MockTransport(respond))
    report = asyncio.run(
        gateway.complete(
            AgentRole.STRATEGIST,
            {"snapshot": {"snapshot_id": "abc"}},
            AgentReport,
        )
    )

    assert calls == 2
    assert report.status == "abstain"
    assert report.reason_code == "EVIDENCE_REPAIR_CHANGED_CONCLUSION"


def test_gateway_abstains_when_a_report_cites_a_nonexistent_packet_path() -> None:
    invalid = valid_report()
    invalid["findings"] = [
        {
            "claim": "Invented evidence path.",
            "evidence_keys": ["snapshot.missing_price"],
            "severity": "support",
            "basis": "observation",
        }
    ]

    calls = 0

    async def respond(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(invalid)}}]},
        )

    gateway = FeatherlessGateway(api_key="secret", transport=httpx.MockTransport(respond))
    report = asyncio.run(
        gateway.complete(
            AgentRole.STRATEGIST,
            {"snapshot": {"snapshot_id": "abc"}},
            AgentReport,
        )
    )

    assert calls == 2
    assert report.status == "abstain"
    assert report.reason_code == "EVIDENCE_PATH_INVALID"


def test_gateway_loader_reads_ignored_private_key_file(tmp_path: Path, monkeypatch: object) -> None:
    key_path = tmp_path / "featherless-api-key"
    key_path.write_text("rc_test_secret\n")
    monkeypatch.setenv("FEATHERLESS_BASE_URL", "https://models.example/v1")  # type: ignore[attr-defined]

    gateway = load_featherless_gateway(key_path=key_path)

    assert gateway.configured is True
    assert gateway.base_url == "https://models.example/v1"
    assert key_path.stat().st_mode & 0o777 == 0o600
    assert "rc_test_secret" not in repr(gateway)
