"""Verification and operations for the external billing service."""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import jwt
from starlette.datastructures import Headers
from sqlalchemy import func, insert, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import billing_capabilities
from app.core.config import settings
from app.core.errors import CodedError
from app.core.identify import bearer_token
from app.core.messages import BillingMessages
from app.core.security import PublicKeyBundleError, load_verification_keys
from app.models.platform.billing import (
    BillingEventLog,
    BillingJti,
    BillingOp,
    BillingSource,
)
from app.models.platform.guild import Guild, GuildMembership, CommunityStatus
from app.models.platform.guild_administration import GuildAdministration
from app.schemas.platform.billing import (
    BillingCommunityNotice,
    BillingCommunityTierApply,
    BillingCommunityTierRead,
)
from app.core.audit_events import AuditEventType
from app.services import audit as audit_service

logger = logging.getLogger(__name__)

# Pinned on both sides of the boundary — not deployment knobs.
BILLING_AUDIENCE = "initiative:billing"
BILLING_ISSUER = "initiative-billing"
#: Max |now - signed timestamp| accepted, in seconds.
BILLING_REPLAY_WINDOW_SECONDS = 300


class BillingEnvelopeError(CodedError):
    """The request failed envelope verification: 403, or 503 when billing is
    absent (the self-host default) or this deployment's key is unreadable —
    neither a caller fault, so the answer is fail-closed and retryable."""

    status_code = 403


@dataclass(frozen=True)
class BillingClaims:
    """Validated identity of a billing service call."""

    jti: str
    expires_at: datetime


def billing_inbound_enabled() -> bool:
    """True when the inbound billing endpoints are configured to run.

    The single source of truth for "billing writes can happen": both the
    signing key and the HMAC secret must be present. Unset — the self-host
    default — means the endpoints 503 and nothing ever reaches the
    ``billing_*`` tables, so the janitor can skip its sweep entirely.
    """
    return bool(settings.BILLING_PUBLIC_KEY_PEM and settings.BILLING_HMAC_SECRET)


def billing_managed() -> bool:
    """True when a community's plan is set by the billing service.

    A portal to change it in and a signed way for it to write both have to
    exist; with either missing, the operator sets caps and entitlements by
    hand. The database reads the same answer from ``public.billing_managed()``
    (``app.db.billing_managed``).
    """
    return bool(settings.BILLING_URL) and billing_inbound_enabled()


def verify_billing_envelope(
    *,
    method: str,
    path: str,
    headers: Headers,
    body: bytes,
) -> BillingClaims:
    """Verify the envelope on a billing call. Pure — no DB.

    Order: config presence, timestamp recency, HMAC over the raw body, then
    the RS256 JWT. The one-shot ``jti`` redemption is not done here — it is
    a DB write and belongs inside the endpoint's transaction.
    """
    if not billing_inbound_enabled():
        raise BillingEnvelopeError(BillingMessages.NOT_CONFIGURED, 503)

    ts_header = headers.get("X-Billing-Timestamp")
    signature = headers.get("X-Billing-Signature")
    token = bearer_token(headers)
    if not ts_header or not signature or not token:
        raise BillingEnvelopeError(BillingMessages.MISSING_SIGNATURE)

    try:
        ts = int(ts_header)
    except ValueError as exc:
        raise BillingEnvelopeError(BillingMessages.STALE_TIMESTAMP) from exc
    window = BILLING_REPLAY_WINDOW_SECONDS
    if abs(time.time() - ts) > window:
        raise BillingEnvelopeError(BillingMessages.STALE_TIMESTAMP)

    # Signed over the raw bytes, before any parsing.
    message = "\n".join(
        [method.upper(), path, ts_header, hashlib.sha256(body).hexdigest()]
    ).encode()
    offered = signature.lower()
    matched_index = -1
    for index, secret in enumerate(
        (settings.BILLING_HMAC_SECRET, settings.BILLING_HMAC_SECRET_PREVIOUS)
    ):
        if not secret:
            continue
        expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, offered) and matched_index < 0:
            matched_index = index
    if matched_index < 0:
        raise BillingEnvelopeError(BillingMessages.INVALID_SIGNATURE)

    try:
        keys = load_verification_keys(settings.BILLING_PUBLIC_KEY_PEM)
    except PublicKeyBundleError as exc:
        # An unreadable key is this deployment's misconfiguration, not the
        # caller's fault, so it surfaces like "not configured" rather than as
        # a rejected token.
        raise BillingEnvelopeError(BillingMessages.KEY_UNREADABLE, 503) from exc
    if not keys:
        raise BillingEnvelopeError(BillingMessages.NOT_CONFIGURED, 503)

    payload = None
    first_error: jwt.PyJWTError | None = None
    for key in keys:
        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=BILLING_AUDIENCE,
                issuer=BILLING_ISSUER,
                options={"require": ["exp", "iat", "iss", "aud", "jti"]},
            )
            break
        except jwt.PyJWTError as exc:
            if first_error is None:
                first_error = exc
    if payload is None:
        raise BillingEnvelopeError(BillingMessages.INVALID_TOKEN) from first_error

    # Bound to the blocklist column (varchar 64) so an oversized jti is a
    # clean 403 instead of a database error at redemption time.
    jti = str(payload["jti"])
    if not jti or len(jti) > 64:
        raise BillingEnvelopeError(BillingMessages.INVALID_TOKEN)

    if matched_index > 0:
        logger.warning(
            "billing.envelope_verified_with_previous_secret "
            "rotation is still in progress; clear BILLING_HMAC_SECRET_PREVIOUS "
            "once this stops appearing"
        )

    return BillingClaims(
        jti=jti,
        expires_at=datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc),
    )


