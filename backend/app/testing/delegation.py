"""One delegate, for the suites that need a delegation token to be accepted.

A delegation token is decided by the registration whose key set published its
``kid``, so a test that wants one accepted registers an app rather than setting
a value. This module holds the keypair, the JWKS built from it, the minting,
and the registration — one place, so a suite states *which* app is delegating
rather than restating how delegation is wired.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.app_service_registration import (
    AppServiceRegistration,
    AppServiceStatus,
)
from app.services.marketplace.registration_lookup import invalidate_registrations

__all__ = [
    "DELEGATE_KID",
    "DELEGATE_PUBLIC_ID",
    "authorize_delegate",
    "delegate_subject",
    "delegation_jwks",
    "DELEGATE_LISTING_UID",
    "delegation_verification_keys",
    "install_delegate",
    "foreign_jwks",
    "mint_delegation_token",
    "register_delegate",
]

#: The app that delegates in tests, and the key it signs with. The shape
#: mirrors what a real delegate publishes: its public id, then a generation
#: suffix, because a rotation runs two entries in one key set.
DELEGATE_PUBLIC_ID = "acme.auto"
DELEGATE_KID = f"{DELEGATE_PUBLIC_ID}-delegation-1"
#: The listing the delegate's registration names, and therefore what a guild
#: installs to let it act there.
DELEGATE_LISTING_UID = "DELEGATE000001"

# One keypair per test session. Generated rather than checked in so no test
# depends on a fixed modulus, and cheap enough at 2048 bits to build once.
_keypair = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _keypair.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()


def delegation_jwks(kid: str = DELEGATE_KID) -> dict[str, Any]:
    """The public half, in the shape an operator provisions."""
    entry = json.loads(RSAAlgorithm.to_jwk(_keypair.public_key()))
    entry["kid"] = kid
    return {"keys": [entry]}


_foreign_keypair = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def foreign_jwks(kid: str = DELEGATE_KID) -> dict[str, Any]:
    """A key set under the given ``kid`` belonging to a different keypair — for
    the case where two apps happen to choose the same opaque label."""
    entry = json.loads(RSAAlgorithm.to_jwk(_foreign_keypair.public_key()))
    entry["kid"] = kid
    return {"keys": [entry]}


def mint_delegation_token(
    *,
    subject: str,
    guild_id: int,
    initiative_id: Optional[int] = None,
    jti: Optional[str] = None,
    kid: Optional[str] = DELEGATE_KID,
    aud: str = "initiative:auto-delegation",
    iss: str = "initiative-auto",
    private_pem: str = _PRIVATE_PEM,
    expires_in: int = 900,
) -> str:
    """A delegation JWT as the delegate would mint it.

    ``subject`` is the pairwise identifier the app was given for a member, not
    a user id — an app never learns which Initiative user it acts for. Get one
    from :func:`delegate_subject`.
    """
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "jti": jti or secrets.token_hex(8),
        "sub": subject,
        "aud": aud,
        "iss": iss,
        "iat": int(now.timestamp()),
        "exp": now + timedelta(seconds=expires_in),
        "guild_id": guild_id,
    }
    if initiative_id is not None:
        payload["initiative_id"] = initiative_id
    return jwt.encode(
        payload,
        private_pem,
        algorithm="RS256",
        headers={"kid": kid} if kid else None,
    )


async def register_delegate(
    session: AsyncSession,
    *,
    public_id: str = DELEGATE_PUBLIC_ID,
    grants: tuple[str, ...] = ("delegation",),
    enabled: bool = True,
    key_set: Optional[dict[str, Any]] = None,
) -> AppServiceRegistration:
    """Wire up the app whose tokens the suite expects to be accepted.

    Written straight to the table rather than through the registration service:
    that path runs a handshake against the app, and there is no app here — only
    the row the resolver reads.
    """
    row = AppServiceRegistration(
        public_id=public_id,
        listing_uid=DELEGATE_LISTING_UID,
        base_url="http://auto.test:8080",
        allowed_origins=["http://auto.test:8080"],
        secret_encrypted=None,
        grants=list(grants),
        delegation_jwks=delegation_jwks() if key_set is None else key_set,
        enabled=enabled,
        status=AppServiceStatus.OK,
    )
    session.add(row)
    await session.commit()
    # The resolver reads a cached snapshot; a row written behind its back is
    # not one it would notice on its own.
    invalidate_registrations()
    return row


def delegation_verification_keys() -> tuple[Any, ...]:
    """The public key itself, for a test calling the verifier directly rather
    than through the auth dep that would resolve it from a registration."""
    return (_keypair.public_key(),)


async def install_delegate(session: AsyncSession, guild, creator=None) -> Any:
    """Install the delegate in a guild, which is what lets it act there.

    An app reaches a guild because that guild installed it, so a test that
    expects a delegated call to succeed installs the app as well as registering
    it — the two halves an operator and a guild admin each own.
    """
    from sqlmodel import select

    from app.models.tenant.guild_app import GuildApp
    from app.testing.factories import create_guild_app, create_user
    from app.testing.schema_harness import route_session_to_guild

    # Resolved before the session is routed: a user is a public row, and
    # writing one on a guild-routed session is not a thing this should do.
    installer = creator or await create_user(session)

    await route_session_to_guild(session, guild.id)
    existing = (
        await session.exec(
            select(GuildApp).where(GuildApp.listing_uid == DELEGATE_LISTING_UID)
        )
    ).first()
    if existing is not None:
        return existing

    return await create_guild_app(
        session,
        guild,
        installer,
        definition={
            "app_kind": "service",
            "service": {"public_id": DELEGATE_PUBLIC_ID},
        },
        listing_uid=DELEGATE_LISTING_UID,
        name="Delegate",
    )


async def delegate_subject(session: AsyncSession, guild, user) -> str:
    """The pairwise subject the delegate knows one member by.

    Installs the app if the guild has not, because the subject's sector is the
    install — there is no subject for an app that is not there.
    """
    from app.services.marketplace.app_subjects import ensure_subject

    app = await install_delegate(session, guild)
    subject = await ensure_subject(
        session, app_install_id=app.id, guild_id=guild.id, user_id=user.id
    )
    await session.commit()
    return subject


async def authorize_delegate(
    session: AsyncSession, guild, user, *, can_write: bool = True
) -> Any:
    """Let the delegate act as one member of a guild.

    A delegated call needs three yeses — the operator granted the app, the guild
    installed it, and the member authorized it to carry their name. This is the
    third, and it installs the app first if the guild has not already, so a
    suite whose subject is something else states the precondition in one line.
    """
    from app.testing.factories import create_app_delegation

    app = await install_delegate(session, guild)
    return await create_app_delegation(session, app, user, can_write=can_write)
