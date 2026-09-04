from __future__ import annotations

import json
import os
import re
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from afterimage.contracts.hashing import canonical_sha256

from .prompts import PROMPT_VERSION, system_prompt
from .schemas import AgentFinding, AgentReport, AgentRole

T = TypeVar("T", bound=BaseModel)

_DEEP_ROLES = frozenset({AgentRole.STRATEGIST, AgentRole.PROSECUTOR})
_BRACKET_INDEX = re.compile(r"\[(\d+)\]")


class EvidencePathError(ValueError):
    pass


class EvidenceRepairChangedConclusion(ValueError):
    pass


class ModelGateway(ABC):
    @abstractmethod
    async def complete(
        self, role: AgentRole, packet: dict[str, Any], output_type: type[T], deep: bool = False
    ) -> T:
        raise NotImplementedError


class FeatherlessGateway(ModelGateway):
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.featherless.ai/v1",
        deep_model: str = "zai-org/GLM-5.3",
        fast_model: str = "zai-org/GLM-5.3-Flash",
        timeout_seconds: float = 90.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.deep_model = deep_model
        self.fast_model = fast_model
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip())

    def __repr__(self) -> str:
        return (
            "FeatherlessGateway(api_key=<redacted>, "
            f"deep_model={self.deep_model!r}, fast_model={self.fast_model!r})"
        )

    @staticmethod
    def _prompt(role: AgentRole) -> str:
        return system_prompt(role)

    @staticmethod
    def _path_exists(packet: dict[str, Any], evidence_key: str) -> bool:
        path = evidence_key.removeprefix("packet.")
        path = _BRACKET_INDEX.sub(r".\1", path)
        if not path or path.startswith("."):
            return False
        current: Any = packet
        for part in path.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, list) and part.isdigit():
                index = int(part)
                if index >= len(current):
                    return False
                current = current[index]
            else:
                return False
        return True

    @classmethod
    def _validate_evidence_paths(cls, report: AgentReport, packet: dict[str, Any]) -> None:
        if report.status == "abstain":
            return
        for finding in report.findings:
            if not finding.evidence_keys or not all(
                cls._path_exists(packet, key) for key in finding.evidence_keys
            ):
                raise EvidencePathError("report cites a missing evidence path")

    @classmethod
    def _evidence_paths(cls, packet: dict[str, Any]) -> tuple[str, ...]:
        paths: set[str] = set()

        def visit(value: Any, prefix: str) -> None:
            if isinstance(value, dict):
                for key in sorted(value):
                    path = f"{prefix}.{key}" if prefix else str(key)
                    paths.add(path)
                    visit(value[key], path)
            elif isinstance(value, (list, tuple)):
                for index, item in enumerate(value):
                    path = f"{prefix}[{index}]"
                    paths.add(path)
                    visit(item, path)

        visit(packet, "")
        return tuple(sorted(paths))

    @staticmethod
    def _model_output_schema(output_type: type[T]) -> dict[str, Any]:
        schema = output_type.model_json_schema()
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            return schema
        gateway_fields = {
            "role",
            "model_id",
            "prompt_version",
            "prompt_hash",
            "input_packet_hash",
            "response_hash",
            "response_preimage",
            "provider_request_id",
            "provider_created_at",
            "provider_system_fingerprint",
            "latency_ms",
        }
        for field in gateway_fields:
            properties.pop(field, None)
        required = schema.get("required")
        if isinstance(required, list):
            schema["required"] = [field for field in required if field not in gateway_fields]
        return schema

    @staticmethod
    def _decision_without_citations(report: AgentReport) -> dict[str, Any]:
        return {
            "status": report.status,
            "thesis": report.thesis,
            "findings": [
                {
                    "claim": finding.claim,
                    "severity": finding.severity,
                    "basis": finding.basis,
                }
                for finding in report.findings
            ],
            "falsifiers": list(report.falsifiers),
            "reason_code": report.reason_code,
        }

    @staticmethod
    def _abstention(
        role: AgentRole,
        model_id: str,
        prompt_hash: str,
        input_packet_hash: str,
        reason: str,
        latency: int,
    ) -> AgentReport:
        return AgentReport(
            role=role,
            status="abstain",
            thesis="No model conclusion is admitted.",
            findings=(AgentFinding(claim=reason, evidence_keys=(), severity="warning"),),
            falsifiers=("A valid schema-conforming response is required.",),
            reason_code=reason,
            model_id=model_id,
            prompt_version=PROMPT_VERSION,
            prompt_hash=prompt_hash,
            input_packet_hash=input_packet_hash,
            response_hash=canonical_sha256({"reason": reason}),
            response_preimage={"reason": reason},
            latency_ms=latency,
        )

    @staticmethod
    def _json_object(content: str) -> dict[str, Any]:
        try:
            value = json.loads(content)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
        decoder = json.JSONDecoder()
        candidates: list[tuple[int, dict[str, Any]]] = []
        for index, character in enumerate(content):
            if character != "{":
                continue
            try:
                value, end = decoder.raw_decode(content[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                candidates.append((end, value))
        if candidates:
            return max(candidates, key=lambda item: item[0])[1]
        raise json.JSONDecodeError("no JSON object found", content, 0)

    async def complete(
        self, role: AgentRole, packet: dict[str, Any], output_type: type[T], deep: bool = False
    ) -> T:
        del deep
        is_deep_role = role in _DEEP_ROLES
        model = self.deep_model if is_deep_role else self.fast_model
        prompt = self._prompt(role)
        output_schema = self._model_output_schema(output_type)
        allowed_evidence_paths = list(self._evidence_paths(packet))
        prompt_hash = canonical_sha256(
            {
                "prompt_version": PROMPT_VERSION,
                "role": role.value,
                "system_prompt": prompt,
                "output_schema": output_schema,
            }
        )
        input_packet_hash = canonical_sha256(packet)
        started = time.perf_counter()
        messages = [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "output_schema": output_schema,
                        "allowed_evidence_paths": allowed_evidence_paths,
                        "evidence_packet": packet,
                    },
                    separators=(",", ":"),
                ),
            },
        ]
        body = {
            "model": model,
            "temperature": 0,
            "seed": 0,
            "reasoning_effort": "high" if is_deep_role else "low",
            "max_tokens": 6000 if is_deep_role else 2200,
            "messages": messages,
        }

        def validated_result(
            response: httpx.Response, envelope: dict[str, Any], content: str
        ) -> tuple[T, dict[str, Any]]:
            parsed = self._json_object(content)
            for reserved in (
                "role",
                "model_id",
                "prompt_version",
                "prompt_hash",
                "input_packet_hash",
                "response_hash",
                "response_preimage",
                "provider_request_id",
                "provider_created_at",
                "provider_system_fingerprint",
                "latency_ms",
            ):
                parsed.pop(reserved, None)
            response_preimage = dict(parsed)
            request_id = response.headers.get("x-request-id") or envelope.get("id")
            created_at = envelope.get("created")
            fingerprint = envelope.get("system_fingerprint")
            parsed.update(
                {
                    "role": role,
                    "model_id": model,
                    "prompt_version": PROMPT_VERSION,
                    "prompt_hash": prompt_hash,
                    "input_packet_hash": input_packet_hash,
                    "response_hash": canonical_sha256(response_preimage),
                    "response_preimage": response_preimage,
                    "provider_request_id": str(request_id) if request_id else None,
                    "provider_created_at": created_at if isinstance(created_at, int) else None,
                    "provider_system_fingerprint": (str(fingerprint) if fingerprint else None),
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                }
            )
            return output_type.model_validate(parsed), response_preimage

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds, transport=self.transport
            ) as client:

                async def send(request_body: dict[str, Any]) -> tuple[T, dict[str, Any]]:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "HTTP-Referer": "https://github.com/afterimage-agent/afterimage",
                            "X-Title": "AFTERIMAGE",
                        },
                        json=request_body,
                    )
                    response.raise_for_status()
                    envelope = response.json()
                    content = envelope["choices"][0]["message"]["content"]
                    if not isinstance(content, str):
                        raise TypeError("completion content must be text")
                    return validated_result(response, envelope, content)

                result, response_preimage = await send(body)
                if not isinstance(result, AgentReport):
                    return result
                try:
                    self._validate_evidence_paths(result, packet)
                    return result
                except EvidencePathError:
                    repair_messages = [
                        *messages,
                        {
                            "role": "assistant",
                            "content": json.dumps(response_preimage, separators=(",", ":")),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "task": "repair_evidence_citations_only",
                                    "instruction": (
                                        "Keep the decision, thesis, findings, severities, bases, "
                                        "falsifiers, and reason_code unchanged. Replace only "
                                        "evidence_keys with exact entries from allowed_evidence_paths. "
                                        "If no listed path supports a finding, return an abstention."
                                    ),
                                    "allowed_evidence_paths": allowed_evidence_paths,
                                },
                                separators=(",", ":"),
                            ),
                        },
                    ]
                    repaired, _ = await send({**body, "messages": repair_messages})
                    if not isinstance(repaired, AgentReport):
                        raise TypeError("citation repair must return an agent report")
                    if repaired.status != "abstain" and self._decision_without_citations(
                        repaired
                    ) != self._decision_without_citations(result):
                        raise EvidenceRepairChangedConclusion(
                            "citation repair changed the model conclusion"
                        )
                    self._validate_evidence_paths(repaired, packet)
                    return output_type.model_validate(repaired.model_dump())
        except EvidencePathError:
            latency = int((time.perf_counter() - started) * 1000)
            report = self._abstention(
                role,
                model,
                prompt_hash,
                input_packet_hash,
                "EVIDENCE_PATH_INVALID",
                latency,
            )
            return output_type.model_validate(report.model_dump())
        except EvidenceRepairChangedConclusion:
            latency = int((time.perf_counter() - started) * 1000)
            report = self._abstention(
                role,
                model,
                prompt_hash,
                input_packet_hash,
                "EVIDENCE_REPAIR_CHANGED_CONCLUSION",
                latency,
            )
            return output_type.model_validate(report.model_dump())
        except (
            TimeoutError,
            httpx.HTTPError,
            KeyError,
            json.JSONDecodeError,
            ValidationError,
            TypeError,
        ) as exc:
            latency = int((time.perf_counter() - started) * 1000)
            report = self._abstention(
                role,
                model,
                prompt_hash,
                input_packet_hash,
                type(exc).__name__.upper(),
                latency,
            )
            return output_type.model_validate(report.model_dump())