async def record_jti(session: AsyncSession, *, jti: str, expires_at: datetime) -> None:
    """Redeem a billing service JWT's ``jti`` — first presentation only.

    Flushes (never commits) so the redemption shares the endpoint's
    transaction; a later presentation collides on the PK and is refused as
    ``REPLAYED_TOKEN``.
    """
    session.add(
        BillingJti(
            jti=jti,
            redeemed_at=datetime.now(timezone.utc),
            expires_at=expires_at,
        )
    )
    try:
        await session.flush()
    except IntegrityError as exc:
        # Written now: the refusal rolls the transaction back.
        audit_service.emit(
            event_type=AuditEventType.SECURITY_REPLAY_REJECTED,
            actor_user_id=None,
            detail={"channel": "billing"},
        )
        raise CodedError(BillingMessages.REPLAYED_TOKEN, 403) from exc


# The caps and the plan label live on ``guild_administration``; the lifecycle
# status stays on ``guilds`` (every request reads it). Billing sees exactly
# these columns of each — nothing else on either table.
_GUILD_TIER_COLUMNS = (
    Guild.id,
    GuildAdministration.tier_name,
    GuildAdministration.max_storage_bytes,
    GuildAdministration.max_users,
    GuildAdministration.banner_image_enabled,
    GuildAdministration.support_enabled,
    GuildAdministration.auth_options,
    # Billing's answer to "does this plan charge anybody" — see migration 0325.
    GuildAdministration.plan_is_free,
    Guild.status,
)


#: A guild in one of these takes no status write from billing at all.
_BILLING_UNTOUCHABLE_STATUS_VALUES: frozenset[str] = frozenset(
    {CommunityStatus.suspended.value, CommunityStatus.deleted.value}
)


async def _select_tier_row(session: AsyncSession, guild_id: int):
    """Read the billing-visible slice of one guild. Explicit columns only —
    the role's grants are column-scoped, so an ORM ``SELECT *`` would fail."""
    return (
        await session.exec(
            select(*_GUILD_TIER_COLUMNS)
            .join(GuildAdministration, GuildAdministration.guild_id == Guild.id)
            .where(Guild.id == guild_id)
        )
    ).one_or_none()


async def _member_count(session: AsyncSession, guild_id: int) -> int:
    # count(guild_id), not count(*): guild_id (NOT NULL) is the role's only
    # granted column on this table.
    return (
        await session.exec(
            select(func.count(GuildMembership.guild_id)).where(
                GuildMembership.guild_id == guild_id
            )
        )
    ).one()


async def _claim_event(
    session: AsyncSession,
    *,
    event_id: str,
    guild_id: int,
    op: BillingOp,
    source: BillingSource,
    actor: str | None = None,
) -> bool:
    """Claim one event id in ``billing_event_log``; False if already claimed.

    Plain INSERT in a savepoint rather than ON CONFLICT DO NOTHING: the
    billing role holds no SELECT on this table (append-only), and under RLS
    an ON CONFLICT insert would demand one. The unique-violation IS the
    replay signal; the savepoint confines the abort so the jti burn and the
    transaction survive.
    """
    claim = insert(BillingEventLog.__table__).values(
        event_id=event_id,
        guild_id=guild_id,
        op=op.value,
        source=source.value,
        actor=actor,
        applied_at=datetime.now(timezone.utc),
    )
    try:
        async with session.begin_nested():
            await session.exec(claim)
    except IntegrityError:
        return False
    return True


