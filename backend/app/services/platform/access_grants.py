"""Privileged Access Management (PAM) service.

Time-bound, per-guild access grants: a lower-privilege platform user requests
temporary access to one guild, an approver (``access.approve`` holder) grants
it, and it auto-expires. See ``app.models.access_grant``.

Grants are written on the system engine alone. They are read on the caller's
platform tier: a grantee's own rows (``access_grants_self``) and, for
``access.approve`` holders, the whole queue (``access_grants_admin``).
Capability and ownership checks happen at the endpoint as well.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from sqlalchemy import or_, text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.capabilities import Capability, roles_with_capability
from app.core.login_methods import LoginMethod
from app.core.config import settings
from app.core.email_i18n import translate
from app.models.platform.access_grant import (
    LEVEL_LABEL_KEYS,
    AccessGrant,
    AccessGrantPurpose,
    AccessGrantStatus,
    AccessLevel,
)
from app.models.platform.guild import Guild, GuildStatus
from app.models.platform.notification import NotificationType
from app.models.platform.user import User, UserRole, UserStatus
from app.models.platform.user_passkey import UserPasskey
from app.models.platform.user_totp import UserTotp
from app.schemas.platform.access_grant import (
    AccessGrantCreate,
    AccessGrantRead,
    BreakGlassCreate,
)
from app.services import email as email_service
from app.services.auth import addresses
from app.services.platform import auth_posture
from app.services.platform import guilds as guilds_service
from app.services.platform import push_notifications
from app.services.platform import user_notifications
from app.core.user_display import display_name

logger = logging.getLogger(__name__)


class AccessGrantError(Exception):
    """Raised for PAM rule violations; carries a machine-readable code that the
    endpoint maps to an HTTP status + ``AccessGrantMessages`` detail."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _lock_user_guild_grants(
    session: AsyncSession, *, user_id: int, guild_id: int
) -> None:
    """Serialize grant changes for one user and guild until transaction end."""
    await session.exec(
        text("SELECT pg_advisory_xact_lock(:uid, :gid)"),
        params={"uid": int(user_id), "gid": int(guild_id)},
    )


# Per-role maximum grant duration (least privilege). Each is clamped to the
# absolute ceiling. The request and break-glass forms read the caller's figure
# from the server (``max_minutes_for_role``, ``break_glass_max_minutes``).
_ROLE_MAX_MINUTES: dict[UserRole, int] = {
    UserRole.support: settings.PAM_SUPPORT_MAX_MINUTES,
    UserRole.moderator: settings.PAM_MODERATOR_MAX_MINUTES,
    UserRole.operator: settings.PAM_ADMIN_MAX_MINUTES,
    # Owners/operators reach a guild via the self-approved break-glass path
    # (``data.bypass``) rather than the request→approve flow; their cap applies
    # to that self-issued grant.
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


def break_glass_max_minutes(role: UserRole) -> int:
    """The longest break-glass window the given role may issue itself: the role
    cap, further clamped to the (shorter) break-glass ceiling because a
    self-approved grant has no second-person check."""
    return min(max_minutes_for_role(role), settings.PAM_BREAK_GLASS_MAX_MINUTES)


def _break_glass_duration(requested: Optional[int], role: UserRole) -> int:
    """Resolve a break-glass window against ``break_glass_max_minutes``.
    Defaults to ``PAM_BREAK_GLASS_DEFAULT_MINUTES``."""
    cap = break_glass_max_minutes(role)
    minutes = (
        requested
        if requested is not None
        else min(settings.PAM_BREAK_GLASS_DEFAULT_MINUTES, cap)
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
    levels: Optional[Sequence[str]] = None,
    requester: Optional[str] = None,
) -> None:
    """Best-effort push + email fan-out for a PAM event.

    Always attempted (these are operational/security notices with no per-user
    opt-out); silently no-ops when FCM / SMTP aren't configured, and never lets
    a delivery failure break the request. ``push_key`` selects the
    ``accessGrant.<key>`` entry in the ``notifications`` namespace, localized to
    the recipient.

    ``levels`` and ``requester`` populate the ``{{level}}`` / ``{{requester}}``
    placeholders that only some body templates contain — ``requester`` is used by
    the ``requested`` event only and is intentionally ``None`` for approve/deny/
    revoke. Each is passed to the interpolator only when present, so it maps to
    exactly the placeholders its template declares.

    ``levels`` is a sequence because one ask can be for two things at once. It
    is what the recipient is being asked to decide about, so every one of them
    is named: a message that described only the first would be asking for a
    decision about something it had not mentioned.
    """
    locale = getattr(recipient, "locale", None) or "en"
    body_vars: dict[str, str] = {"guild": guild_name or "a guild"}
    if levels:
        body_vars["level"] = ", ".join(
            translate(LEVEL_LABEL_KEYS[level], locale, namespace="notifications")
            for level in levels
            if level in LEVEL_LABEL_KEYS
        )
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
            locale=locale,
        )
    except Exception as exc:  # best effort
        logger.error("PAM push notification failed: %s", exc, exc_info=True)
    try:
        from app.core.notification_categories import category_of
        from app.services.platform import email_outbox

        await email_outbox.enqueue(
            session,
            recipient,
            category=category_of(notification_type),
            pieces=email_service.access_grant_pieces(
                recipient,
                event=email_event,
                guild_name=guild_name or "a guild",
                levels=levels,
                requester=requester,
            ),
        )
    except Exception as exc:  # best effort
        logger.error("PAM email notification failed: %s", exc, exc_info=True)


