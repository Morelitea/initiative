"""An app installed into a guild.

Guild-level by definition: an app belongs to the guild rather than to any
initiative, which is the whole reason it exists — some content is guild-wide by
nature (a club's own events calendar), and a tool that lives in one initiative
cannot be that.

The row is *installation state*, not content. It records which listing was
installed, at which version, and whatever the app needs to find its own content
(``config``). The content itself is an ordinary row in an ordinary table — a
guild-level ``calendars`` row, for instance — governed by its own grants like
anything else. That split is deliberate: apps mount existing tools at guild
scope rather than introducing a parallel one.

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
    # What the install produced or the guild configured — for a tool instance,
    # the id of the row it created.
    config: dict[str, Any] = Field(
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