async def event_claimed(session: AsyncSession, event_id: str) -> bool:
    """Whether ``event_id`` is already in ``billing_event_log``.

    On the system engine: the billing role writes the log and may not read it,
    so the community notice asks here before it writes anything down.
    """
    return (
        await session.exec(
            select(BillingEventLog.event_id).where(BillingEventLog.event_id == event_id)
        )
    ).first() is not None


async def claim_community_notice(
    session: AsyncSession, payload: BillingCommunityNotice, *, guild_id: int
) -> bool:
    """Record one community notice in the event log; False if a concurrent
    delivery recorded it first.

    Claimed after the notice is written down, not before (see
    ``api.v1.platform_endpoints.billing.community_notice``): the billing role
    writes the log row and nothing else, and the notice is the system engine's.
    """
    return await _claim_event(
        session,
        event_id=payload.event_id,
        guild_id=guild_id,
        op=BillingOp.community_notice,
        source=payload.source,
    )


async def apply_guild_tier(
    session: AsyncSession, payload: BillingCommunityTierApply, *, guild_id: int
) -> BillingCommunityTierRead:
    """Apply a tier-metadata write, exactly once per ``event_id``.

    The payload names its guild by the reference billing holds; ``guild_id`` is
    what that resolved to at the edge, and is the only name for the guild used
    from here in.

    Sequence: existence check (404 before consuming the event id), then the
    source/state restriction (a refused write consumes nothing — the whole
    transaction rolls back), then the ``billing_event_log`` claim (a
    unique-violation means a prior delivery already applied this event, so
    the values are left untouched), then the UPDATE with
    ``model_fields_set`` sentinel semantics (omit = leave, null = unlimited).
    """
    provided = payload.model_fields_set
    row = await _select_tier_row(session, guild_id)
    if row is None:
        # Rolls back with the jti unredeemed and the event id unconsumed, so
        # the delivery can be retried once the guild exists.
        raise CodedError(BillingMessages.COMMUNITY_NOT_FOUND, 404)

    # support_manual may only RAISE the storage cap. The payload validator
    # already forbids it every other field; the lower-vs-raise half needs the
    # current value, so it lives here, against the row read in the same
    # transaction. NULL = unlimited, so any finite value under a NULL cap is
    # a lowering too. Equal-to-current is allowed (idempotent re-apply).
    if (
        payload.source is BillingSource.support_manual
        and "max_storage_bytes" in provided
        and payload.max_storage_bytes is not None
        and (
            row.max_storage_bytes is None
            or payload.max_storage_bytes < row.max_storage_bytes
        )
    ):
        raise CodedError(BillingMessages.SUPPORT_CANNOT_LOWER, 422)

    # An operator may lift a member ceiling, never impose one. A plan change
    # sets whatever the plan says — a downgrade legitimately tightens — but a
    # human at the billing end reaching in to type a number may only move the
    # limit out of the way. NULL is unlimited and therefore the highest value
    # there is, so anything finite under a NULL ceiling is a lowering too.
    if (
        payload.source is BillingSource.operator_manual
        and "max_users" in provided
        and payload.max_users is not None
        and (row.max_users is None or payload.max_users < row.max_users)
    ):
        raise CodedError(BillingMessages.OPERATOR_CANNOT_LOWER_CEILING, 422)

    applied = await _claim_event(
        session,
        event_id=payload.event_id,
        guild_id=guild_id,
        op=BillingOp.guild_tier,
        source=payload.source,
        actor=payload.actor,
    )

    if applied:
        now = datetime.now(timezone.utc)
        # Two rows, one transaction: the caps and plan label on
        # ``guild_administration``, the lifecycle status on ``guilds``.
        administration_values: dict = {}
        for field in ("tier_name", "max_storage_bytes", "max_users", "plan_is_free"):
            if field in provided:
                administration_values[field] = getattr(payload, field)
        if "feature_keys" in provided and payload.feature_keys is not None:
            administration_values.update(
                billing_capabilities.administration_values(payload.feature_keys)
            )
        guild_values: dict = {}
        if payload.status is not None:
            # Recorded whatever the guild's status is, so a suspension that
            # lifts returns the guild to what billing last said.
            administration_values["billing_status"] = payload.status.value
        if payload.status is not None and payload.status.value != row.status:
            if row.status in _BILLING_UNTOUCHABLE_STATUS_VALUES:
                # A status write never moves a guild out of ``suspended`` or
                # ``deleted``: the operator's time out and deletion own those.
                # The caps still land, and the status is recorded above.
                logger.info(
                    "billing: guild %s status write %s -> %s held (source=%s event=%s)",
                    guild_id,
                    row.status,
                    payload.status.value,
                    payload.source.value,
                    payload.event_id,
                )
            else:
                guild_values["status"] = payload.status.value
                guild_values["status_changed_at"] = now
                logger.info(
                    "billing: guild %s status %s -> %s (source=%s actor=%s event=%s)",
                    guild_id,
                    row.status,
                    payload.status.value,
                    payload.source.value,
                    payload.actor,
                    payload.event_id,
                )
        if administration_values or guild_values:
            if administration_values:
                await session.exec(
                    update(GuildAdministration)
                    .where(GuildAdministration.guild_id == guild_id)
                    .values(**administration_values)
                )
            # Stamp the guild whichever row moved: "when did this guild last
            # change" stays a fact about the guild.
            guild_values["updated_at"] = now
            await session.exec(
                update(Guild).where(Guild.id == guild_id).values(**guild_values)
            )
            row = await _select_tier_row(session, guild_id)

    return BillingCommunityTierRead(
        community_ref=payload.community_ref,
        tier_name=row.tier_name,
        max_storage_bytes=row.max_storage_bytes,
        max_users=row.max_users,
        status=CommunityStatus(row.status),
        feature_keys=billing_capabilities.package_of(
            banner_image_enabled=row.banner_image_enabled,
            support_enabled=row.support_enabled,
            auth_options=row.auth_options,
        ),
        plan_is_free=row.plan_is_free,
        member_count=await _member_count(session, guild_id),
        applied=applied,
    )


