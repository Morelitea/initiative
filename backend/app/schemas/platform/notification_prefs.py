"""What the settings page reads and writes.

The registry travels with the response, so the page renders whatever categories
this build has rather than carrying its own copy of the list. Adding a category
is then one entry in ``app.core.notification_categories`` and four locale files.
"""

from typing import Optional

from pydantic import ConfigDict, Field, field_validator

from app.core.notification_categories import (
    CategoryGroup,
    Channel,
    NotificationCategory,
)
from app.models.platform.user_notification_prefs import NotificationLevel
from app.schemas.base import SanitizedBaseModel


def _valid_clock(value: str) -> str:
    hour, _, minute = value.partition(":")
    if not (hour.isdigit() and minute.isdigit()):
        raise ValueError("expected HH:MM")
    if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
        raise ValueError("expected HH:MM")
    return f"{int(hour):02d}:{int(minute):02d}"


class QuietHours(SanitizedBaseModel):
    """A nightly window, in the account's own timezone. Wraps midnight."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def _clock(cls, value: str) -> str:
        return _valid_clock(value)


class NotificationCategoryRead(SanitizedBaseModel):
    """One row of the settings grid, described by the backend."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    category: NotificationCategory
    group: CategoryGroup
    #: Addressed to this account by another person — what the "only what names
    #: me" community level keeps, and what the inbox's Mentions filter shows.
    personal: bool
    #: Whether a community level or per-community override can reach it.
    guild_scoped: bool
    #: Channels the account may switch off. A channel absent from this renders
    #: as on and disabled.
    mutable_channels: list[Channel]
    defaults: dict[Channel, bool]


class GuildNotificationSettings(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    guild_id: int
    guild_name: str
    level: NotificationLevel = NotificationLevel.everything
    #: Per-category overrides for this community only. Sparse.
    categories: dict[str, dict[str, bool]] = Field(default_factory=dict)


class NotificationPreferencesRead(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: The registry, so the page has no list of its own.
    categories: list[NotificationCategoryRead]
    #: Account-wide overrides. Sparse — absent means the registry default.
    settings: dict[str, dict[str, bool]] = Field(default_factory=dict)
    quiet_hours: Optional[QuietHours] = None
    guilds: list[GuildNotificationSettings] = Field(default_factory=list)


class NotificationChannelSet(SanitizedBaseModel):
    """One switch being moved. ``guild_id`` scopes it to one community."""

    guild_id: Optional[int] = None
    category: NotificationCategory
    channel: Channel
    enabled: bool


class NotificationLevelSet(SanitizedBaseModel):
    guild_id: int
    level: NotificationLevel


class NotificationPreferencesUpdate(SanitizedBaseModel):
    """A partial write: only what moved.

    Whole-document writes would make two open settings tabs clobber each other,
    and a single switch is what the page actually sends.
    """

    channels: list[NotificationChannelSet] = Field(default_factory=list)
    levels: list[NotificationLevelSet] = Field(default_factory=list)
    quiet_hours: Optional[QuietHours] = None
    #: Explicit, because ``quiet_hours: null`` is indistinguishable from
    #: "not mentioned" in a partial write.
    clear_quiet_hours: bool = False
