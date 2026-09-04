from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from afterimage.contracts.hashing import canonical_json, canonical_sha256
from afterimage.contracts.models import FrozenSnapshot, MarketRecord, StrategyIdentity


class PointInTimeViolation(ValueError):
    pass


class SnapshotStore:
    def __init__(self, root: str | Path = "evidence/replays/snapshots") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def build(
        self,
        cutoff: datetime,
        identity: StrategyIdentity,
        records: Sequence[MarketRecord],
        features: dict[str, float | int | str | bool | None],
    ) -> FrozenSnapshot:
        if cutoff.tzinfo is None:
            raise PointInTimeViolation("cutoff must be timezone-aware")
        eligible = []
        for record in records:
            if record.timestamp.tzinfo is None or record.received_at.tzinfo is None:
                raise PointInTimeViolation("record timestamps must be timezone-aware")
            if record.timestamp > cutoff:
                continue
            eligible.append(record)
        payload = {
            "cutoff": cutoff,
            "identity": identity,
            "features": features,
            "records": eligible,
        }
        snapshot_id = canonical_sha256(payload)
        return FrozenSnapshot(
            snapshot_id=snapshot_id,
            cutoff=cutoff,
            identity=identity,
            features=features,
            records=tuple(eligible),
            provenance={"record_count": str(len(eligible)), "future_records_excluded": "true"},
        )

    def persist(self, snapshot: FrozenSnapshot) -> Path:
        target = self.root / f"{snapshot.snapshot_id}.parquet"
        if target.exists():
            return target
        rows = [
            {
                "symbol": record.symbol,
                "timestamp": record.timestamp.isoformat(),
                "received_at": record.received_at.isoformat(),
                "source": record.source,
                "feed": record.feed,
                "kind": record.kind,
                "values_json": canonical_json(record.values).decode(),
                "snapshot_id": snapshot.snapshot_id,
            }
            for record in snapshot.records
        ]
        table = pa.Table.from_pylist(rows)
        pq.write_table(table, target, compression="zstd")
        manifest = target.with_suffix(".json")
        manifest.write_text(
            json.dumps(snapshot.model_dump(mode="json"), sort_keys=True, indent=2), encoding="utf-8"
        )
        return target
