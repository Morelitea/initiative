from datetime import datetime
from typing import Any, List

from pydantic import BaseModel

from app.models.notification import NotificationType


class NotificationRead(BaseModel):
    id: int
    type: NotificationType
    data: dict[str, Any]
    created_at: datetime
    read_at: datetime | None = None

    class Config:
        from_attributes = True


class NotificationListResponse(BaseModel):
    notifications: List[NotificationRead]
    unread_count: int


class NotificationCountResponse(BaseModel):
    unread_count: int
