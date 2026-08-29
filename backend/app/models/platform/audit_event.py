"""What was done, by whom, to what — kept after everyone involved is gone."""

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlmodel import Field, SQLModel


class AuditEvent(SQLModel, table=True):
    """One recorded action.

    Append-only: the table grants no UPDATE or DELETE to anyone, the system
    engine included. A record of what happened that could be rewritten
    afterwards would not be one.

    **Every reference here is a plain integer with no foreign key.** An audit
    row is a point-in-time fact, and it has to outlive the account and the
    guild it names — a cascade or a null-out on erasure would erase the record
    of the erasure. Identity is resolved at read time, by id, and only for
    rows that still have someone to resolve.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        # The board's query is "recent first, optionally filtered", and the
        # shipper's is "everything above this id".
        Index("ix_audit_events_occurred_at", "occurred_at"),
        Index("ix_audit_events_actor", "actor_user_id", "occurred_at"),
        Index("ix_audit_events_target_user", "target_user_id", "occurred_at"),
    )

    id: Optional[int] = Field(
        default=None, sa_column=Column(BigInteger, primary_key=True)
    )
    #: Stable id for the envelope, so a downstream consumer can dedupe across
    #: replays without depending on our sequence.
    event_uuid: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(PGUUID(as_uuid=True), nullable=False, unique=True),
    )
    event_type: str = Field(sa_column=Column(String(64), nullable=False))
    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    #: Who did it. No FK — see the class docstring.
    actor_user_id: int = Field(sa_column=Column(Integer, nullable=False))
    #: Who it was done to, when the subject is an account. No FK.
    target_user_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    #: The guild it happened in, for events that have one. No FK.
    guild_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    target_type: Optional[str] = Field(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    target_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    #: Denormalized from the registry so a shipper can select by tier without
    #: reading application code.
    tier: int = Field(sa_column=Column(SmallInteger, nullable=False))
    #: The versioned envelope, verbatim — the same object written to the
    #: ingestible log line. Ids only; identity is never in here.
    envelope: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
