from __future__ import annotations

import asyncio
from typing import Any

from afterimage.contracts.hashing import canonical_sha256

from .gateway import ModelGateway
from .schemas import AgentReport, AgentRole, DeskReports


class AgentDesk:
    def __init__(self, gateway: ModelGateway) -> None:
        self.gateway = gateway

    @staticmethod
    def _strategy_adapter(
        market_packet: dict[str, Any], options_packet: dict[str, Any]
    ) -> dict[str, Any]:
        declared = market_packet.get("strategy_adapter")
        if isinstance(declared, dict):
            return declared
        candidate = market_packet.get("candidate")
        structures = (
            candidate.get("permitted_structures", ()) if isinstance(candidate, dict) else ()
        )
        option_markers = {
            "contracts",
            "snapshots",
            "long_symbol",
            "short_symbol",
            "expiration_date",
            "contract_count",
        }
        option_structures = {
            "call_debit_vertical",
            "put_debit_vertical",
            "debit_vertical",
            "credit_vertical",
            "iron_condor",
            "straddle",
            "strangle",
        }
        asset_class = (
            "options"
            if option_markers.intersection(options_packet)
            or (
                isinstance(structures, (list, tuple))
                and bool(option_structures.intersection(structures))
            )
            else "unspecified"
        )
        return {
            "asset_class": asset_class,
            "asset_class_source": "derived_from_supplied_packet_markers",
        }

    async def deliberate(
        self,
        market_packet: dict[str, Any],
        regime_packet: dict[str, Any],
        options_packet: dict[str, Any],
        retrieval_packet: dict[str, Any],
    ) -> DeskReports:
        candidate = market_packet.get("candidate")
        strategy_adapter = self._strategy_adapter(market_packet, options_packet)
        strategist_packet = {
            "market": market_packet,
            "evidence_protocol": retrieval_packet,
        }
        regime_witness_packet = {
            "candidate": candidate,
            "market": market_packet,
            "regime": regime_packet,
            "evidence_protocol": retrieval_packet,
        }
        execution_witness_packet = {
            "candidate": candidate,
            "strategy_adapter": strategy_adapter,
            "market": market_packet,
            "execution": options_packet,
            "evidence_protocol": retrieval_packet,
        }
        strategist_task = self.gateway.complete(
            AgentRole.STRATEGIST, strategist_packet, AgentReport, deep=True
        )
        regime_task = self.gateway.complete(
            AgentRole.REGIME_WITNESS, regime_witness_packet, AgentReport
        )
        options_task = self.gateway.complete(
            AgentRole.OPTIONS_WITNESS, execution_witness_packet, AgentReport
        )
        strategist, regime, options = await asyncio.gather(
            strategist_task, regime_task, options_task
        )
        prosecutor_packet = {
            "candidate": candidate,
            "reports": [
                strategist.model_dump(mode="json"),
                regime.model_dump(mode="json"),
                options.model_dump(mode="json"),
            ],
            "source_packets": {
                "market": market_packet,
                "regime": regime_packet,
                "execution": options_packet,
                "evidence_protocol": retrieval_packet,
                "strategy_adapter": strategy_adapter,
            },
            "packet_hashes": {
                "market": canonical_sha256(market_packet),
                "regime": canonical_sha256(regime_packet),
                "options": canonical_sha256(options_packet),
                "evidence_protocol": canonical_sha256(retrieval_packet),
            },
        }
        prosecutor = await self.gateway.complete(
            AgentRole.PROSECUTOR, prosecutor_packet, AgentReport, deep=True
        )
        return DeskReports(
            strategist=strategist,
            regime_witness=regime,
            options_witness=options,
            prosecutor=prosecutor,
        )
