from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import select

from afterimage.contracts.hashing import canonical_json
from afterimage.contracts.models import SessionEvent

from .db import Database
from .models import AuditRow

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
