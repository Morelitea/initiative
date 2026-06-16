"""Privileged Access Management (PAM) service.

Time-bound, per-guild access grants: a lower-privilege platform user requests
temporary access to one guild, an approver (``access.approve`` holder) grants
it, and it auto-expires. See ``app.models.access_grant``.

All functions take the admin (RLS-bypassing) session — access_grants is a
platform-scoped table managed cross-guild, like ``users``. Capability and
ownership checks happen at the endpoint/service layer instead of via RLS.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.capabilities import Capability, roles_with_capability
from app.core.config import settings
from app.core.email_i18n import translate
from app.models.access_grant import AccessGrant, AccessGrantStatus, AccessLevel
from app.models.notification import NotificationType
from app.models.user import User, UserRole, UserStatus
from app.schemas.access_grant import AccessGrantCreate, AccessGrantRead
from app.services import email as email_service
from app.services import guilds as guilds_service
from app.services import push_notifications
from app.services import user_notifications

logger = logging.getLogger(__name__)


class AccessGrantError(Exception):
    """Raised for PAM rule violations; carries a machine-readable code that the
    endpoint maps to an HTTP status + ``AccessGrantMessages`` detail."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Per-role maximum grant duration (least privilege). Each is clamped to the
# absolute ceiling. Keep in sync with the frontend mirror in
# SettingsAccessGrantsPage.
_ROLE_MAX_MINUTES: dict[UserRole, int] = {
    UserRole.support: settings.PAM_SUPPORT_MAX_MINUTES,
    UserRole.moderator: settings.PAM_MODERATOR_MAX_MINUTES,
    UserRole.admin: settings.PAM_ADMIN_MAX_MINUTES,
    # Owners hold the standing all-guild bypass and don't self-request, but
    # define a cap for completeness / defensive use.
    UserRole.owner: settings.PAM_ADMIN_MAX_MINUTES,
}


def max_minutes_for_role(role: UserRole) -> int:
    """The longest grant the given role may hold (clamped to the ceiling)."""
    role_cap = _ROLE_MAX_MINUTES.get(role, settings.PAM_DEFAULT_DURATION_MINUTES)
    return min(role_cap, settings.PAM_MAX_DURATION_MINUTES)


def _capped_duration(requested: Optional[int], role: UserRole) -> int:
    """Resolve a requested duration for a grantee of ``role`` to the effective
    one, or raise if it exceeds that role's maximum."""
    cap = max_minutes_for_role(role)
    minutes = (
        requested
        if requested is not None
        else min(settings.PAM_DEFAULT_DURATION_MINUTES, cap)
    )
    if minutes > cap:
        raise AccessGrantError("DURATION_TOO_LONG")
    return minutes


async def _event_notification_data(session: AsyncSession, grant: AccessGrant) -> dict:
    """Common notification payload for grant lifecycle events — enough for the
    frontend to render an informative message and link to the Access page."""
    guild = await guilds_service.get_guild(session, guild_id=grant.guild_id)
    return {
        "grant_id": str(grant.id),
        "guild_id": str(grant.guild_id),
        "guild_name": guild.name if guild else None,
        "access_level": grant.access_level,
    }


async def _approvers(session: AsyncSession) -> list[User]:
    """Active users who can approve access requests (for notification fan-out)."""
    roles = list(roles_with_capability(Capability.ACCESS_APPROVE))
    if not roles:
        return []
    result = await session.exec(
        select(User).where(User.role.in_(roles), User.status == UserStatus.active)
    )
    return list(result.all())