async def request_grants(
    session: AsyncSession,
    *,
    requester: User,
    payload: AccessGrantCreate,
    asks: list[tuple[str, str]],
) -> list[AccessGrant]:
    """Create the pending grants ``payload`` asks for, as one act.

    Validate every purpose first, create one row per purpose, and notify each
    approver once after the complete request is established.
    """
    await _lock_user_guild_grants(
        session, user_id=requester.id, guild_id=payload.guild_id
    )
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

    # Validate the complete request before creating any row.
    for purpose, _level in asks:
        existing = await session.exec(
            select(AccessGrant).where(
                AccessGrant.user_id == requester.id,
                AccessGrant.guild_id == payload.guild_id,
                AccessGrant.purpose == purpose,
                AccessGrant.status.in_(
                    [AccessGrantStatus.pending.value, AccessGrantStatus.approved.value]
                ),
            )
        )
        for grant in existing.all():
            if grant.status == AccessGrantStatus.pending.value or grant.is_live(
                now=_now()
            ):
                raise AccessGrantError("OVERLAPPING_GRANT")

    created: list[AccessGrant] = []
    for purpose, level in asks:
        grant = AccessGrant(
            user_id=requester.id,
            guild_id=payload.guild_id,
            access_level=level,
            purpose=purpose,
            status=AccessGrantStatus.pending.value,
            reason=payload.reason,
            requested_duration_minutes=duration,
            requested_by_id=requester.id,
        )
        session.add(grant)
        created.append(grant)
    await session.flush()

    requester_name = display_name(requester)
    for approver in await _approvers(session):
        for grant in created:
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
            levels=[grant.access_level for grant in created],
            requester=requester_name,
        )
    return created


async def demands_second_factor(session: AsyncSession) -> bool:
    """Whether breaking glass has to carry the account's own second factor.

    Derived rather than configured, from two things that must both hold: the
    deployment offers the authenticator app, and some active ``data.bypass``
    holder has confirmed one.

    The pair is what keeps the rule answerable. A holder who has neither is
    refused until they set one up, and the way back is their own Security page
    — so the rule may only ask while that page can actually give them one. A
    deployment that has withdrawn a method refuses new enrolments of it, which
    is why both have to be gone before it stops asking, rather than it asking
    for something it will not let anybody obtain.

    Either method answers, so either keeps the rule alive: an authenticator
    code or an assertion from one of the account's passkeys.
    """
    offered = [
        method
        for method in (LoginMethod.totp, LoginMethod.passkey)
        if await auth_posture.login_method_allowed(session, method)
    ]
    if not offered:
        return False

    # Only a factor held in a method still offered keeps the rule alive: one
    # the deployment has withdrawn is not a way back for the holder who has
    # nothing.
    held = []
    if LoginMethod.totp in offered:
        held.append(
            select(UserTotp.user_id)
            .where(UserTotp.user_id == User.id, UserTotp.confirmed_at.is_not(None))
            .exists()
        )
    if LoginMethod.passkey in offered:
        held.append(
            select(UserPasskey.user_id).where(UserPasskey.user_id == User.id).exists()
        )

    roles = list(roles_with_capability(Capability.DATA_BYPASS))
    found = (
        await session.exec(
            select(User.id)
            .where(
                User.role.in_(roles),
                User.status == UserStatus.active,
                or_(*held),
            )
            .limit(1)
        )
    ).first()
    return found is not None


