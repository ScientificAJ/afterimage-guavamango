from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from afterimage.contracts.hashing import canonical_json, canonical_sha256

from .db import Database
from .models import ArtifactRow, BrokerOrderRow, RiskStateRow, SessionRow


class Repository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert_session(
        self,
        session_id: str,
        state: str,
        strategy_id: str,
        strategy_version: str,
        payload: dict[str, Any],
    ) -> None:
        now = datetime.now(UTC)
        with self.database.session() as session:
            row = session.get(SessionRow, session_id)
            if row is None:
                row = SessionRow(
                    id=session_id,
                    state=state,
                    strategy_id=strategy_id,
                    strategy_version=strategy_version,
                    payload_json=canonical_json(payload).decode(),
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            else:
                row.state = state
                row.payload_json = canonical_json(payload).decode()
                row.updated_at = now

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self.database.session() as session:
            row = session.get(SessionRow, session_id)
            if row is None:
                return None
            return {
                "id": row.id,
                "state": row.state,
                "strategy_id": row.strategy_id,
                "strategy_version": row.strategy_version,
                "payload": json.loads(row.payload_json),
            }

    def save_artifact(
        self, session_id: str, kind: str, payload: Any, artifact_hash: str | None = None
    ) -> str:
        artifact_hash = artifact_hash or canonical_sha256(payload)
        with self.database.session() as session:
            existing = session.scalar(
                select(ArtifactRow).where(
                    ArtifactRow.kind == kind, ArtifactRow.artifact_hash == artifact_hash
                )
            )
            if existing is None:
                session.add(
                    ArtifactRow(
                        session_id=session_id,
                        kind=kind,
                        artifact_hash=artifact_hash,
                        payload_json=canonical_json(payload).decode(),
                        created_at=datetime.now(UTC),
                    )
                )
        return artifact_hash

    def get_artifact(self, kind: str, artifact_hash: str) -> dict[str, Any] | None:
        with self.database.session() as session:
            row = session.scalar(
                select(ArtifactRow).where(
                    ArtifactRow.kind == kind, ArtifactRow.artifact_hash == artifact_hash
                )
            )
            return json.loads(row.payload_json) if row else None

    def session_artifacts(self, session_id: str, kind: str | None = None) -> list[dict[str, Any]]:
        with self.database.session() as session:
            query = select(ArtifactRow).where(ArtifactRow.session_id == session_id)
            if kind is not None:
                query = query.where(ArtifactRow.kind == kind)
            rows = session.scalars(query.order_by(ArtifactRow.id)).all()
            return [
                {
                    "kind": row.kind,
                    "hash": row.artifact_hash,
                    "payload": json.loads(row.payload_json),
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]

    def warrant_by_id(self, warrant_id: str) -> dict[str, Any] | None:
        with self.database.session() as session:
            rows = session.scalars(select(ArtifactRow).where(ArtifactRow.kind == "warrant")).all()
            for row in rows:
                payload = json.loads(row.payload_json)
                if str(payload.get("warrant_id")) == warrant_id:
                    return payload if isinstance(payload, dict) else None
        return None

    def broker_orders(self, session_id: str) -> list[dict[str, Any]]:
        with self.database.session() as session:
            rows = session.scalars(
                select(BrokerOrderRow)
                .where(BrokerOrderRow.session_id == session_id)
                .order_by(BrokerOrderRow.updated_at)
            ).all()
            payloads = [json.loads(row.payload_json) for row in rows]
            return [payload for payload in payloads if isinstance(payload, dict)]

    def save_broker_order(self, session_id: str, order: dict[str, Any], intent_hash: str) -> None:
        now = datetime.now(UTC)
        with self.database.session() as session:
            broker_id = str(order["id"])
            row = session.get(BrokerOrderRow, broker_id)
            if row is None:
                row = session.scalar(
                    select(BrokerOrderRow).where(
                        BrokerOrderRow.client_order_id == str(order["client_order_id"])
                    )
                )
                if row is not None and row.broker_order_id != broker_id:
                    if not row.broker_order_id.startswith("pending:"):
                        raise ValueError("BROKER_ORDER_IDENTITY_CONFLICT")
                    session.delete(row)
                    session.flush()
                    row = None
            if row is None:
                row = BrokerOrderRow(
                    broker_order_id=broker_id,
                    client_order_id=str(order["client_order_id"]),
                    session_id=session_id,
                    intent_hash=intent_hash,
                    status=str(order.get("status", "unknown")),
                    payload_json=canonical_json(order).decode(),
                    updated_at=now,
                )
                session.add(row)
            else:
                row.status = str(order.get("status", row.status))
                row.payload_json = canonical_json(order).decode()
                row.updated_at = now

    def observe_account_equity(
        self, account_id_hash: str, session_date: date, equity: Decimal
    ) -> Decimal:
        """Persist the intraday account high-water mark used by the drawdown gate."""
        now = datetime.now(UTC)
        with self.database.session() as session:
            identity = {"account_id_hash": account_id_hash, "session_date": session_date}
            row = session.get(RiskStateRow, identity)
            if row is None:
                row = RiskStateRow(
                    account_id_hash=account_id_hash,
                    session_date=session_date,
                    high_water_equity=equity,
                    updated_at=now,
                )
                session.add(row)
            elif equity > row.high_water_equity:
                row.high_water_equity = equity
                row.updated_at = now
            return Decimal(row.high_water_equity)

    def active_session_ids(self) -> list[str]:
        active = {
            "SUBMITTING",
            "WORKING",
            "FILLED",
            "EXITING",
            "CLOSED",
            "AMBIGUOUS",
            "PARTIAL_OR_ANOMALOUS",
        }
        with self.database.session() as session:
            rows = session.scalars(
                select(SessionRow)
                .where(SessionRow.state.in_(active))
                .order_by(SessionRow.updated_at)
            ).all()
            return [row.id for row in rows]
