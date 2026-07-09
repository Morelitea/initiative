"""Verification and operations for the external billing service.

``apply_guild_tier`` writes the tier label and billing-computed caps onto
``public.guilds``; ``guild_member_count`` reads one guild's headcount. Tier
definitions live in the billing service's own database — no pricing data,
tier matrix, or plan math may ever live in this repository, and the FOSS app
enforces only the numeric caps and status it is handed (``tier_name`` is
display/audit metadata, never an enforcement input).

Requests carry an HMAC over ``METHOD\\nPATH\\nTIMESTAMP\\nsha256(body)``
(bounded recency window) plus an RS256 service JWT whose ``jti`` is redeemed
one-shot in ``billing_jti_blocklist``. Authorization is the database's: the
caller runs as the ``initiative_billing`` role with ``app.billing_guild_id``
set to the envelope's guild. Writes are claimed through ``billing_event_log``
(UNIQUE event id), so retried deliveries apply once.

Nothing here commits — the endpoint owns the transaction.
"""

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

from app.core.config import settings
from app.core.messages import BillingMessages
from app.models.platform.billing import (
    BillingEventLog,
    BillingJti,
    BillingOp,
    BillingSource,
)
from app.models.platform.guild import Guild, GuildMembership, GuildStatus
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
    expected = hmac.new(
        settings.BILLING_HMAC_SECRET.encode(), message, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature.lower()):
        raise BillingEnvelopeError(BillingMessages.INVALID_SIGNATURE)

    try:
        payload = jwt.decode(
            authorization[len("Bearer ") :],
            settings.BILLING_PUBLIC_KEY_PEM,
            algorithms=["RS256"],
            audience=settings.BILLING_AUDIENCE,
            issuer=settings.BILLING_ISSUER,
            options={"require": ["exp", "iat", "iss", "aud", "jti"]},
        )
    except jwt.PyJWTError as exc:
        raise BillingEnvelopeError(BillingMessages.INVALID_TOKEN) from exc

    # Bound to the blocklist column (varchar 64) so an oversized jti is a
    # clean 403 instead of a database error at redemption time.
    jti = str(payload["jti"])
    if not jti or len(jti) > 64:
        raise BillingEnvelopeError(BillingMessages.INVALID_TOKEN)

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


_GUILD_TIER_COLUMNS = (
    Guild.id,
    Guild.tier_name,
    Guild.max_storage_bytes,
    Guild.max_users,
    Guild.status,
)


async def _select_tier_row(session: AsyncSession, guild_id: int):
    """Read the billing-visible slice of one guild. Explicit columns only —
    the role's grants are column-scoped, so an ORM ``SELECT *`` would fail."""
    return (
        await session.execute(select(*_GUILD_TIER_COLUMNS).where(Guild.id == guild_id))
    ).one_or_none()


async def _member_count(session: AsyncSession, guild_id: int) -> int:
    # count(guild_id), not count(*): guild_id (NOT NULL) is the role's only
    # granted column on this table.
    return (
        await session.execute(
            select(func.count(GuildMembership.guild_id)).where(
                GuildMembership.guild_id == guild_id
            )
        )
    ).scalar_one()


async def apply_guild_tier(
    session: AsyncSession, payload: BillingGuildTierApply
) -> BillingGuildTierRead:
    """Apply a tier-metadata write, exactly once per ``event_id``.

    Sequence: existence check (404 before consuming the event id), then the
    source/state restriction (a refused write consumes nothing — the whole
    transaction rolls back), then the ``billing_event_log`` claim (a
    unique-violation means a prior delivery already applied this event, so
    the values are left untouched), then the UPDATE with
    ``model_fields_set`` sentinel semantics (omit = leave, null = unlimited).
    """
    provided = payload.model_fields_set
    row = await _select_tier_row(session, payload.guild_id)
    if row is None:
        raise BillingGuildNotFoundError(payload.guild_id)

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

    # Plain INSERT in a savepoint rather than ON CONFLICT DO NOTHING: the
    # billing role holds no SELECT on this table (append-only), and under RLS
    # an ON CONFLICT insert would demand one. The unique-violation IS the
    # replay signal; the savepoint confines the abort so the jti burn and the
    # transaction survive.
    claim = insert(BillingEventLog.__table__).values(
        event_id=payload.event_id,
        guild_id=payload.guild_id,
        op=BillingOp.guild_tier.value,
        source=payload.source.value,
        actor=payload.actor,
        applied_at=datetime.now(timezone.utc),
    )
    try:
        async with session.begin_nested():
            await session.execute(claim)
        applied = True
    except IntegrityError:
        applied = False

    if applied:
        now = datetime.now(timezone.utc)
        values: dict = {}
        for field in ("tier_name", "max_storage_bytes", "max_users"):
            if field in provided:
                values[field] = getattr(payload, field)
        if payload.status is not None and payload.status.value != row.status:
            values["status"] = payload.status.value
            values["status_changed_at"] = now
            logger.info(
                "billing: guild %s status %s -> %s (source=%s actor=%s event=%s)",
                payload.guild_id,
                row.status,
                payload.status.value,
                payload.source.value,
                payload.actor,
                payload.event_id,
            )
        if values:
            values["updated_at"] = now
            await session.execute(
                update(Guild).where(Guild.id == payload.guild_id).values(**values)
            )
            row = await _select_tier_row(session, payload.guild_id)

    return BillingGuildTierRead(
        guild_id=row.id,
        tier_name=row.tier_name,
        max_storage_bytes=row.max_storage_bytes,
        max_users=row.max_users,
        status=GuildStatus(row.status),
        member_count=await _member_count(session, payload.guild_id),
        applied=applied,
    )


async def guild_member_count(session: AsyncSession, guild_id: int) -> int:
    """Headcount for per-user billing."""
    exists = (
        await session.execute(select(Guild.id).where(Guild.id == guild_id))
    ).one_or_none()
    if exists is None:
        raise BillingGuildNotFoundError(guild_id)
    return await _member_count(session, guild_id)
