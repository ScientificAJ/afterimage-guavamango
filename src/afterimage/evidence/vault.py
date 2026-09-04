from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from afterimage.contracts.models import RevealedOutcome


class HistoricalRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    private_row_id: str
    session_date: date
    cluster_id: str
    signal_at: datetime | None = None
    direction: Literal["bullish", "bearish", "long_volatility"] | None = None
    signal_price: Decimal | None = None
    features: dict[str, float]
    target_first: bool | None
    return_r: Decimal
    placebo_return_r: Decimal
    censored: bool = False
    path: tuple[Decimal, ...] = ()


class BlindFeatureRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    twin_id: str
    cluster_id: str
    features: dict[str, float]


class OutcomeVault:
    def __init__(self, rows: Iterable[HistoricalRow], salt: str) -> None:
        self._rows = {self._twin_id(row.private_row_id, salt): row for row in rows}
        self._salt = salt

    @staticmethod
    def _twin_id(private_row_id: str, salt: str) -> str:
        return "twin_" + hashlib.sha256(f"{salt}:{private_row_id}".encode()).hexdigest()[:16]

    def blind_rows(self) -> tuple[BlindFeatureRow, ...]:
        return tuple(
            BlindFeatureRow(twin_id=twin_id, cluster_id=row.cluster_id, features=row.features)
            for twin_id, row in sorted(self._rows.items())
        )

    def reveal(self, twin_ids: Iterable[str]) -> tuple[RevealedOutcome, ...]:
        revealed = []
        for twin_id in twin_ids:
            row = self._rows.get(twin_id)
            if row is None:
                raise KeyError(f"unknown committed twin {twin_id}")
            revealed.append(
                RevealedOutcome(
                    twin_id=twin_id,
                    session_date=row.session_date,
                    target_first=row.target_first,
                    return_r=row.return_r,
                    placebo_return_r=row.placebo_return_r,
                    censored=row.censored,
                    path=row.path,
                )
            )
        return tuple(revealed)
