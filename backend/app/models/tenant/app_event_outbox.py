"""The events installed apps emit, kept until each subscription has them.

An app emits one of the events its pinned definition declares
(``POST /app-platform/installation/events``) and the row lands here, in the
community's own schema. The outbox poller delivers it with the change log
(``event_outbox``): the same ledger, backoff, dead-letter and retention, and
the same envelope, where an app event is one entry in ``changes``.

Unlike the change log, a row carries its payload: it is the emitting app's own
vendor data, bounded in size, and a subscriber hears it only while it holds
``apps:<emitter>``.

Written by the system engine alone and read by the poller.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import BigInteger, Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class AppEventOutbox(SQLModel, table=True):
    __tablename__ = "app_event_outbox"

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )

    #: ``txid_current()`` of the emitting transaction: the unit the poller's
    #: ledger records, shared with ``event_outbox``.
    txn_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))

    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )

    #: The install that emitted it. A weak reference, like the change log's
    #: actor: removing the app leaves the row to retention, and delivery names
    #: an emitter only while its install is there.
    install_id: int = Field(sa_column=Column(Integer, nullable=False))

    #: ``app.<public_id>.<event>``, an ``emit`` endpoint the pinned definition
    #: declares.
    event_type: str = Field(sa_column=Column(String(length=200), nullable=False))

    #: The initiative the event is about, or NULL for one about the community.
    initiative_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True, index=True)
    )

    payload: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