async def break_glass(
    session: AsyncSession,
    *,
    actor: User,
    payload: BreakGlassCreate,
    allow_member: bool = False,
    purpose: AccessGrantPurpose = AccessGrantPurpose.content,
    level: str,
) -> AccessGrant:
    """Self-issue a time-bound break-glass grant for ``actor`` to one guild.

    The capability-gated endpoint lets an operator self-approve a scoped,
    expiring PAM grant in one step. The result is an ``access_grants`` row with
    requester and approver both set to ``actor`` and the supplied reason kept
    for the audit trail. The window is capped server-side.

    ``purpose`` scopes what the grant authorises and ``level`` says how far it
    reaches within that purpose — the two vocabularies are different, which is
    why the caller states the level rather than a request body carrying one.
    ``allow_member`` goes with a non-content purpose, which membership does not
    already confer.

    """
    guild = await guilds_service.get_guild(session, guild_id=payload.guild_id)
    if guild is None:
        raise AccessGrantError("GUILD_NOT_FOUND")

    # A member already has standing access — nothing to break glass for.
    membership = await guilds_service.get_membership(
        session, guild_id=payload.guild_id, user_id=actor.id
    )
    if membership is not None and not allow_member:
        raise AccessGrantError("ALREADY_MEMBER")

    # Serialize concurrent self-issues for this (actor, guild) so the
    # read-then-insert anti-stacking check below can't be raced into two live
    # grants. A transaction-scoped advisory lock on the (user_id, guild_id) pair
    # makes a second concurrent request wait, then see the first's grant and hit
    # ALREADY_LIVE. The two-int key space is distinct from any single-bigint
    # advisory lock used elsewhere; the lock auto-releases on commit/rollback.
    await _lock_user_guild_grants(session, user_id=actor.id, guild_id=payload.guild_id)

    # Don't stack grants: a still-live grant already confers the access, and a
    # pending request would conflict. Re-trigger only after the current one ends.
    existing = await session.exec(
        select(AccessGrant).where(
            AccessGrant.user_id == actor.id,
            AccessGrant.guild_id == payload.guild_id,
            AccessGrant.purpose == purpose.value,
            AccessGrant.status.in_(
                [AccessGrantStatus.pending.value, AccessGrantStatus.approved.value]
            ),
        )
    )
    now = _now()
    for grant in existing.all():
        if grant.status == AccessGrantStatus.pending.value:
            raise AccessGrantError("OVERLAPPING_GRANT")
        if grant.is_live(now=now):
            raise AccessGrantError("ALREADY_LIVE")

    duration = _break_glass_duration(payload.requested_duration_minutes, actor.role)
    grant = AccessGrant(
        user_id=actor.id,
        guild_id=payload.guild_id,
        access_level=level,
        purpose=purpose.value,
        # Created AND approved in one step — self-approved, so there's no wait.
        status=AccessGrantStatus.approved.value,
        reason=payload.reason,
        requested_duration_minutes=duration,
        requested_by_id=actor.id,
        approved_by_id=actor.id,
        decided_at=now,
        expires_at=now + timedelta(minutes=duration),
    )
    session.add(grant)
    await session.flush()

    # Record the event for the actor (audit/visibility); the row itself is the
    # authoritative audit trail.
    data = await _event_notification_data(session, grant)
    await user_notifications.create_notification(
        session,
        user_id=actor.id,
        notification_type=NotificationType.access_grant_approved,
        data=data,
    )
    await _push_and_email(
        session,
        recipient=actor,
        notification_type=NotificationType.access_grant_approved,
        push_key="approved",
        email_event="approved",
        guild_name=data["guild_name"],
        levels=[grant.access_level],
    )
    return grant


