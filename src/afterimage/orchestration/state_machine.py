from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from afterimage.contracts.enums import EvidenceLevel, SessionState
from afterimage.contracts.models import SessionEvent, StrategyIdentity, VersionStamp
from afterimage.storage import AuditLedger, Repository


class InvalidTransition(RuntimeError):
    pass


ALLOWED: dict[SessionState, dict[str, SessionState]] = {
    SessionState.BOOTSTRAP: {"precheck_passed": SessionState.PRECHECKED},
    SessionState.PRECHECKED: {"observe": SessionState.OBSERVING},
    SessionState.OBSERVING: {
        "snapshot_frozen": SessionState.SNAPSHOT_FROZEN,
        "no_signal": SessionState.NO_SIGNAL,
    },
    SessionState.SNAPSHOT_FROZEN: {
        "candidate_created": SessionState.SIGNAL_CANDIDATE,
        "no_signal": SessionState.NO_SIGNAL,
    },
    SessionState.SIGNAL_CANDIDATE: {
        "evidence_committed": SessionState.EVIDENCE_COMMITTED,
        "rejected": SessionState.REJECTED,
    },
    SessionState.EVIDENCE_COMMITTED: {"evidence_revealed": SessionState.EVIDENCE_REVEALED},
    SessionState.EVIDENCE_REVEALED: {
        "risk_approved": SessionState.RISK_APPROVED,
        "rejected": SessionState.REJECTED,
        "insufficient_evidence": SessionState.INSUFFICIENT_EVIDENCE,
    },
    SessionState.RISK_APPROVED: {"warrant_minted": SessionState.WARRANT_MINTED},
    SessionState.WARRANT_MINTED: {
        "submit_started": SessionState.SUBMITTING,
        "shadow_ready": SessionState.SHADOW_READY,
        "insufficient_evidence": SessionState.INSUFFICIENT_EVIDENCE,
        "warrant_expired": SessionState.EXPIRED,
    },
    SessionState.SHADOW_READY: {
        "submit_started": SessionState.SUBMITTING,
        "insufficient_evidence": SessionState.INSUFFICIENT_EVIDENCE,
    },
    SessionState.SUBMITTING: {
        "working": SessionState.WORKING,
        "filled": SessionState.FILLED,
        "partial_fill": SessionState.PARTIAL_OR_ANOMALOUS,
        "ambiguous": SessionState.AMBIGUOUS,
        "anomaly": SessionState.PARTIAL_OR_ANOMALOUS,
    },
    SessionState.AMBIGUOUS: {
        "working": SessionState.WORKING,
        "filled": SessionState.FILLED,
        "partial_fill": SessionState.PARTIAL_OR_ANOMALOUS,
        "rejected": SessionState.REJECTED,
        "anomaly": SessionState.PARTIAL_OR_ANOMALOUS,
    },
    SessionState.WORKING: {
        "filled": SessionState.FILLED,
        "partial_fill": SessionState.PARTIAL_OR_ANOMALOUS,
        "rejected": SessionState.REJECTED,
        "anomaly": SessionState.PARTIAL_OR_ANOMALOUS,
    },
    SessionState.PARTIAL_OR_ANOMALOUS: {
        "partial_fill": SessionState.PARTIAL_OR_ANOMALOUS,
        "filled": SessionState.FILLED,
        "rejected": SessionState.REJECTED,
        "exit_started": SessionState.EXITING,
        "anomaly": SessionState.PARTIAL_OR_ANOMALOUS,
    },
    SessionState.FILLED: {"exit_started": SessionState.EXITING},
    SessionState.EXITING: {
        "closed": SessionState.CLOSED,
        "exit_retry": SessionState.EXITING,
        "anomaly": SessionState.PARTIAL_OR_ANOMALOUS,
    },
    SessionState.CLOSED: {"autopsy_saved": SessionState.AUTOPSY},
}

TERMINAL = {
    SessionState.AUTOPSY,
    SessionState.NO_SIGNAL,
    SessionState.REJECTED,
    SessionState.INSUFFICIENT_EVIDENCE,
    SessionState.EXPIRED,
    SessionState.HALTED,
}


@dataclass
class StateMachine:
    session_id: UUID
    identity: StrategyIdentity
    repository: Repository
    ledger: AuditLedger
    state: SessionState = SessionState.BOOTSTRAP
    sequence: int = 0

    def transition(
        self,
        event_type: str,
        payload: dict[str, object] | None = None,
        evidence_level: EvidenceLevel = EvidenceLevel.L0_INVARIANT,
    ) -> SessionEvent:
        target: SessionState | None
        if event_type == "halt" and self.state not in TERMINAL:
            target = SessionState.HALTED
        else:
            target = ALLOWED.get(self.state, {}).get(event_type)
        if target is None:
            raise InvalidTransition(f"{self.state} cannot accept {event_type}")
        self.sequence += 1
        event = SessionEvent(
            session_id=self.session_id,
            sequence=self.sequence,
            event_type=event_type,
            state=target,
            payload=payload or {},
            versions=VersionStamp(
                strategy_id=self.identity.strategy_id,
                strategy_version=self.identity.strategy_version,
            ),
            created_at=datetime.now(UTC),
            evidence_level=evidence_level,
        )
        self.ledger.append_and_upsert_session(event)
        self.state = target
        return event
