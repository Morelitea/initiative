"""One member's authorization for an installed app to act as them.

Installing an app is the guild's decision; acting as a particular person is
that person's. This table is the second answer. A guild admin puts the app in
the guild and says what it may reach there; each member then says, separately,
whether it may make requests carrying their own name — and to what depth.

The two are genuinely different questions, so neither implies the other. An app
is fully installed with no rows here at all, and a member who authorizes it
keeps that authorization only as long as the install stands: the row hangs off
``guild_apps``, so removing the app removes every member's grant with it rather
than leaving consent for something that is no longer there.

``can_read`` and ``can_write`` are separate because the member is asked for them
separately. ``can_read`` is what makes the app able to act as the member at all;
``can_write`` additionally lets it change things. Withdrawing either leaves the
row behind holding ``revoked_at``, so "this person authorized it and then
stopped" stays legible — a delete would read the same as never having been
asked.

Like a per-member connection, a grant is guild-governed rather than private
property: the row is readable and revocable by its owner **or** by a guild admin
(the ``own_row_*`` policies in ``app.db.tenancy.OWN_ROW_TABLES``).
"""

from datetime import datetime, timezone
from typing import Optional

from pydantic import ConfigDict
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlmodel import Field, SQLModel


class GuildAppUserDelegation(SQLModel, table=True):
    __tablename__ = "guild_app_user_delegations"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    __table_args__ = (
        # One row per member per install. Re-authorizing after a withdrawal
        # reuses it, so a member's history with one app is one row.
        UniqueConstraint(
            "app_id",
            "user_id",
            name="guild_app_user_delegations_unique_member",
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
    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )

    #: Whether the app may act as this member at all.
    can_read: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    #: Whether it may additionally change things as them.
    can_write: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )

    #: When the current authorization started — reset when a withdrawn grant is
    #: given again, so it reads as the age of what is in force now.
    granted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    revoked_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: Who withdrew it — the member themselves, or the guild admin who did it
    #: for them.
    revoked_by_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
    )

    #: How the member was authenticated when they gave it. Recorded so a grant
    #: says what it was confirmed by rather than only that it exists.
    confirmed_factor: Optional[str] = Field(
        default=None, sa_column=Column(String(32), nullable=True)
    )

    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