async def reconcile_break_glass_pair(
    session: AsyncSession,
    *,
    actor: User,
    payload: BreakGlassCreate,
) -> list[AccessGrant]:
    """Close open grants replaced by the fixed break-glass pair."""
    await _lock_user_guild_grants(session, user_id=actor.id, guild_id=payload.guild_id)
    result = await session.exec(
        select(AccessGrant).where(
            AccessGrant.user_id == actor.id,
            AccessGrant.guild_id == payload.guild_id,
            AccessGrant.purpose.in_(
                [AccessGrantPurpose.content.value, AccessGrantPurpose.settings.value]
            ),
            AccessGrant.status.in_(
                [AccessGrantStatus.pending.value, AccessGrantStatus.approved.value]
            ),
        )
    )
    now = _now()
    replaced: list[AccessGrant] = []
    for grant in result.all():
        if grant.status == AccessGrantStatus.pending.value:
            grant.status = AccessGrantStatus.denied.value
            grant.approved_by_id = actor.id
            grant.decided_at = now
            grant.updated_at = now
            session.add(grant)
            replaced.append(grant)
            continue
        if not grant.is_live(now=now):
            continue
        grant.status = AccessGrantStatus.revoked.value
        grant.revoked_by_id = actor.id
        grant.revoked_at = now
        grant.updated_at = now
        session.add(grant)
        replaced.append(grant)
    await session.flush()
    return replaced


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
            levels=[grant.access_level],
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
    purpose: AccessGrantPurpose = AccessGrantPurpose.content,
) -> Optional[AccessGrant]:
    """Return the user's currently-live grant for ``guild_id``, if any.

    Used when resolving guild session context so a grantee can act in a guild
    they aren't a member of, for the grant's window only. Scoped to ``purpose``
    so a grant issued for one authority is never spent as another — the default
    keeps the content path seeing only content grants.
    """
    now = _now()
    result = await session.exec(
        select(AccessGrant).where(
            AccessGrant.user_id == user_id,
            AccessGrant.guild_id == guild_id,
            AccessGrant.purpose == purpose.value,
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


async def _enrichment(
    session: AsyncSession, *, user_ids: set[int], guild_ids: set[int]
) -> tuple[dict[int | None, User], dict[int, str], dict[int, Guild]]:
    """The people and communities a page of grants names, for display."""
    users_result = await session.exec(select(User).where(User.id.in_(user_ids)))
    users = {u.id: u for u in users_result.all()}
    # An account's address lives in ``user_emails``; one query for the page.
    addresses_by_user = await addresses.primary_addresses(
        session, user_ids=sorted(user_ids)
    )
    guilds = {}
    for gid in guild_ids:
        guild = await guilds_service.get_guild(session, guild_id=gid)
        if guild is not None:
            guilds[gid] = guild
    return users, addresses_by_user, guilds


async def to_read(
    grants: list[AccessGrant], *, system_session: Optional[AsyncSession] = None
) -> list[AccessGrantRead]:
    """Serialize grants, batch-loading display enrichment (user/guild names).

    The enrichment is read on the system engine: the grantee's address lives
    in ``user_emails``, and the community a grant names is one its holder is
    not a member of. A route already on the system engine passes its session;
    a route on the caller's platform tier passes none and a short system
    session is opened for the lookup.
    """
    if not grants:
        return []

    user_ids: set[int] = set()
    guild_ids: set[int] = set()
    for g in grants:
        user_ids.add(g.user_id)
        guild_ids.add(g.guild_id)
        if g.approved_by_id is not None:
            user_ids.add(g.approved_by_id)

    if system_session is not None:
        users, addresses_by_user, guilds = await _enrichment(
            system_session, user_ids=user_ids, guild_ids=guild_ids
        )
    else:
        from app.db.session import AdminSessionLocal

        async with AdminSessionLocal() as own_session:
            users, addresses_by_user, guilds = await _enrichment(
                own_session, user_ids=user_ids, guild_ids=guild_ids
            )

    out: list[AccessGrantRead] = []
    for g in grants:
        read = AccessGrantRead.model_validate(g)
        grantee = users.get(g.user_id)
        if grantee is not None:
            read.user_email = addresses_by_user.get(g.user_id)
            read.user_full_name = grantee.full_name
        guild = guilds.get(g.guild_id)
        if guild is not None:
            read.guild_name = guild.name
            read.guild_status = GuildStatus(guild.status)
        if g.approved_by_id is not None:
            approver = users.get(g.approved_by_id)
            if approver is not None:
                read.approved_by_email = addresses_by_user.get(g.approved_by_id)
        out.append(read)
    return out


# Convenience aliases for cap values used by callers / docs.
DEFAULT_DURATION_MINUTES = settings.PAM_DEFAULT_DURATION_MINUTES
MAX_DURATION_MINUTES = settings.PAM_MAX_DURATION_MINUTES
__all__ = [
    "AccessGrantError",
    "request_grants",
    "break_glass",
    "get_grant",
    "approve",
    "deny",
    "revoke",
    "cancel_own_pending",
    "get_live_grant",
    "list_grants",
    "expire_due",
    "to_read",
    "max_minutes_for_role",
    "break_glass_max_minutes",
    "AccessLevel",
]
