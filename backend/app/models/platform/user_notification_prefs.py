"""What one account wants to be told about, and how.

One row per account, holding a sparse settings document. Deliberately not
columns on ``public.users``: that table is read whole by the platform tiers, and
what somebody has chosen to hear about is their own business — the same
reasoning that keeps ``user_dm_settings`` off it.

Sparse means a key exists only where a default has been overridden, so an
account that has never opened the settings page stores ``{}`` and still gets
every default from ``app.core.notification_categories``. A community joined
tomorrow needs no write.

Shape::

    {
      "categories": {"comments": {"in_app": false, "email": false}},
      "quiet_hours": {"start": "22:00", "end": "07:00"},
      "guilds": {
        "7": {"level": "personal", "categories": {"reactions": {"push": false}}}
      }
    }

A document rather than a row per setting: fifteen categories times three
channels is a fixed grid the registry already enumerates, and resolving one
value is then a dict lookup on a row the fan-out has already loaded rather than
a query per recipient.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import ConfigDict
from sqlalchemy import Column, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class NotificationLevel(str, Enum):
    """How much one community is allowed to say.

    The dial almost everyone will use, in place of the per-category grid. It
    lives in the settings document rather than on ``guild_memberships`` because
    a roster row is read by other people, and this is not theirs to see.
    """

    #: Everything the account's category settings allow. The default, and the
    #: value a community joined tomorrow has without anything being written.
    everything = "everything"
    #: Only categories marked ``personal`` — the things another person
    #: addressed to this account.
    personal = "personal"
    #: Nothing at all, including a direct mention. Silence means silence; the
    #: control says so where it is chosen.
    nothing = "nothing"


class UserNotificationPrefs(SQLModel, table=True):
    __tablename__ = "user_notification_prefs"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    prefs: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
