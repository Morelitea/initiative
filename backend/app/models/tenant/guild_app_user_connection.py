"""One member's own connection to an installed app's vendor.

Some vendors authorize an *organization* and some authorize a *person*. The
first kind is a credential a guild admin types once and the whole guild uses,
which lives on the ``guild_apps`` row. This table is the second kind: an OAuth
grant, or anything else where the vendor's answer to "who is this?" is a human
being. Whatever such a credential can reach is what *that person* can reach, so
each member connects their own account and the app holds one credential per
person rather than one for everybody.

Two consequences shape the columns:

* **Installing an app never waits on this.** An app whose only connections are
  per-member is fully installed with no rows here at all; members connect when
  and if they want the features that need it.
* **The app never learns who the member is.** It addresses a connection by
  ``connection_ref`` — an opaque random handle minted per (install, connection,
  member) — so it can select the right credential without holding a user id, an
  email, or a display name, and the same person looks unrelated across apps.

A personal connection is still guild-governed access rather than private
property, so the row is readable and removable by its owner **or** by a guild
admin (the ``own_row_*`` policies in ``app.db.tenancy.OWN_ROW_TABLES``). What an
admin gets is management — see who connected as which vendor account, disconnect
them, stop them reconnecting. Never the values: ``config_secrets`` serializes to
nobody, because ending access is the useful power and reading a live credential
is not part of it.

``blocked_at`` leaves the row behind as a tombstone once the values are gone, so
"this person may not reach that system through us" survives without uninstalling
the app for everyone.
"""

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import ConfigDict
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

#: Where a connection has got to, as far as this side can tell.
#:
#: ``pending`` — the member started the vendor flow and the app has not written
#: a result back yet. ``connected`` — values are present. ``blocked`` — an admin
#: stopped this member reconnecting, and the row is a tombstone.
CONNECTION_STATUSES: frozenset[str] = frozenset({"pending", "connected", "blocked"})


class GuildAppUserConnection(SQLModel, table=True):
    __tablename__ = "guild_app_user_connections"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    __table_args__ = (
        # One row per member per connection of an install. Reconnecting reuses
        # it, so a member's history is one row rather than a pile of them.
        UniqueConstraint(
            "app_id",
            "connection_id",
            "user_id",
            name="guild_app_user_connections_unique_member",
        ),
        # The handle the app addresses. Unique so it resolves to exactly one
        # credential.
        UniqueConstraint(
            "connection_ref", name="guild_app_user_connections_unique_ref"
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False, index=True)

    app_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guild_apps.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    #: Which of the pinned definition's connections this is, by manifest id.
    connection_id: str = Field(sa_column=Column(String(64), nullable=False))

    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    #: Random, not derived: the same person is uncorrelated across apps.
    connection_ref: str = Field(sa_column=Column(String(32), nullable=False))

    #: Non-secret values, keyed by field key.
    config: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    #: One Fernet ciphertext per secret field, under the same custody as the
    #: guild-scoped values.
    config_secrets: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )

    status: str = Field(
        default="pending",
        sa_column=Column(String(16), nullable=False, server_default="pending"),
    )
    #: What the app says the member connected as, e.g. ``@alice``. Display only,
    #: reported by the app, never a credential.
    account_label: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    blocked_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    blocked_by_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
