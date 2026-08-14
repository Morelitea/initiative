"""An app installed into a guild.

Guild-level by definition: an app belongs to the guild rather than to any
initiative, which is the whole reason it exists — some content is guild-wide by
nature (a club's own events calendar), and a tool that lives in one initiative
cannot be that.

The row is *installation state*, not content. It records which listing was
installed, at which version, what the install produced (``artifacts``), and how
the guild configured it (``config`` / ``config_secrets``). The content itself is
an ordinary row in an ordinary table — a guild-level ``calendars`` row, for
instance — governed by its own grants like anything else. That split is
deliberate: apps mount existing tools at guild scope rather than introducing a
parallel one.

One install can produce more than one thing, so ``artifacts`` is a list of
``{"type": …, "id": …}`` rather than a single id on ``config``. Removal walks
that list through a per-type handler, which is what lets a later app mount two
tools at once without the removal path growing a special case.

``config_secrets`` holds the values a guild admin typed into an app's connection
form, encrypted per key. This row is the custodian: the values are written
through the API and never read back out of it — a read reports only whether a
value is present.

Managing apps is a guild-admin action; the row is readable by any member of the
guild, because the sidebar has to know an app is there. What a member may do
*inside* an app is decided by that instance's grants, not here.
"""

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import ConfigDict
from sqlalchemy import Boolean, Column, DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class GuildApp(SQLModel, table=True):
    __tablename__ = "guild_apps"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    __table_args__ = (
        # One install per listing. Enforced here rather than by the endpoint's
        # look-before-insert alone: two installs arriving together would both
        # find nothing and both create a calendar.
        UniqueConstraint("guild_id", "listing_uid", name="guild_apps_unique_listing"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False, index=True)

    # Provenance, exactly as an installed dashboard records it: the uid is the
    # identity that means the same listing on every deployment.
    listing_uid: str = Field(sa_column=Column(String(14), nullable=False, index=True))
    listing_version: str = Field(sa_column=Column(String(32), nullable=False))
    # Which kind of app this is, copied from the installed definition so the
    # sidebar can render it without re-reading the catalog.
    app_kind: str = Field(sa_column=Column(String(32), nullable=False))

    # Display name, seeded from the listing and renameable per guild.
    name: str = Field(sa_column=Column(String(255), nullable=False))
    # Turned off without uninstalling: the app disappears from the sidebar and
    # its content stays exactly where it is.
    enabled: bool = Field(
        default=True, sa_column=Column(Boolean, nullable=False, server_default="true")
    )

    # The pinned snapshot of what was installed, so the app keeps working at the
    # version this guild chose even if the listing changes or goes away.
    definition: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    # Non-secret connection values, keyed by connection id then field key:
    # ``{"admin_read": {"shop_domain": "example.myshopify.com"}}``.
    config: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    # The same shape, holding one Fernet ciphertext per secret field. Written
    # through the config endpoint, read only by the code that hands values to
    # the app — never serialized back to a client.
    config_secrets: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    # What the app reported back about the configuration it was given:
    # ``unverified`` until it says otherwise, then ``ok`` or ``invalid``.
    # Presence of values is what this build can know by itself; whether a
    # credential carries the permissions it needs is the app's to report.
    config_state: str = Field(
        default="unverified",
        sa_column=Column(String(16), nullable=False, server_default="unverified"),
    )
    #: The app's own short code for an ``invalid`` state, shown beside it.
    config_state_detail: Optional[str] = Field(
        default=None, sa_column=Column(String(120), nullable=True)
    )

    # What this install created: ``[{"type": "calendar", "id": 7}, …]``.
    artifacts: list[Any] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default="[]"),
    )

    # Which initiatives an app's initiative-scoped surfaces appear in.
    #
    # ``{}`` means every one of them, which is the default and the reading an
    # install that never says otherwise keeps. ``{"initiatives": [12, 15]}``
    # narrows it. One column rather than a mode plus a list, so "all" has
    # exactly one representation and cannot fall out of step with a stale set of
    # ids; an initiative that is deleted simply stops matching.
    #
    # This is placement, not permission. It is the guild admin's own answer to
    # "where does this belong", so it applies to them as much as to anyone —
    # unlike a surface's ``visibility``, which names an audience floor an admin
    # always clears.
    placement: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )

    installed_by_id: int = Field(foreign_key="users.id", nullable=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
