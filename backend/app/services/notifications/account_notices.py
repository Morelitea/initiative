"""Notices about a person's own account, written with the change that
caused them."""

from __future__ import annotations


from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user import User
from app.models.platform.notification import NotificationType
from app.services.platform import user_notifications


async def queue_avatar_removed(session: AsyncSession, *, user: User) -> None:
    """Tell a user their profile picture was taken down.

    In-app only. There is no preference to consult and no email or push: this
    is not something a user opts out of being told, and it is not urgent enough
    to interrupt them on a device.

    Queues rather than sends: the caller commits, so the removal and the notice
    of it land together or not at all. A picture that vanished with no
    explanation is a support ticket.
    """
    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.avatar_removed,
        data={"target_path": "/profile"},
    )


async def queue_username_changed(
    session: AsyncSession, *, user: User, previous_handle: str
) -> None:
    """Tell a user a moderator changed their username.

    Carries the handle they had, because the one they have is already on
    screen and the one they lost is what they will look for.

    In-app only, and queued rather than sent, for the same reasons as
    :func:`queue_avatar_removed`: not something to opt out of, not urgent
    enough to interrupt, and it lands with the change or not at all.
    """
    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.username_changed,
        data={
            "previous_handle": previous_handle,
            "target_path": "/profile/account",
        },
    )


async def queue_account_suspended(
    session: AsyncSession, *, user: User, reason: str | None = None
) -> None:
    """Tell a user their account was suspended, and why if a reason was given.

    They can still sign in, which is the only reason telling them works: a
    suspension nobody could read would present as the app quietly breaking.
    """
    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.account_suspended,
        data={"reason": reason, "target_path": "/profile/account"},
    )


async def queue_account_unsuspended(session: AsyncSession, *, user: User) -> None:
    """Tell a user their account is theirs again."""
    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.account_unsuspended,
        data={"target_path": "/"},
    )
