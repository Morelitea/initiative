"""Least-privilege + replay-safety of the auto-delegation jti blocklist purge.

The generic sweep and the FOSS gating live in ``jti_purge_test.py`` (the one
shared worker covers both blocklists). Here we pin the two things specific to
this table (issue #842):

* DELETE is *only* the system engine's — the request-path login role that
  inserts jtis at redemption cannot prune them (least privilege; ``app_admin``
  gained DELETE in migration ``20260709_0135``);
* pruning is safe: an expired delegation JWT is refused by its own ``exp`` at
  verification before the blocklist is read, so removing its spent row never
  re-opens a replay window (the ``test_purged_jti_still_unreplayable`` shape).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import select

from app.core import config as config_module
from app.core.security import (
    AutoDelegationVerificationError,
    verify_auto_delegation_token,
)
from app.db.jti_blocklist import purge_expired_jtis
from app.models.platform.auto_delegation_jti import AutoDelegationJti

pytestmark = [pytest.mark.integration, pytest.mark.database]

_keypair = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _keypair.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
_PUBLIC_PEM = (
    _keypair.public_key()
    .public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode()
)


def _mint(*, jti: str, expires_in: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "jti": jti,
            "sub": "1",
            "aud": config_module.settings.AUTO_DELEGATION_AUDIENCE,
            "iss": config_module.settings.AUTO_DELEGATION_ISSUER,
            "iat": int(now.timestamp()),
            "exp": now + timedelta(seconds=expires_in),
            "guild_id": 1,
        },
        _PRIVATE_PEM,
        algorithm="RS256",
    )


async def _add_jti(session, jti: str, *, expired: bool) -> None:
    now = datetime.now(timezone.utc)
    delta = timedelta(hours=1)
    session.add(
        AutoDelegationJti(
            jti=jti,
            redeemed_at=now - delta,
            expires_at=(now - delta) if expired else (now + delta),
        )
    )
    await session.commit()


async def test_request_role_cannot_delete_blocklist(session, role_session):
    """DELETE is the system engine's alone — the request-path login role that
    inserts jtis at redemption must not be able to prune them."""
    await _add_jti(session, "deleg-locked", expired=True)

    user = await role_session("app_user")
    with pytest.raises(DBAPIError):
        await user.execute(text("DELETE FROM auto_delegation_jti_blocklist"))
    await user.rollback()

    # Still there — the failed DELETE changed nothing.
    survivor = (
        await session.exec(
            select(AutoDelegationJti).where(AutoDelegationJti.jti == "deleg-locked")
        )
    ).one_or_none()
    assert survivor is not None


async def test_purged_jti_still_unreplayable(session, role_session, monkeypatch):
    """Pruning an expired jti never re-opens a replay window: the token's own
    exp refuses it at verification, before the blocklist is consulted."""
    monkeypatch.setattr(
        config_module.settings, "AUTO_DELEGATION_PUBLIC_KEY_PEM", _PUBLIC_PEM
    )
    jti = "deleg-purged"
    token = _mint(jti=jti, expires_in=-30)  # exp already in the past

    # Simulate the long-ago redemption whose row the janitor prunes.
    await _add_jti(session, jti, expired=True)
    admin = await role_session("app_admin")
    assert await purge_expired_jtis(admin, AutoDelegationJti) >= 1

    gone = (
        await session.exec(
            select(AutoDelegationJti).where(AutoDelegationJti.jti == jti)
        )
    ).one_or_none()
    assert gone is None

    # Blocklist row gone, but the token's exp still refuses the replay.
    with pytest.raises(AutoDelegationVerificationError):
        verify_auto_delegation_token(token)
