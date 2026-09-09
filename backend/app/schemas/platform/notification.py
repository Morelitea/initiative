from datetime import datetime
from typing import Any, List

from pydantic import ConfigDict

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
    message names none of them, a membership notice only a community."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    guild_id: int | None = None
    initiative_id: int | None = None
    tool: str | None = None


class UnreadPlacesResponse(SanitizedBaseModel):
    """Where the dots go. No counts anywhere — the popover shows the list."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    places: List[NotificationPlace]


class NotificationCountResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    unread_count: int
