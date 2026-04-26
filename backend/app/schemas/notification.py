from datetime import datetime
from typing import Any, List

from pydantic import BaseModel, ConfigDict

from app.models.notification import NotificationType


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    type: NotificationType
    data: dict[str, Any]
    created_at: datetime
    read_at: datetime | None = None


class NotificationListResponse(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    notifications: List[NotificationRead]
    unread_count: int


class NotificationCountResponse(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    unread_count: int