async def guild_display_name(session: AsyncSession, guild_id: int) -> str | None:
    """What one guild calls itself, or None if it is no longer there.

    Read on the billing session rather than the system engine: the name is one
    column of ``public.guilds``, and the billing role is granted it explicitly
    (``20260911_0257``). Selecting columns rather than the model because that
    role's grants are column-scoped — an ORM ``SELECT *`` would be refused.
    """
    return (
        await session.exec(select(Guild.name).where(Guild.id == guild_id))
    ).one_or_none()


async def guild_lifecycle_status(
    session: AsyncSession, guild_id: int
) -> CommunityStatus | None:
    """One guild's lifecycle status, ``deleted`` included, or None once purged.

    On the billing session, like the name: ``status`` is among the columns the
    billing role already reads for the tier write.
    """
    status = (
        await session.exec(select(Guild.status).where(Guild.id == guild_id))
    ).one_or_none()
    return None if status is None else CommunityStatus(status)


@dataclass(frozen=True)
class GuildUsage:
    """What one guild is using, for the signed usage read.

    ``usage_bytes`` is the figure ``enforce_storage_quota`` enforces against;
    ``member_count`` is the one ``ensure_membership`` compares with
    ``max_users``. Billing reads the second so a seat count is never cut below
    the people already in the community.
    """

    usage_bytes: int
    member_count: int


async def guild_usage(guild_id: int) -> GuildUsage:
    """Current stored bytes and member count for one guild, for the signed
    usage read.

    Neither is visible to the column-scoped ``initiative_billing`` role:
    ``uploads`` lives in the per-guild ``guild_<id>`` schema, and
    ``guild_memberships`` is outside its grants. So the guild is looked up — and
    its members counted — on a **system session from the guild's cohort**, not
    the billing-context session; that session bypasses RLS, which is what
    ``count_members`` asks of its caller. The sum is
    ``get_guild_storage_usage``'s. The billing session still owns envelope
    verification + the jti burn in the endpoint; this only reads the figures
    the app itself enforces against. Read-only — the app never pushes usage
    anywhere.
    """
    from app.db import cohorts
    from app.services.platform.guilds import count_members
    from app.services.tenant.attachments import get_guild_storage_usage

    async with cohorts.system_session(guild_id) as session:
        # Existence check at the public baseline.
        exists = (
            await session.exec(select(Guild.id).where(Guild.id == guild_id))
        ).one_or_none()
        if exists is None:
            raise CodedError(BillingMessages.COMMUNITY_NOT_FOUND, 404)
        member_count = await count_members(session, guild_id=guild_id)

    return GuildUsage(
        usage_bytes=await get_guild_storage_usage(guild_id),
        member_count=member_count,
    )
