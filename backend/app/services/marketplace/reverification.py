"""Re-running the handshake with registered app services, on a schedule.

A registration records what one handshake found. Apps move: a container is
redeployed at a new address, a manifest gains a connection, a secret is rotated
on one side only. Left alone, the row keeps saying "ok" until somebody clicks
something and gets a failure, and the operator hears about it from a member.

So the sweep re-verifies, and what it changes is only the *record*: ``status``
and ``last_verified_at``. Nothing here disables an app or edits what an operator
configured — a network blip must not switch off a working integration, and the
manifest hash is deliberately left as it was, because accepting a changed
manifest is an operator decision (an app that widened what it declares gets
looked at, not adopted silently).

Bounded by construction, per §8.6: one registration at a time, each on its own
short request budget, skipping the ones that cannot be verified anyway (no
secret, switched off). It is background work, never a startup blocker, and it
does not run at all on a deployment with no app platform configured.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.encryption import SALT_APP_SERVICE_SECRET, decrypt_field
from app.core.security import app_platform_signing_enabled
from app.db import session as db_session
from app.models.platform.app_service_registration import (
    AppServiceRegistration,
    AppServiceStatus,
)
from app.services.marketplace import registration_lookup
from app.services.marketplace.handshake import HandshakeError, perform_handshake

logger = logging.getLogger(__name__)

__all__ = [
    "SweepResult",
    "process_app_service_reverification",
    "reverification_configured",
    "reverification_interval_seconds",
    "sweep_registrations",
]


@dataclass(frozen=True)
class SweepResult:
    """What one pass found."""

    checked: int = 0
    ok: int = 0
    failed: int = 0
    skipped: int = 0


def reverification_interval_seconds() -> int:
    return settings.APP_SERVICE_VERIFY_INTERVAL_SECONDS


def reverification_configured() -> bool:
    """Whether this deployment runs the sweep at all.

    Two conditions, and both are about the deployment rather than the data: an
    interval, and the app platform's signing key. Without the key the platform
    is inert — no app is registered, nothing is minted — so a worker for it
    would wake up forever to find nothing.
    """
    return reverification_interval_seconds() > 0 and app_platform_signing_enabled()


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _reverify_one(
    session: AsyncSession,
    row: AppServiceRegistration,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """Re-handshake one registration and record the outcome. Returns the status."""
    secret = decrypt_field(row.secret_encrypted, SALT_APP_SERVICE_SECRET)
    try:
        result = await perform_handshake(
            base_url=row.base_url, secret=secret, transport=transport
        )
    except HandshakeError as exc:
        status = exc.status
    else:
        # The address now answering as a different app, or serving a manifest
        # that no longer hashes to the recorded one, are both recorded rather
        # than adopted: what a registration names and accepts is the operator's
        # statement, and a background sweep does not rewrite one.
        changed_manifest = (
            row.manifest_hash is not None and row.manifest_hash != result.manifest_hash
        )
        if result.public_id != row.public_id or changed_manifest:
            status = AppServiceStatus.MANIFEST_MISMATCH
        else:
            status = AppServiceStatus.OK
            row.listing_uid = result.listing_uid
            row.manifest_hash = result.manifest_hash
            row.protocol_version = result.protocol_version

    row.status = status
    if status == AppServiceStatus.OK:
        row.last_verified_at = _now()
    row.updated_at = _now()
    session.add(row)
    return status


async def sweep_registrations(
    *, transport: httpx.AsyncBaseTransport | None = None
) -> SweepResult:
    """Re-verify every enabled registration that can be verified."""
    checked = ok = failed = skipped = 0
    async with db_session.AdminSessionLocal() as session:
        rows = (
            await session.exec(
                select(AppServiceRegistration).order_by(AppServiceRegistration.id)
            )
        ).all()
        for row in rows:
            if not row.enabled or not row.secret_encrypted:
                # A registration the operator switched off, or one with no
                # secret, has nothing to prove. Its recorded status stands.
                skipped += 1
                continue
            checked += 1
            try:
                status = await _reverify_one(session, row, transport=transport)
            except Exception:
                failed += 1
                logger.exception(
                    "app services: %s could not be re-verified", row.public_id
                )
                continue
            if status == AppServiceStatus.OK:
                ok += 1
            else:
                failed += 1
                logger.warning("app services: %s is %s", row.public_id, status)
        await session.commit()

    # The request path reads registrations through a cached snapshot; a status
    # this sweep just changed should be what the next read sees.
    registration_lookup.invalidate_registrations()
    return SweepResult(checked=checked, ok=ok, failed=failed, skipped=skipped)


async def process_app_service_reverification() -> None:
    """The background worker's one pass."""
    if not reverification_configured():
        return
    result = await sweep_registrations()
    if result.checked:
        logger.info(
            "app services: re-verified %d (%d ok, %d failing, %d skipped)",
            result.checked,
            result.ok,
            result.failed,
            result.skipped,
        )
