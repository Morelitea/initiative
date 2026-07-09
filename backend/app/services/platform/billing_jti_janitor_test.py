"""The billing jti blocklist must not grow forever — and its purge must run
under the system engine's real grants (SELECT/DELETE for ``app_admin``, per
``app/db/system_grants.py``), not the test superuser."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from app.models.platform.billing import BillingJti
from app.services.platform.billing_jti_janitor import (
    process_billing_jti_purge,
    purge_expired_billing_jtis,
)

pytestmark = [pytest.mark.integration, pytest.mark.database]


async def test_purge_skipped_when_billing_unconfigured(monkeypatch):
    """FOSS no-op: with inbound billing unset (the self-host default) the
    worker returns without touching the database — no session is opened."""
    import app.db.session as session_module

    def _explode(*args, **kwargs):
        raise AssertionError("janitor opened a session on an unconfigured host")

    monkeypatch.setattr(session_module, "AdminSessionLocal", _explode)
    # settings.BILLING_* are unset by default in the test config.
    await process_billing_jti_purge()


async def test_purge_removes_only_expired_rows(session, role_session):
    now = datetime.now(timezone.utc)
    session.add(
        BillingJti(
            jti="janitor-expired",
            redeemed_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
        )
    )
    session.add(
        BillingJti(
            jti="janitor-live",
            redeemed_at=now,
            expires_at=now + timedelta(minutes=5),
        )
    )
    await session.commit()

    admin = await role_session("app_admin")
    purged = await purge_expired_billing_jtis(admin)
    assert purged >= 1

    remaining = {row.jti for row in (await session.exec(select(BillingJti))).all()}
    assert "janitor-expired" not in remaining
    # A live row is still a replay guard — the janitor must never touch it.
    assert "janitor-live" in remaining