async def _push_and_email(
    session: AsyncSession,
    *,
    recipient: User,
    notification_type: NotificationType,
    push_key: str,
    email_event: str,
    guild_name: Optional[str],
    access_level: Optional[str] = None,
    requester: Optional[str] = None,
) -> None:
    """Best-effort push + email fan-out for a PAM event.

    Always attempted (these are operational/security notices with no per-user
    opt-out); silently no-ops when FCM / SMTP aren't configured, and never lets
    a delivery failure break the request. ``push_key`` selects the
    ``accessGrant.<key>`` entry in the ``notifications`` namespace, localized to
    the recipient.

    ``access_level`` and ``requester`` populate the ``{{level}}`` / ``{{requester}}``
    placeholders that only some body templates contain — ``requester`` is used by
    the ``requested`` event only and is intentionally ``None`` for approve/deny/
    revoke. Each is passed to the interpolator only when present, so it maps to
    exactly the placeholders its template declares.
    """
    locale = getattr(recipient, "locale", None) or "en"
    body_vars: dict[str, str] = {"guild": guild_name or "a guild"}
    if access_level is not None:
        level_key = (
            "accessGrant.levelReadWrite"
            if access_level == "read_write"
            else "accessGrant.levelRead"
        )
        body_vars["level"] = translate(level_key, locale, namespace="notifications")
    if requester is not None:
        body_vars["requester"] = requester
    try:
        await push_notifications.send_push_to_user(
            session=session,
            user_id=recipient.id,
            notification_type=notification_type,
            title=translate(
                f"accessGrant.{push_key}.title", locale, namespace="notifications"
            ),
            body=translate(
                f"accessGrant.{push_key}.body",
                locale,
                namespace="notifications",
                **body_vars,
            ),
            data={
                "type": notification_type.value,
                "target_path": "/settings/admin/access",
            },
        )
    except Exception as exc:  # best effort
        logger.error("PAM push notification failed: %s", exc, exc_info=True)
    try:
        await email_service.send_access_grant_email(
            session,
            recipient,
            event=email_event,
            guild_name=guild_name or "a guild",
            access_level=access_level,
            requester=requester,
        )
    except email_service.EmailNotConfiguredError:
        pass
    except Exception as exc:  # best effort
        logger.error("PAM email notification failed: %s", exc, exc_info=True)


async def request_grant(
    session: AsyncSession, *, requester: User, payload: AccessGrantCreate
) -> AccessGrant:
    """Create a pending access request for ``requester`` to ``payload.guild_id``."""
    guild = await guilds_service.get_guild(session, guild_id=payload.guild_id)
    if guild is None:
        raise AccessGrantError("GUILD_NOT_FOUND")

    # Members don't need a grant — they already have standing access.
    membership = await guilds_service.get_membership(
        session, guild_id=payload.guild_id, user_id=requester.id
    )
    if membership is not None:
        raise AccessGrantError("ALREADY_MEMBER")

    duration = _capped_duration(payload.requested_duration_minutes, requester.role)

    # Reject a second open request for the same guild while one is still
    # pending or live.
    existing = await session.exec(
        select(AccessGrant).where(
            AccessGrant.user_id == requester.id,
            AccessGrant.guild_id == payload.guild_id,
            AccessGrant.status.in_(
                [AccessGrantStatus.pending.value, AccessGrantStatus.approved.value]
            ),
        )
    )
    for grant in existing.all():
        if grant.status == AccessGrantStatus.pending.value or grant.is_live(now=_now()):
            raise AccessGrantError("OVERLAPPING_GRANT")

    grant = AccessGrant(
        user_id=requester.id,
        guild_id=payload.guild_id,
        access_level=payload.access_level.value,
        status=AccessGrantStatus.pending.value,
        reason=payload.reason,
        requested_duration_minutes=duration,
        requested_by_id=requester.id,
    )
    session.add(grant)
    await session.flush()

    requester_name = requester.full_name or requester.email
    for approver in await _approvers(session):
        await user_notifications.create_notification(
            session,
            user_id=approver.id,
            notification_type=NotificationType.access_grant_requested,
            data={
                "grant_id": str(grant.id),
                "guild_id": str(grant.guild_id),
                "guild_name": guild.name,
                "requester_id": str(requester.id),
                "requester_name": requester_name,
                "access_level": grant.access_level,
            },
        )
        await _push_and_email(
            session,
            recipient=approver,
            notification_type=NotificationType.access_grant_requested,
            push_key="requested",
            email_event="requested",
            guild_name=guild.name,
            access_level=grant.access_level,
            requester=requester_name,
        )
    return grant


async def get_grant(session: AsyncSession, grant_id: int) -> Optional[AccessGrant]:
    return await session.get(AccessGrant, grant_id)


