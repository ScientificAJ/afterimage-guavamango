from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from afterimage.contracts.models import StrategyIdentity
from afterimage.orchestration.state_machine import StateMachine
from afterimage.storage import AuditLedger, Database, Repository


def test_event_and_session_state_are_committed_atomically(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'atomic.db'}")
    database.create()
    session_id = uuid4()
    repository = Repository(database)
    ledger = AuditLedger(database)
    machine = StateMachine(
        session_id,
        StrategyIdentity(strategy_id="opening_range_failure_v1", strategy_version="1.0.0"),
        repository,
        ledger,
    )
    with database.session() as session:
        session.execute(
            text(
                "CREATE TRIGGER reject_session_insert BEFORE INSERT ON sessions "
                "BEGIN SELECT RAISE(ABORT, 'injected session failure'); END"
            )
        )

    with pytest.raises(Exception, match="injected session failure"):
        machine.transition("precheck_passed")

    assert ledger.events(str(session_id)) == ()
    assert repository.get_session(str(session_id)) is None
