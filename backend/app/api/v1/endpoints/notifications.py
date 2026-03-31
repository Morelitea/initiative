from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from sqlmodel import select

from app.api.deps import SessionDep, get_current_active_user, get_service_or_guild_membership, GuildContext
from app.models.guild import GuildMembership
from app.models.notification import NotificationType
from app.models.user import User
from app.schemas.notification import (
    NotificationCountResponse,
    NotificationListResponse,
    NotificationRead,
    NotificationSendRequest,
)
from app.core.messages import NotificationMessages
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
        raise HTTPException(status_code=404, detail=NotificationMessages.NOT_FOUND)
    return notification


@router.post("/read-all", response_model=NotificationCountResponse)
async def mark_all_notifications_read(
    session: SessionDep,
    current_user: User = Depends(get_current_active_user),
) -> NotificationCountResponse:
    await notifications_service.mark_all_notifications_read(session, user_id=current_user.id)
    count = await notifications_service.unread_count(session, user_id=current_user.id)
    return NotificationCountResponse(unread_count=count)


@router.post("/send", response_model=list[NotificationRead])
async def send_notifications(
    body: NotificationSendRequest,
    session: SessionDep,
    guild_context: Annotated[GuildContext, Depends(get_service_or_guild_membership)],
) -> list[NotificationRead]:
    """Send notifications to specified users. Used by the automation engine.

    Accepts a service token or normal admin auth via get_service_or_guild_membership.
    Only users who are members of the scoped guild can receive notifications.
    """
    # Validate all user_ids belong to this guild
    stmt = select(GuildMembership.user_id).where(
        GuildMembership.guild_id == guild_context.guild_id,
        GuildMembership.user_id.in_(body.user_ids),
    )
    result = await session.exec(stmt)
    valid_user_ids = set(result.all())
    invalid_ids = set(body.user_ids) - valid_user_ids
    if invalid_ids:
        raise HTTPException(
            status_code=422,
            detail=f"Users not in guild: {sorted(invalid_ids)}",
        )

    results = []
    for user_id in body.user_ids:
        notification = await notifications_service.create_notification(
            session,
            user_id=user_id,
            notification_type=NotificationType.automation,
            data={"message": body.message, **body.data},
        )
        results.append(NotificationRead.model_validate(notification))
    await session.commit()
    return results
