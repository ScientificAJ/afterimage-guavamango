from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SessionRow(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    strategy_id: Mapped[str] = mapped_column(String(80), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditRow(Base):
    __tablename__ = "audit_records"
    __table_args__ = (UniqueConstraint("session_id", "sequence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    record_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ArtifactRow(Base):
    __tablename__ = "artifacts"
    __table_args__ = (UniqueConstraint("kind", "artifact_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    artifact_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConsumedNonceRow(Base):
    __tablename__ = "consumed_warrant_nonces"

    nonce: Mapped[str] = mapped_column(String(128), primary_key=True)
    warrant_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BrokerOrderRow(Base):
    __tablename__ = "broker_orders"

    broker_order_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    client_order_id: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    intent_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
