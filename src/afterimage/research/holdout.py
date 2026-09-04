from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from afterimage.contracts.hashing import canonical_sha256
from afterimage.contracts.models import MarketRecord
from afterimage.evidence import HistoricalRow
from afterimage.strategies.base import MarketFrame, StrategyPlugin

ET = ZoneInfo("America/New_York")


class HoldoutEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    strategy_id: str
    sessions_scanned: int
    signals: int
    source_record_count: int
    source_hash: str
    rows: tuple[HistoricalRow, ...]


def evaluate_strategy_holdout(
    records: Sequence[MarketRecord], strategy: StrategyPlugin
) -> HoldoutEvaluation:
    ordered = tuple(
        sorted(
            (
                record
                for record in records
                if record.kind == "bar"
                and time(9, 30) <= record.timestamp.astimezone(ET).time() <= time(16)
            ),
            key=lambda record: record.timestamp,
        )
    )
    source_hash = canonical_sha256(
        [record.model_dump(mode="json", exclude={"received_at"}) for record in ordered]
    )
    by_session: dict[date, list[MarketRecord]] = defaultdict(list)
    for record in ordered:
        by_session[record.timestamp.astimezone(ET).date()].append(record)
    decision_time_by_strategy = {
        "opening_range_failure_v1": time(10, 0),
        "momentum_continuation_v1": time(10, 5),
        "volatility_dislocation_v1": time(10, 5),
    }
    decision_time = decision_time_by_strategy[strategy.identity.strategy_id]
    rows: list[HistoricalRow] = []
    for session_date, session_records in sorted(by_session.items()):
        eligible = tuple(
            record
            for record in session_records
            if (record.timestamp + timedelta(minutes=5)).astimezone(ET).time() <= decision_time
        )
        if not eligible:
            continue
        closes = [float(record.values["close"]) for record in eligible]
        volumes = [float(record.values.get("volume", 0)) for record in eligible]
        midpoint = max(1, len(volumes) // 2)
        first_volume = sum(volumes[:midpoint]) / max(1, len(volumes[:midpoint]))
        second_volume = sum(volumes[midpoint:]) / max(1, len(volumes[midpoint:]))
        returns = [
            closes[index] / closes[index - 1] - 1
            for index in range(1, len(closes))
            if closes[index - 1]
        ]
        context = {
            "relative_volume": second_volume / first_volume if first_volume else 0,
            "realized_volatility": (sum(value * value for value in returns) / len(returns)) ** 0.5
            * (252 * 78) ** 0.5
            if returns
            else 0,
        }
        snapshot = strategy.freeze(
            MarketFrame(
                symbol=eligible[0].symbol,
                cutoff=eligible[-1].timestamp + timedelta(minutes=5),
                records=eligible,
                context=context,
            )
        )
        candidate = strategy.detect(snapshot)
        if candidate is None:
            continue
        future = tuple(
            record
            for record in session_records
            if candidate.signal_at <= record.timestamp < strategy.exit_plan(candidate).exit_at
        )
        if not future:
            continue
        signal_price = Decimal(str(eligible[-1].values["close"]))
        opening = eligible[:3]
        opening_width = Decimal(
            str(
                max(float(record.values["high"]) for record in opening)
                - min(float(record.values["low"]) for record in opening)
            )
        )
        risk_unit = max(signal_price * Decimal("0.001"), opening_width * Decimal("0.20"))
        path: list[Decimal] = [Decimal(0)]
        target_first: bool | None = None
        return_r = Decimal(0)
        for record in future:
            high = Decimal(str(record.values["high"]))
            low = Decimal(str(record.values["low"]))
            close = Decimal(str(record.values["close"]))
            if candidate.direction == "bullish":
                favorable = (high - signal_price) / risk_unit
                adverse = (low - signal_price) / risk_unit
                close_r = (close - signal_price) / risk_unit
            elif candidate.direction == "bearish":
                favorable = (signal_price - low) / risk_unit
                adverse = (signal_price - high) / risk_unit
                close_r = (signal_price - close) / risk_unit
            else:
                favorable = max(abs(high - signal_price), abs(low - signal_price)) / risk_unit
                adverse = Decimal(0)
                close_r = abs(close - signal_price) / risk_unit
            path.append(max(Decimal(-1), min(Decimal(3), close_r)))
            if adverse <= -1:
                target_first = False
                return_r = Decimal(-1)
                break
            if favorable >= 3:
                target_first = True
                return_r = Decimal(3)
                break
        censored = target_first is None
        if censored:
            return_r = path[-1]
        numeric_features = {
            key: float(value)
            for key, value in candidate.features.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        private_row_id = canonical_sha256(
            {
                "strategy": strategy.identity.model_dump(),
                "session_date": str(session_date),
                "snapshot_id": snapshot.snapshot_id,
                "source_hash": source_hash,
            }
        )
        iso_year, iso_week, _ = session_date.isocalendar()
        rows.append(
            HistoricalRow(
                private_row_id=private_row_id,
                session_date=session_date,
                cluster_id=f"{iso_year}-W{iso_week:02d}",
                signal_at=candidate.signal_at,
                direction=candidate.direction,
                signal_price=signal_price,
                features=numeric_features,
                target_first=target_first,
                return_r=return_r,
                placebo_return_r=max(Decimal(-1), min(Decimal(3), -path[-1])),
                censored=censored,
                path=tuple(path),
            )
        )
    return HoldoutEvaluation(
        strategy_id=strategy.identity.strategy_id,
        sessions_scanned=len(by_session),
        signals=len(rows),
        source_record_count=len(ordered),
        source_hash=source_hash,
        rows=tuple(rows),
    )
