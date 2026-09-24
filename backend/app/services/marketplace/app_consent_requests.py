"""Recording an installed app's request to act as a member, and telling them.

The app's own request is routed and stood up by the install seam, which also
resolves the member it names in the install's own sector. What it then writes —
the request row in the community's schema, and the member's notification in
``public`` — is written here on the system engine: the app's role holds nothing
on either table, and neither write decides what anybody may reach. The row is a
question for the member, and only the member's answer makes it count.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlmodel import select

from app.db import session as db_session
from app.db.session import set_rls_context
from app.models.platform.guild import GuildMembership
from app.models.platform.notification import NotificationType
from app.models.platform.user import User, UserStatus
from app.models.tenant.app_member_consent import ConsentAccess, ConsentStatus
from app.models.tenant.guild_app import GuildApp
from app.services.platform import user_notifications
from app.services.tenant import app_member_consents

__all__ = [
    "ConsentRequestLimited",
    "RecordedRequest",
    "consent_target_path",
    "record_request",
]


class ConsentRequestLimited(Exception):
    """The request would be a new one, and the install may make no more of
    this member for now."""


@dataclass(frozen=True)
class RecordedRequest:
    """The request as it stands, and whether this call made it."""

    purpose: Optional[str]
    label: str
    initiative_id: Optional[int]
    requested_access: ConsentAccess
    granted_access: Optional[ConsentAccess]
    status: ConsentStatus
    requested_at: datetime
    created: bool


def consent_target_path(install_id: int) -> str:
    """Where the member answers, inside the community: its front page with the
    app's settings open."""
    return f"/?app={int(install_id)}"


async def record_request(
    *,
    guild_id: int,
    install_id: int,
    user_id: int,
    purpose: Optional[str],
    label: str,
    initiative_id: Optional[int],
    access: ConsentAccess,
    may_create: bool = True,
) -> Optional[RecordedRequest]:
    """Record the request, or find the one already made, and notify the member
    the first time.

    Returns ``None`` when the member no longer belongs to the community or
    their account is not active: there is nobody to ask. With ``may_create``
    false only a request already made is returned, and a new one raises
    :class:`ConsentRequestLimited`.
    """
    async with db_session.SystemSessionLocal() as session:
        belongs = (
            await session.exec(
                select(GuildMembership.user_id)
                .join(User, User.id == GuildMembership.user_id)  # type: ignore[arg-type]
                .where(
                    GuildMembership.guild_id == guild_id,
                    GuildMembership.user_id == user_id,
                    User.status == UserStatus.active,
                )
            )
        ).first()
        await session.rollback()
        if belongs is None:
            return None

        await set_rls_context(session, guild_id=guild_id)
        if may_create:
            row, created = await app_member_consents.request_consent(
                session,
                app_member_consents.ConsentRequest(
                    install_id=install_id,
                    user_id=user_id,
                    purpose=purpose,
                    label=label,
                    initiative_id=initiative_id,
                    access=access,
                ),
            )
        else:
            existing = await app_member_consents.find_consent(
                session, install_id=install_id, user_id=user_id, purpose=purpose
            )
            if existing is None:
                raise ConsentRequestLimited()
            row, created = existing, False
        app_name = (
            await session.exec(select(GuildApp.name).where(GuildApp.id == install_id))
        ).first()
        recorded = RecordedRequest(
            purpose=row.purpose,
            label=row.label,
            initiative_id=row.initiative_id,
            requested_access=ConsentAccess(row.requested_access),
            granted_access=(
                ConsentAccess(row.granted_access) if row.granted_access else None
            ),
            status=row.status,
            requested_at=row.requested_at,
            created=created,
        )
        consent_id = row.id
        await session.commit()

        if created:
            # Out of the community's schema: the notification is the member's
            # own row in ``public``.
            await set_rls_context(session)
            await user_notifications.create_notification(
                session,
                user_id=user_id,
                notification_type=NotificationType.app_consent_requested,
                data={
                    "guild_id": guild_id,
                    "app_id": install_id,
                    "app_name": app_name or "",
                    "consent_id": consent_id,
                    "label": recorded.label,
                    "access": recorded.requested_access.value,
                    "target_path": consent_target_path(install_id),
                },
            )
            await session.commit()
    return recorded
