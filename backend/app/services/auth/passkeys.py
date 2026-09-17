"""Registering a WebAuthn credential, and answering with one.

The ceremony is the library's; what lives here is everything around it — which
relying party this deployment is, what a credential row holds, and the rules
about when one may be made or used.

Two things are deliberately *not* here. Nothing in this module opens a session:
it reports what a ceremony proved and the caller decides what that is worth.
And no route calls it yet — enrolment is the change after this one.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import webauthn
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.models.platform.user_passkey import UserPasskey

#: How long a ceremony's challenge stands. The browser prompt is a few seconds
#: of work; a minute is the library's own default and plenty.
CEREMONY_TIMEOUT_MS = 60_000

#: The most credentials one account may register. High enough that nobody
#: bumps it — a phone, a laptop, two hardware keys and room to spare — and low
#: enough that the allow-list sent to a browser stays small.
MAX_PASSKEYS_PER_USER = 20

MAX_NAME_LENGTH = 64


def _now() -> datetime:
    return datetime.now(timezone.utc)


def relying_party_id() -> str:
    """The domain this deployment's credentials belong to.

    A passkey is bound to it, which is the property that makes it worth having
    and also the thing to be careful with: it is derived from ``APP_URL``, so a
    deployment that moves domain is a deployment whose existing credentials no
    longer answer. Every row records the value it was made under so that can be
    said plainly rather than surfacing as a signature that will not verify.
    """
    from app.core.config import settings

    host = urlsplit(settings.APP_URL.strip()).hostname
    if not host:
        raise RuntimeError("APP_URL names no host, so no relying party can be derived")
    return host


def expected_origin() -> str:
    """The origin a ceremony must have come from — scheme, host and port."""
    from app.core.config import settings

    parts = urlsplit(settings.APP_URL.strip())
    if not parts.scheme or not parts.hostname:
        raise RuntimeError("APP_URL is not a whole URL, so no origin can be derived")
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{parts.hostname}{port}"


def relying_party_name() -> str:
    """What the browser prompt calls this deployment."""
    return relying_party_id()


@dataclass(frozen=True)
class Ceremony:
    """Options for the browser, and the challenge they must come back with."""

    options: dict[str, Any]
    challenge: bytes


@dataclass(frozen=True)
class RegisteredCredential:
    """What a finished registration proved, before it is anybody's."""

    credential_id: bytes
    public_key: bytes
    sign_count: int
    aaguid: str | None
    user_verified: bool
    backed_up: bool
    transports: list[str]


async def list_for_user(session: AsyncSession, *, user_id: int) -> list[UserPasskey]:
    rows = await session.exec(
        select(UserPasskey)
        .where(UserPasskey.user_id == user_id)
        .order_by(UserPasskey.created_at)
    )
    return list(rows.all())


async def count_for_user(session: AsyncSession, *, user_id: int) -> int:
    return len(await list_for_user(session, user_id=user_id))


async def begin_registration(
    session: AsyncSession, *, user_id: int, account_name: str, display_name: str
) -> Ceremony:
    """Options for making a new credential on this account.

    The credentials the account already holds go out as ``excludeCredentials``,
    so an authenticator that already has one for this deployment says so rather
    than quietly making a second.
    """
    existing = await list_for_user(session, user_id=user_id)
    options = webauthn.generate_registration_options(
        rp_id=relying_party_id(),
        rp_name=relying_party_name(),
        user_id=str(user_id).encode(),
        user_name=account_name,
        user_display_name=display_name,
        timeout=CEREMONY_TIMEOUT_MS,
        authenticator_selection=AuthenticatorSelectionCriteria(
            # Discoverable, so signing in can start from the key rather than
            # from a typed address — which is the whole shape of the sign-in
            # this is for.
            resident_key=ResidentKeyRequirement.PREFERRED,
            # Asked for, not insisted on: a key that only proves the device is
            # still a way in, and the row records which kind it was so a rule
            # can tell them apart later.
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=row.credential_id) for row in existing
        ],
    )
    return Ceremony(
        options=_options_to_dict(options), challenge=bytes(options.challenge)
    )


def finish_registration(
    *, credential: dict[str, Any], expected_challenge: bytes
) -> RegisteredCredential:
    """Check a finished ceremony. Raises on anything that does not verify."""
    verified = webauthn.verify_registration_response(
        credential=credential,
        expected_challenge=expected_challenge,
        expected_rp_id=relying_party_id(),
        expected_origin=expected_origin(),
    )
    transports = credential.get("response", {}).get("transports") or []
    return RegisteredCredential(
        credential_id=bytes(verified.credential_id),
        public_key=bytes(verified.credential_public_key),
        sign_count=int(verified.sign_count),
        aaguid=verified.aaguid,
        user_verified=bool(verified.user_verified),
        backed_up=bool(verified.credential_backed_up),
        transports=[str(t) for t in transports],
    )


