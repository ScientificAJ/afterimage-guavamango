from __future__ import annotations

import asyncio
from typing import Any

from afterimage.contracts.hashing import canonical_sha256

from .gateway import ModelGateway
from .schemas import AgentReport, AgentRole, DeskReports


class AgentDesk:
    def __init__(self, gateway: ModelGateway) -> None:
        self.gateway = gateway

    async def deliberate(
        self,
        market_packet: dict[str, Any],
        regime_packet: dict[str, Any],
        options_packet: dict[str, Any],
        retrieval_packet: dict[str, Any],
    ) -> DeskReports:
        strategist_task = self.gateway.complete(
            AgentRole.STRATEGIST, market_packet, AgentReport, deep=True
        )
        regime_task = self.gateway.complete(AgentRole.REGIME_WITNESS, regime_packet, AgentReport)
        options_task = self.gateway.complete(AgentRole.OPTIONS_WITNESS, options_packet, AgentReport)
        strategist, regime, options = await asyncio.gather(
            strategist_task, regime_task, options_task
        )
        prosecutor_packet = {
            "reports": [
                strategist.model_dump(mode="json"),
                regime.model_dump(mode="json"),
                options.model_dump(mode="json"),
            ],
            "retrieval": retrieval_packet,
            "packet_hashes": {
                "market": canonical_sha256(market_packet),
                "regime": canonical_sha256(regime_packet),
                "options": canonical_sha256(options_packet),
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
