from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


class Database:
    def __init__(self, url: str = "sqlite:///./.afterimage/afterimage.db") -> None:
        self.url = url
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine: Engine = create_engine(url, connect_args=connect_args, future=True)
        if url.startswith("sqlite"):
            event.listen(self.engine, "connect", self._configure_sqlite)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    @staticmethod
    def _configure_sqlite(connection: object, _record: object) -> None:
        cursor = connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=FULL")
        cursor.close()

    def create(self) -> None:
        if self.url.startswith("sqlite:///./"):
            Path(self.url.removeprefix("sqlite:///./")).parent.mkdir(parents=True, exist_ok=True)
        Base.metadata.create_all(self.engine)
        self._secure_sqlite_files()

    def _secure_sqlite_files(self) -> None:
        if not self.url.startswith("sqlite:///"):
            return
        raw_path = self.url.removeprefix("sqlite:///")
        path = Path(raw_path)
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
            if candidate.exists() and not candidate.is_symlink():
                candidate.chmod(0o600)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._sessions()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
            self._secure_sqlite_files()