async def store(
    session: AsyncSession,
    *,
    user_id: int,
    registered: RegisteredCredential,
    name: str,
) -> UserPasskey:
    """Keep a verified credential. The caller commits."""
    row = UserPasskey(
        user_id=user_id,
        credential_id=registered.credential_id,
        public_key=registered.public_key,
        rp_id=relying_party_id(),
        sign_count=registered.sign_count,
        transports=registered.transports,
        aaguid=registered.aaguid,
        user_verified=registered.user_verified,
        backed_up=registered.backed_up,
        name=name[:MAX_NAME_LENGTH],
    )
    session.add(row)
    await session.flush()
    return row


async def begin_authentication(
    session: AsyncSession, *, user_id: int | None = None
) -> Ceremony:
    """Options for answering with a credential.

    With no ``user_id`` the allow-list is empty, which is what lets somebody
    sign in without saying who they are first: the authenticator offers what it
    holds for this domain and the assertion names the credential.
    """
    allow: list[PublicKeyCredentialDescriptor] = []
    if user_id is not None:
        allow = [
            PublicKeyCredentialDescriptor(id=row.credential_id)
            for row in await list_for_user(session, user_id=user_id)
        ]
    options = webauthn.generate_authentication_options(
        rp_id=relying_party_id(),
        timeout=CEREMONY_TIMEOUT_MS,
        allow_credentials=allow or None,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    return Ceremony(
        options=_options_to_dict(options), challenge=bytes(options.challenge)
    )


async def find_by_credential_id(
    session: AsyncSession, *, credential_id: bytes
) -> UserPasskey | None:
    rows = await session.exec(
        select(UserPasskey).where(UserPasskey.credential_id == credential_id)
    )
    return rows.first()


@dataclass(frozen=True)
class Assertion:
    """What answering with a credential proved."""

    passkey: UserPasskey
    user_verified: bool


async def finish_authentication(
    session: AsyncSession, *, credential: dict[str, Any], expected_challenge: bytes
) -> Assertion | None:
    """Check an assertion and record that the credential was used.

    ``None`` when the credential is unknown, was made for another domain, or
    does not verify — one answer for all three, because the caller's refusal is
    the same either way.
    """
    raw_id = credential.get("rawId") or credential.get("id")
    if not raw_id:
        return None
    try:
        credential_id = webauthn.base64url_to_bytes(raw_id)
    except Exception:
        return None

    row = await find_by_credential_id(session, credential_id=credential_id)
    if row is None:
        return None

    rp_id = relying_party_id()
    if row.rp_id != rp_id:
        # Registered when this deployment answered to another name. It cannot
        # verify here, and saying so is better than a failed signature.
        return None

    try:
        verified = webauthn.verify_authentication_response(
            credential=credential,
            expected_challenge=expected_challenge,
            expected_rp_id=rp_id,
            expected_origin=expected_origin(),
            credential_public_key=row.public_key,
            credential_current_sign_count=row.sign_count,
        )
    except Exception:
        return None

    row.sign_count = int(verified.new_sign_count)
    row.last_used_at = _now()
    row.backed_up = bool(verified.credential_backed_up)
    session.add(row)
    await session.flush()
    return Assertion(passkey=row, user_verified=bool(verified.user_verified))


async def rename(
    session: AsyncSession, *, user_id: int, passkey_id: Any, name: str
) -> bool:
    row = await session.get(UserPasskey, passkey_id)
    if row is None or row.user_id != user_id:
        return False
    row.name = name[:MAX_NAME_LENGTH]
    session.add(row)
    await session.flush()
    return True


async def remove(session: AsyncSession, *, user_id: int, passkey_id: Any) -> bool:
    row = await session.get(UserPasskey, passkey_id)
    if row is None or row.user_id != user_id:
        return False
    await session.delete(row)
    await session.flush()
    return True


def generate_challenge() -> bytes:
    """A challenge of our own, for a caller holding one outside a ceremony."""
    return secrets.token_bytes(32)


def _options_to_dict(options: Any) -> dict[str, Any]:
    """The library's options as plain JSON-ready data.

    ``options_to_json`` renders every binary field the way the browser API
    expects it, so the shape the client receives is the library's rather than
    one assembled here.
    """
    import json

    return json.loads(webauthn.options_to_json(options))
