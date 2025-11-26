from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import SessionDep, get_current_active_user
from app.models.user import User
from app.schemas.notification import (
    NotificationCountResponse,
    NotificationListResponse,
    NotificationRead,
)
from app.services import user_notifications as notifications_service

router = APIRouter()


@router.get("/", response_model=NotificationListResponse)
async def list_notifications(
    session: SessionDep,
    current_user: User = Depends(get_current_active_user),
    limit: int = Query(default=20, ge=1, le=100),
) -> NotificationListResponse:
    notifications, unread_count = await notifications_service.list_notifications(
        session,
        user_id=current_user.id,
        limit=limit,
    )
    return NotificationListResponse(notifications=notifications, unread_count=unread_count)


@router.get("/unread-count", response_model=NotificationCountResponse)
async def unread_notifications_count(
    session: SessionDep,
    current_user: User = Depends(get_current_active_user),
) -> NotificationCountResponse:
    count = await notifications_service.unread_count(session, user_id=current_user.id)
    return NotificationCountResponse(unread_count=count)


@router.post("/{notification_id}/read", response_model=NotificationRead)
async def mark_notification_read(
    notification_id: int,
    session: SessionDep,
    current_user: User = Depends(get_current_active_user),
) -> NotificationRead:
    notification = await notifications_service.mark_notification_read(
        session,
        user_id=current_user.id,
        notification_id=notification_id,
    )
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    return notification


@router.post("/read-all", response_model=NotificationCountResponse)
async def mark_all_notifications_read(
    session: SessionDep,
    current_user: User = Depends(get_current_active_user),
) -> NotificationCountResponse:
    await notifications_service.mark_all_notifications_read(session, user_id=current_user.id)
    count = await notifications_service.unread_count(session, user_id=current_user.id)
    return NotificationCountResponse(unread_count=count)
