"""Verification and operations for the external billing service."""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

import jwt
from sqlalchemy import func, insert, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import billing_capabilities
from app.core.config import settings
from app.core.messages import BillingMessages
from app.core.security import PublicKeyBundleError, load_verification_keys
from app.models.platform.billing import (
    BillingEventLog,
    BillingJti,
    BillingOp,
    BillingSource,
)
from app.models.platform.guild import Guild, GuildMembership, GuildStatus
from app.models.platform.guild_administration import GuildAdministration
from app.schemas.platform.billing import BillingGuildTierApply, BillingGuildTierRead

logger = logging.getLogger(__name__)


class BillingEnvelopeError(Exception):
    """The request failed envelope verification. ``code`` is the
    BillingMessages constant the endpoint surfaces as a 403 (or 503 for
    ``NOT_CONFIGURED``)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class BillingReplayError(Exception):
    """The service JWT's ``jti`` was already redeemed."""


class BillingGuildNotFoundError(Exception):
    """The envelope's guild does not exist."""


class BillingSourceRestrictionError(Exception):
    """The payload's ``source`` may not perform this write against the
    guild's current state (e.g. support_manual lowering the storage cap).
    ``code`` is the BillingMessages constant the endpoint surfaces as 422."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


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


def verify_billing_envelope(
    *,
    method: str,
    path: str,
    headers: Mapping[str, str],
    body: bytes,
) -> BillingClaims:
    """Verify the envelope on a billing call. Pure — no DB.

    Order: config presence, timestamp recency, HMAC over the raw body, then
    the RS256 JWT. The one-shot ``jti`` redemption is not done here — it is
    a DB write and belongs inside the endpoint's transaction.
    """
    if not billing_inbound_enabled():
        raise BillingEnvelopeError(BillingMessages.NOT_CONFIGURED)

    ts_header = headers.get("X-Billing-Timestamp")
    signature = headers.get("X-Billing-Signature")
    authorization = headers.get("Authorization", "")
    if not ts_header or not signature or not authorization.startswith("Bearer "):
        raise BillingEnvelopeError(BillingMessages.MISSING_SIGNATURE)

    try:
        ts = int(ts_header)
    except ValueError as exc:
        raise BillingEnvelopeError(BillingMessages.STALE_TIMESTAMP) from exc
    window = max(1, settings.BILLING_REPLAY_WINDOW_SECONDS)  # never 0 (P-6)
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
        raise BillingEnvelopeError(BillingMessages.KEY_UNREADABLE) from exc
    if not keys:
        raise BillingEnvelopeError(BillingMessages.NOT_CONFIGURED)

    token = authorization[len("Bearer ") :]
    payload = None
    first_error: jwt.PyJWTError | None = None
    for key in keys:
        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=settings.BILLING_AUDIENCE,
                issuer=settings.BILLING_ISSUER,
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
    transaction; a later presentation collides on the PK and raises
    :class:`BillingReplayError`.
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
        raise BillingReplayError(f"jti {jti} already redeemed") from exc


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


async def apply_guild_tier(
    session: AsyncSession, payload: BillingGuildTierApply, *, guild_id: int
) -> BillingGuildTierRead:
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
        raise BillingGuildNotFoundError(guild_id)

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
        raise BillingSourceRestrictionError(BillingMessages.SUPPORT_CANNOT_LOWER)

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
        raise BillingSourceRestrictionError(
            BillingMessages.OPERATOR_CANNOT_LOWER_CEILING
        )

    # Plain INSERT in a savepoint rather than ON CONFLICT DO NOTHING: the
    # billing role holds no SELECT on this table (append-only), and under RLS
    # an ON CONFLICT insert would demand one. The unique-violation IS the
    # replay signal; the savepoint confines the abort so the jti burn and the
    # transaction survive.
    claim = insert(BillingEventLog.__table__).values(
        event_id=payload.event_id,
        guild_id=guild_id,
        op=BillingOp.guild_tier.value,
        source=payload.source.value,
        actor=payload.actor,
        applied_at=datetime.now(timezone.utc),
    )
    try:
        async with session.begin_nested():
            await session.exec(claim)
        applied = True
    except IntegrityError:
        applied = False

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
        if payload.status is not None and payload.status.value != row.status:
            if GuildStatus.deleted.value in (row.status, payload.status.value):
                # ``deleted`` belongs to the community's admins and the platform
                # operators, never to billing: a status write must not delete a
                # guild, and must not bring one back either. The second is the
                # dangerous one — a lapsed card's ``read_only`` landing on a
                # deleted guild would restore it and restart its purge clock.
                # The caps still land, so a restore comes back on the plan
                # billing last recorded.
                logger.info(
                    "billing: guild %s status write %s -> %s ignored (source=%s event=%s)",
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

    return BillingGuildTierRead(
        guild_ref=payload.guild_ref,
        tier_name=row.tier_name,
        max_storage_bytes=row.max_storage_bytes,
        max_users=row.max_users,
        status=GuildStatus(row.status),
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
) -> GuildStatus | None:
    """One guild's lifecycle status, ``deleted`` included, or None once purged.

    On the billing session, like the name: ``status`` is among the columns the
    billing role already reads for the tier write.
    """
    status = (
        await session.exec(select(Guild.status).where(Guild.id == guild_id))
    ).one_or_none()
    return None if status is None else GuildStatus(status)


async def guild_storage_usage(admin_session: AsyncSession, guild_id: int) -> int:
    """Current stored bytes for one guild, for the signed usage read.

    ``uploads`` lives in the per-guild ``guild_<id>`` schema, which the
    column-scoped ``initiative_billing`` role cannot reach — so this runs on
    the **system engine** routed into the guild (``guild_role='admin'``, the
    trash-purge pattern), not the billing-context session. The billing session
    still owns envelope verification + the jti burn in the endpoint; this only
    reads the same ``SUM(uploads.size_bytes)`` that ``enforce_storage_quota``
    enforces against. Read-only — the app never pushes usage anywhere.
    """
    from app.db.session import set_rls_context
    from app.services.tenant.attachments import get_guild_storage_usage

    # Existence check at the public baseline before routing into the schema.
    exists = (
        await admin_session.exec(select(Guild.id).where(Guild.id == guild_id))
    ).one_or_none()
    if exists is None:
        raise BillingGuildNotFoundError(guild_id)

    await set_rls_context(admin_session, guild_id=guild_id)
    return await get_guild_storage_usage(admin_session)
