"""The single jti-blocklist janitor sweeps every configured blocklist.

One worker replaces the per-table janitors: it prunes expired rows from each
jti blocklist whose integration is configured, under the system engine's
DELETE grant, and is a strict no-op when nothing is wired (the self-host
default). Per-table replay-safety/least-privilege live in each blocklist's
own test module; here we pin the shared worker's gating and correctness.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core import config as config_module
from app.models.platform.auto_delegation_jti import AutoDelegationJti
from app.models.platform.billing import BillingJti
from app.services.platform import jti_purge
from app.services.platform.jti_purge import process_jti_blocklist_purges

pytestmark = [pytest.mark.integration, pytest.mark.database]


def _configure(monkeypatch, *, billing: bool, delegation: bool) -> None:
    monkeypatch.setattr(
        config_module.settings,
        "BILLING_PUBLIC_KEY_PEM",
        "pk" if billing else None,
    )
    monkeypatch.setattr(
        config_module.settings,
        "BILLING_HMAC_SECRET",
        "secret" if billing else None,
    )
    monkeypatch.setattr(
        config_module.settings,
        "AUTO_DELEGATION_PUBLIC_KEY_PEM",
        "pk" if delegation else None,
    )


async def _add(session, model, jti: str, *, expired: bool) -> None:
    now = datetime.now(timezone.utc)
    delta = timedelta(hours=1)
    session.add(
        model(
            jti=jti,
            redeemed_at=now - delta,
            expires_at=(now - delta) if expired else (now + delta),
        )
    )
    await session.commit()


async def _exists(session, model, jti: str) -> bool:
    from sqlmodel import select

    row = (await session.exec(select(model).where(model.jti == jti))).one_or_none()
    return row is not None


async def test_worker_prunes_only_expired_across_all_blocklists(session, monkeypatch):
    _configure(monkeypatch, billing=True, delegation=True)
    await _add(session, BillingJti, "b-old", expired=True)
    await _add(session, BillingJti, "b-live", expired=False)
    await _add(session, AutoDelegationJti, "d-old", expired=True)
    await _add(session, AutoDelegationJti, "d-live", expired=False)

    await process_jti_blocklist_purges()

    assert not await _exists(session, BillingJti, "b-old")
    assert not await _exists(session, AutoDelegationJti, "d-old")
    # Live rows are still replay guards — never touched.
    assert await _exists(session, BillingJti, "b-live")
    assert await _exists(session, AutoDelegationJti, "d-live")


async def test_worker_skips_unconfigured_blocklist(session, monkeypatch):
    """Billing wired, delegation not: only billing's table is swept. A missed
    ping-free self-host of one integration must not touch the other's rows."""
    _configure(monkeypatch, billing=True, delegation=False)
    await _add(session, BillingJti, "b-skip", expired=True)
    await _add(session, AutoDelegationJti, "d-skip", expired=True)

    await process_jti_blocklist_purges()

    assert not await _exists(session, BillingJti, "b-skip")
    # Delegation unconfigured -> its blocklist is left entirely alone.
    assert await _exists(session, AutoDelegationJti, "d-skip")


async def test_worker_continues_after_a_sweep_fails(session, monkeypatch):
    """A failure sweeping one blocklist must not skip the rest — the shared
    session stays usable and the next table is still pruned."""
    _configure(monkeypatch, billing=True, delegation=True)
    await _add(session, AutoDelegationJti, "d-after-fail", expired=True)

    real_purge = jti_purge.purge_expired_jtis

    async def flaky(sess, model):
        if model is BillingJti:
            raise RuntimeError("boom")
        return await real_purge(sess, model)

    monkeypatch.setattr(jti_purge, "purge_expired_jtis", flaky)
    await process_jti_blocklist_purges()

    # Billing's sweep raised, but the delegation table was still swept.
    assert not await _exists(session, AutoDelegationJti, "d-after-fail")


async def test_worker_noop_when_nothing_configured(monkeypatch):
    """Self-host default: neither integration wired -> no session is opened."""
    import app.db.session as session_module

    def _explode(*args, **kwargs):
        raise AssertionError("worker opened a session with nothing configured")

    _configure(monkeypatch, billing=False, delegation=False)
    monkeypatch.setattr(session_module, "AdminSessionLocal", _explode)
    await process_jti_blocklist_purges()
