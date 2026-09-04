from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from afterimage.storage import Database, Repository


def test_intraday_high_water_is_persisted_and_never_moves_down(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'risk-state.db'}")
    database.create()
    repository = Repository(database)
    account_hash = "a" * 64
    session_date = date(2026, 9, 4)

    assert repository.observe_account_equity(
        account_hash, session_date, Decimal(100000)
    ) == Decimal(100000)
    assert repository.observe_account_equity(
        account_hash, session_date, Decimal(101250)
    ) == Decimal(101250)
    assert repository.observe_account_equity(account_hash, session_date, Decimal(99800)) == Decimal(
        101250
    )
    assert (tmp_path / "risk-state.db").stat().st_mode & 0o777 == 0o600
