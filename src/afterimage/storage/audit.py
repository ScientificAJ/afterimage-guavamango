from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from afterimage.contracts.hashing import canonical_json
from afterimage.contracts.models import SessionEvent

from .db import Database
from .models import AuditRow, SessionRow

GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class AuditVerification:
    valid: bool
    records: int
    failed_sequence: int | None = None


class AuditLedger:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _record_hash(previous_hash: str, sequence: int, event_type: str, payload: bytes) -> str:
        material = previous_hash.encode() + str(sequence).encode() + event_type.encode() + payload
        return hashlib.sha256(material).hexdigest()

    def append(self, event: SessionEvent) -> str:
        payload = canonical_json(event.model_dump(mode="json"))
        with self.database.session() as session:
            previous = session.scalar(
                select(AuditRow)
                .where(AuditRow.session_id == str(event.session_id))
                .order_by(AuditRow.sequence.desc())
                .limit(1)
            )
            previous_hash = previous.record_hash if previous else GENESIS_HASH
            record_hash = self._record_hash(
                previous_hash, event.sequence, event.event_type, payload
            )
            session.add(
                AuditRow(
                    session_id=str(event.session_id),
                    sequence=event.sequence,
                    event_type=event.event_type,
                    payload_json=payload.decode(),
                    previous_hash=previous_hash,
                    record_hash=record_hash,
                    created_at=event.created_at,
                )
            )
        return record_hash

    def append_and_upsert_session(self, event: SessionEvent) -> str:
        """Commit the audit event and materialized session state together."""
        payload = canonical_json(event.model_dump(mode="json"))
        now = datetime.now(UTC)
        with self.database.session() as session:
            previous = session.scalar(
                select(AuditRow)
                .where(AuditRow.session_id == str(event.session_id))
                .order_by(AuditRow.sequence.desc())
                .limit(1)
            )
            previous_hash = previous.record_hash if previous else GENESIS_HASH
            record_hash = self._record_hash(
                previous_hash, event.sequence, event.event_type, payload
            )
            session.add(
                AuditRow(
                    session_id=str(event.session_id),
                    sequence=event.sequence,
                    event_type=event.event_type,
                    payload_json=payload.decode(),
                    previous_hash=previous_hash,
                    record_hash=record_hash,
                    created_at=event.created_at,
                )
            )
            row = session.get(SessionRow, str(event.session_id))
            if row is None:
                row = SessionRow(
                    id=str(event.session_id),
                    state=event.state.value,
                    strategy_id=event.versions.strategy_id,
                    strategy_version=event.versions.strategy_version,
                    payload_json=payload.decode(),
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            else:
                row.state = event.state.value
                row.strategy_id = event.versions.strategy_id
                row.strategy_version = event.versions.strategy_version
                row.payload_json = payload.decode()
                row.updated_at = now
        return record_hash

    def verify(self, session_id: str | None = None) -> AuditVerification:
        with self.database.session() as session:
            statement = select(AuditRow).order_by(AuditRow.session_id, AuditRow.sequence)
            if session_id:
                statement = statement.where(AuditRow.session_id == session_id)
            rows = list(session.scalars(statement))
        previous_by_session: dict[str, str] = {}
        for row in rows:
            previous = previous_by_session.get(row.session_id, GENESIS_HASH)
            expected = self._record_hash(
                previous, row.sequence, row.event_type, row.payload_json.encode()
            )
            if row.previous_hash != previous or row.record_hash != expected:
                return AuditVerification(False, len(rows), row.sequence)
            previous_by_session[row.session_id] = row.record_hash
        return AuditVerification(True, len(rows))

    def events(self, session_id: str) -> tuple[SessionEvent, ...]:
        """Load the authoritative event stream after verifying its hash chain."""
        verification = self.verify(session_id)
        if not verification.valid:
            raise ValueError("AUDIT_CHAIN_INVALID")
        with self.database.session() as session:
            rows = session.scalars(
                select(AuditRow)
                .where(AuditRow.session_id == session_id)
                .order_by(AuditRow.sequence)
            ).all()
            return tuple(SessionEvent.model_validate_json(row.payload_json) for row in rows)