async def approve(
    session: AsyncSession,
    *,
    grant: AccessGrant,
    approver: User,
    duration_minutes: Optional[int] = None,
) -> AccessGrant:
    if grant.status != AccessGrantStatus.pending.value:
        raise AccessGrantError("NOT_PENDING")
    if approver.id == grant.requested_by_id or approver.id == grant.user_id:
        raise AccessGrantError("CANNOT_APPROVE_OWN")

    # Cap by the GRANTEE's role (an approver shortening/extending can't exceed
    # the recipient's tier).
    grantee = await session.get(User, grant.user_id)
    grantee_role = grantee.role if grantee else UserRole.support
    duration = _capped_duration(
        duration_minutes or grant.requested_duration_minutes, grantee_role
    )
    now = _now()
    grant.status = AccessGrantStatus.approved.value
    grant.approved_by_id = approver.id
    grant.decided_at = now
    grant.expires_at = now + timedelta(minutes=duration)
    grant.updated_at = now
    session.add(grant)
    await session.flush()

    data = await _event_notification_data(session, grant)
    await user_notifications.create_notification(
        session,
        user_id=grant.user_id,
        notification_type=NotificationType.access_grant_approved,
        data=data,
    )
    if grantee is not None:
        await _push_and_email(
            session,
            recipient=grantee,
            notification_type=NotificationType.access_grant_approved,
            push_key="approved",
            email_event="approved",
            guild_name=data["guild_name"],
            access_level=grant.access_level,
        )
    return grant


async def deny(
    session: AsyncSession, *, grant: AccessGrant, approver: User
) -> AccessGrant:
    if grant.status != AccessGrantStatus.pending.value:
        raise AccessGrantError("NOT_PENDING")
    now = _now()
    grant.status = AccessGrantStatus.denied.value
    grant.approved_by_id = approver.id
    grant.decided_at = now
    grant.updated_at = now
    session.add(grant)
    await session.flush()

    grantee = await session.get(User, grant.user_id)
    data = await _event_notification_data(session, grant)
    await user_notifications.create_notification(
        session,
        user_id=grant.user_id,
        notification_type=NotificationType.access_grant_denied,
        data=data,
    )
    if grantee is not None:
        await _push_and_email(
            session,
            recipient=grantee,
            notification_type=NotificationType.access_grant_denied,
            push_key="denied",
            email_event="denied",
            guild_name=data["guild_name"],
        )
    return grant


async def revoke(
    session: AsyncSession, *, grant: AccessGrant, revoker: User
) -> AccessGrant:
    # Revoke is only meaningful for an approved grant (live or not-yet-expired);
    # a pending one should be denied, a terminal one is already over.
    if grant.status != AccessGrantStatus.approved.value:
        raise AccessGrantError("NOT_ACTIVE")
    now = _now()
    grant.status = AccessGrantStatus.revoked.value
    grant.revoked_by_id = revoker.id
    grant.revoked_at = now
    grant.updated_at = now
    session.add(grant)
    await session.flush()

    grantee = await session.get(User, grant.user_id)
    data = await _event_notification_data(session, grant)
    await user_notifications.create_notification(
        session,
        user_id=grant.user_id,
        notification_type=NotificationType.access_grant_revoked,
        data=data,
    )
    if grantee is not None:
        await _push_and_email(
            session,
            recipient=grantee,
            notification_type=NotificationType.access_grant_revoked,
            push_key="revoked",
            email_event="revoked",
            guild_name=data["guild_name"],
        )
    return grant


async def cancel_own_pending(
    session: AsyncSession, *, grant: AccessGrant, user: User
) -> None:
    """A requester withdraws their own still-pending request."""
    if grant.requested_by_id != user.id:
        raise AccessGrantError("CANNOT_CANCEL_OTHERS")
    if grant.status != AccessGrantStatus.pending.value:
        raise AccessGrantError("NOT_PENDING")
    await session.delete(grant)
    await session.flush()


