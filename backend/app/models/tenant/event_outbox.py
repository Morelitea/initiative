"""Append-only change log, written by the capture trigger.

One row per changed content row, stamped by the generic capture trigger the
provisioning pipeline installs on every evented guild-content table. The row
carries **identifiers and changed column names only** — never a value. A
consumer learns *that* something changed and reads the current state back
through the REST API, where the six gates apply to the read.

``initiative_id`` is NOT NULL and resolved by the trigger from the same
``INITIATIVE_PATHS`` declaration that renders the table's RLS policies, so an
event is scoped exactly like the row it describes. The outbox itself carries
initiative-member RLS (``direct()``), which is what lets the poller read it *as
the subscriber* and get back only the events that subscriber may see.

Delivery state is not held here: this is a log, and each subscription tracks its
own position in it (``webhook_subscriptions.cursor_event_id``). One row can
therefore serve any number of subscribers, and retention is a plain age sweep.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Field, SQLModel

#: The three actions the trigger emits. A soft delete is reported as ``deleted``
#: and a restore as ``created``, so a consumer never has to know our
#: ``deleted_at`` convention to notice that a row came or went.
ACTION_CREATED = "created"
ACTION_UPDATED = "updated"
ACTION_DELETED = "deleted"
ACTIONS = (ACTION_CREATED, ACTION_UPDATED, ACTION_DELETED)


class EventOutbox(SQLModel, table=True):
    __tablename__ = "event_outbox"

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )

    # ``txid_current()`` of the writing transaction. Every row a single
    # transaction produced shares one value, which is what lets the poller
    # deliver a transaction as one batched envelope instead of N envelopes.
    txn_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))

    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )

    # Both of these are WEAK references — plain ints, no FK.
    #
    # The trigger fires while a row is being deleted, including when that
    # deletion is the cascade from removing the initiative or user the event
    # names. A foreign key would make the log's own insert fail that delete, so
    # purging an initiative would error instead of purging. Weak refs let the
    # log outlive what it describes; retention sweeps the orphans, and RLS still
    # resolves initiative_id through initiative_access (an initiative that no
    # longer exists resolves to guild-admin-only).
    #
    # actor_user_id is NULL for a system-attributed write (background jobs).
    actor_user_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
    )

    # NULL for a guild-wide event (a tag, say) — a row that belongs to no
    # initiative. The access function reads that as "the initiative gate has
    # nothing to decide" and admits any guild member, which is the right
    # disclosure for a row every member can already read. The trigger only
    # writes NULL where a registry says to; an initiative-scoped row whose
    # lookup fails is skipped instead.
    initiative_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, index=True),
    )

    # The table the change happened to, and its primary key.
    resource_type: str = Field(sa_column=Column(String(length=63), nullable=False))
    resource_id: int = Field(sa_column=Column(Integer, nullable=False))

    action: str = Field(sa_column=Column(String(length=16), nullable=False))

    # Changed column NAMES. Empty on create and delete, where the whole row
    # came or went and naming every column would say nothing.
    changed: list[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(String(length=63)), nullable=False, server_default="{}"),
    )
