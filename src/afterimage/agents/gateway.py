from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from afterimage.contracts.hashing import canonical_sha256

from .schemas import AgentFinding, AgentReport, AgentRole

T = TypeVar("T", bound=BaseModel)


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
        timeout_seconds: float = 20.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.deep_model = deep_model
        self.fast_model = fast_model
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _prompt(role: AgentRole) -> str:
        boundaries = (
            "Return only JSON matching the supplied schema. Cite packet keys for every claim. "
            "Do not invent data, contracts, prices, probabilities, or authority. Abstain when evidence is missing."
        )
        prompts = {
            AgentRole.STRATEGIST: "Build a falsifiable thesis from the frozen market packet.",
            AgentRole.REGIME_WITNESS: "Judge whether the candidate is compatible with the observed regime.",
            AgentRole.OPTIONS_WITNESS: "Audit option liquidity, Greeks, synchronization, and scenario behavior.",
            AgentRole.PROSECUTOR: "Attack leakage, instability, hidden assumptions, and unsupported conclusions.",
        }
        return f"{prompts[role]} {boundaries}"

    @staticmethod
    def _abstention(
        role: AgentRole, model_id: str, prompt_hash: str, reason: str, latency: int
    ) -> AgentReport:
        return AgentReport(
            role=role,
            status="abstain",
            thesis="No model conclusion is admitted.",
            findings=(AgentFinding(claim=reason, evidence_keys=(), severity="warning"),),
            falsifiers=("A valid schema-conforming response is required.",),
            reason_code=reason,
            model_id=model_id,
            prompt_hash=prompt_hash,
            response_hash=canonical_sha256({"reason": reason}),
            latency_ms=latency,
        )

    async def complete(
        self, role: AgentRole, packet: dict[str, Any], output_type: type[T], deep: bool = False
    ) -> T:
        model = self.deep_model if deep else self.fast_model
        prompt = self._prompt(role)
        prompt_hash = canonical_sha256(prompt)
        started = time.perf_counter()
        body = {
            "model": model,
            "temperature": 0,
            "max_tokens": 1200,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"packet": packet, "schema": output_type.model_json_schema()}
                    ),
                },
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=body,
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            parsed.update(
                {
                    "role": role,
                    "model_id": model,
                    "prompt_hash": prompt_hash,
                    "response_hash": canonical_sha256(parsed),
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                }
            )
            return output_type.model_validate(parsed)
        except (
            TimeoutError,
            httpx.HTTPError,
            KeyError,
            json.JSONDecodeError,
            ValidationError,
        ) as exc:
            latency = int((time.perf_counter() - started) * 1000)
            report = self._abstention(role, model, prompt_hash, type(exc).__name__.upper(), latency)
            return output_type.model_validate(report.model_dump())


class RecordedGateway(ModelGateway):
    def __init__(self, reports: dict[AgentRole, AgentReport]) -> None:
        self.reports = reports

    async def complete(
        self, role: AgentRole, packet: dict[str, Any], output_type: type[T], deep: bool = False
    ) -> T:
        del packet, deep
        return output_type.model_validate(self.reports[role].model_dump())
