"""One installed client of one account, and the keys that identify it.

A device is where a ratchet lives. It is deliberately *not* the same row as an
``auth_session`` or a ``device_auth`` token: those track a login, which rotates
and expires, and a key store has to outlive both — a laptop shut for three
months comes back expecting its history. ``device_token_id`` links the two
where a link exists, so Settings › Security stays the one device screen and one
revoke means one thing. It is nullable because the web has no device token, and
minting one to tidy the join would put a long-lived credential in a browser.

``identity_key`` and ``fingerprint_key`` are public keys. The private halves
are generated on the client and stay there.

Read by another account only through the directory leg — see the migration —
and only where ``public.dm_apparent_permission`` already says ``open``.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import ConfigDict
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    Uuid,
    text,
)
from sqlmodel import Field, SQLModel


class DmDevice(SQLModel, table=True):
    __tablename__ = "dm_devices"
    __table_args__ = (Index("ix_dm_devices_user", "user_id"),)
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(
            Uuid, primary_key=True, server_default=text("gen_random_uuid()")
        ),
    )
    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    #: Curve25519. What a sender encrypts to.
    identity_key: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    #: Ed25519. What a safety number is computed over.
    fingerprint_key: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    device_token_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("user_tokens.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    #: Derived at registration from the device token's name or the user agent.
    #: Never typed by hand — a device list nobody has to curate is one people
    #: actually read.
    label: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    #: Moved on every collection, so Settings › Security can surface a device
    #: that has stopped syncing before its queue copy grows without bound.
    last_seen_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