def load_featherless_gateway(
    key_path: str | Path = ".afterimage/featherless-api-key",
) -> FeatherlessGateway:
    api_key = os.getenv("FEATHERLESS_API_KEY", "").strip()
    if not api_key:
        try:
            path = Path(key_path)
            if path.is_symlink():
                raise RuntimeError("FEATHERLESS_CREDENTIAL_PATH_INVALID")
            os.chmod(path.parent, 0o700)
            os.chmod(path, 0o600)
            api_key = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError as exc:
            raise RuntimeError("FEATHERLESS_CREDENTIALS_MISSING") from exc
    if not api_key:
        raise RuntimeError("FEATHERLESS_CREDENTIALS_MISSING")
    return FeatherlessGateway(
        api_key=api_key,
        base_url=os.getenv("FEATHERLESS_BASE_URL", "https://api.featherless.ai/v1"),
        deep_model=os.getenv("AFTERIMAGE_DEEP_MODEL", "zai-org/GLM-5.3"),
        fast_model=os.getenv("AFTERIMAGE_FAST_MODEL", "zai-org/GLM-5.3-Flash"),
    )


class RecordedGateway(ModelGateway):
    def __init__(self, reports: dict[AgentRole, AgentReport]) -> None:
        self.reports = reports

    async def complete(
        self, role: AgentRole, packet: dict[str, Any], output_type: type[T], deep: bool = False
    ) -> T:
        del packet, deep
        return output_type.model_validate(self.reports[role].model_dump())
