from datetime import datetime
from typing import Any, List

from pydantic import ConfigDict, Field

from app.schemas.base import SanitizedBaseModel

from app.models.platform.notification import NotificationType


class NotificationRead(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    type: NotificationType
    data: dict[str, Any]
    created_at: datetime
    read_at: datetime | None = None
    #: Where it happened, each level independently optional. The row shows the
    #: community; the navigation lights from the same three values.
    guild_id: int | None = None
    initiative_id: int | None = None
    tool: str | None = None


class NotificationListResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    notifications: List[NotificationRead]
    unread_count: int
    #: The next page, or null at the end of the list.
    next_cursor: str | None = None


class NotificationPlace(SanitizedBaseModel):
    """One place with unread activity. Every level is optional: a direct
    message names none of them, a membership notice only a community, a
    comment on a task all of them down to the task."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    guild_id: int | None = None
    initiative_id: int | None = None
    tool: str | None = None
    #: The tool's row: the project, calendar or wiki the item is in.
    resource_id: int | None = None
    #: The item itself: ``task``, ``calendar_event``, ``wiki_page``, or a
    #: tool's own kind, and its id.
    subject_type: str | None = None
    subject_id: int | None = None


class UnreadPlacesResponse(SanitizedBaseModel):
    """Where the dots go. No counts anywhere — the popover shows the list."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    places: List[NotificationPlace]


class SubjectReadRequest(SanitizedBaseModel):
    """The item its reader just opened."""

    guild_id: int
    subject_type: str = Field(max_length=32)
    subject_id: int


class SubjectReadResponse(SanitizedBaseModel):
    """What was unread on the item, for its page to show for this visit."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: The comments the read lines named.
    comment_ids: List[int]
    #: Where a rolled-up comment line began: every comment after it by somebody
    #: else was unread. Null when no such line was.
    since: datetime | None = None


class NotificationCountResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    unread_count: int