async def get_live_grant(
    session: AsyncSession,
    *,
    user_id: int,
    guild_id: int,
) -> Optional[AccessGrant]:
    """Return the user's currently-live grant for ``guild_id``, if any.

    Used when resolving guild session context so a grantee can act in a guild
    they aren't a member of, for the grant's window only.
    """
    now = _now()
    result = await session.exec(
        select(AccessGrant).where(
            AccessGrant.user_id == user_id,
            AccessGrant.guild_id == guild_id,
            AccessGrant.status == AccessGrantStatus.approved.value,
            AccessGrant.expires_at > now,
        )
    )
    # At most one open grant per (user, guild) is allowed at request time;
    # pick the latest-expiring just in case.
    grants = sorted(result.all(), key=lambda g: g.expires_at or now, reverse=True)
    return grants[0] if grants else None


async def list_grants(
    session: AsyncSession,
    *,
    user_id: Optional[int] = None,
    statuses: Optional[list[str]] = None,
    live_only: bool = False,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> list[AccessGrant]:
    """List grants, optionally filtered to one grantee and/or a set of statuses.

    Approvers pass ``user_id=None`` for the full queue; requesters pass their
    own id for "my requests". ``live_only`` keeps only grants that haven't yet
    expired (pair with ``statuses=["approved"]`` for the currently-usable set).
    ``limit``/``offset`` page the result (ordered newest-first) so a list that
    grows with users/usage stays bounded.
    """
    stmt = select(AccessGrant)
    if user_id is not None:
        stmt = stmt.where(AccessGrant.user_id == user_id)
    if statuses:
        stmt = stmt.where(AccessGrant.status.in_(statuses))
    if live_only:
        stmt = stmt.where(AccessGrant.expires_at > _now())
    stmt = stmt.order_by(AccessGrant.requested_at.desc())
    if offset:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await session.exec(stmt)
    return list(result.all())


async def expire_due(session: AsyncSession) -> int:
    """Flip approved-but-past-expiry grants to ``expired`` for clean audit/UX.

    Liveness is computed independently, so this is housekeeping, not a
    correctness requirement. Returns the number of rows updated.
    """
    now = _now()
    result = await session.exec(
        select(AccessGrant).where(
            AccessGrant.status == AccessGrantStatus.approved.value,
            AccessGrant.expires_at <= now,
        )
    )
    rows = result.all()
    for grant in rows:
        grant.status = AccessGrantStatus.expired.value
        grant.updated_at = now
        session.add(grant)
    if rows:
        await session.flush()
    return len(rows)


async def to_read(
    session: AsyncSession, grants: list[AccessGrant]
) -> list[AccessGrantRead]:
    """Serialize grants, batch-loading display enrichment (user/guild names)."""
    if not grants:
        return []

    user_ids: set[int] = set()
    guild_ids: set[int] = set()
    for g in grants:
        user_ids.add(g.user_id)
        guild_ids.add(g.guild_id)
        if g.approved_by_id is not None:
            user_ids.add(g.approved_by_id)

    users_result = await session.exec(select(User).where(User.id.in_(user_ids)))
    users = {u.id: u for u in users_result.all()}
    guilds = {}
    for gid in guild_ids:
        guild = await guilds_service.get_guild(session, guild_id=gid)
        if guild is not None:
            guilds[gid] = guild

    out: list[AccessGrantRead] = []
    for g in grants:
        read = AccessGrantRead.model_validate(g)
        grantee = users.get(g.user_id)
        if grantee is not None:
            read.user_email = grantee.email
            read.user_full_name = grantee.full_name
        guild = guilds.get(g.guild_id)
        if guild is not None:
            read.guild_name = guild.name
        if g.approved_by_id is not None:
            approver = users.get(g.approved_by_id)
            if approver is not None:
                read.approved_by_email = approver.email
        out.append(read)
    return out


# Convenience aliases for cap values used by callers / docs.
DEFAULT_DURATION_MINUTES = settings.PAM_DEFAULT_DURATION_MINUTES
MAX_DURATION_MINUTES = settings.PAM_MAX_DURATION_MINUTES
__all__ = [
    "AccessGrantError",
    "request_grant",
    "get_grant",
    "approve",
    "deny",
    "revoke",
    "cancel_own_pending",
    "get_live_grant",
    "list_grants",
    "expire_due",
    "to_read",
    "AccessLevel",
]
