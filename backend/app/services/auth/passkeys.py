"""Registering a WebAuthn credential, and answering with one.

The ceremony is the library's; what lives here is everything around it — which
relying party this deployment is, what a credential row holds, and the rules
about when one may be made or used.

One thing is deliberately *not* here: nothing in this module opens a session.
It reports what a ceremony proved and the caller decides what that is worth.

Every ceremony requires user verification, registration and sign-in alike, so
a credential this deployment holds proves the person as well as the device.
``user_verified`` stays on the row because it records what the ceremony
reported rather than what was asked for.
"""

from __future__ import annotations

import ipaddress
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlsplit

import webauthn
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.models.platform.user import User
from app.models.platform.user_passkey import UserPasskey

#: How long a ceremony's challenge stands. The browser prompt is a few seconds
#: of work; a minute is the library's own default and plenty.
CEREMONY_TIMEOUT_MS = 60_000

#: The most credentials one account may register. High enough that nobody
#: bumps it — a phone, a laptop, two hardware keys and room to spare — and low
#: enough that the allow-list sent to a browser stays small.
MAX_PASSKEYS_PER_USER = 20

MAX_NAME_LENGTH = 64

#: The ways of naming the machine itself. A browser treats all three as a
#: secure context, so a deployment addressed by one is an ordinary development
#: setup rather than an address passkeys cannot use.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class PasskeyLimitReached(Exception):
    """The account already has the maximum number of credentials."""


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
    scheme = parts.scheme.lower()
    hostname = parts.hostname
    host = f"[{hostname}]" if ":" in hostname else hostname
    is_default_port = (scheme == "https" and parts.port == 443) or (
        scheme == "http" and parts.port == 80
    )
    port = f":{parts.port}" if parts.port is not None and not is_default_port else ""
    return f"{scheme}://{host}{port}"


def relying_party_name() -> str:
    """What the browser prompt calls this deployment."""
    return relying_party_id()


def site_refusal() -> str | None:
    """Why this deployment's address cannot carry passkeys, or ``None``.

    A credential is bound to a named host reached over https. ``"no_host"``
    says ``APP_URL`` names no host at all; ``"ip_host"`` says it names an
    address rather than a domain; ``"insecure_origin"`` says it is plain http
    somewhere other than the machine itself. All three are properties of the
    deployment's address, so they are answered before a ceremony is begun
    rather than by the browser afterwards — and a caller that has one of them
    never reaches :func:`relying_party_id`, which has no answer to give.
    """
    from app.core.config import settings

    parts = urlsplit(settings.APP_URL.strip())
    host = parts.hostname
    if not host:
        return "no_host"
    # The machine itself is a development address, however it is spelled, so
    # loopback is settled before the address-rather-than-domain rule.
    if host.lower() in _LOCAL_HOSTS:
        return None
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return "ip_host"
    if parts.scheme.lower() == "http":
        return "insecure_origin"
    return None


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
    return (
        await session.exec(
            select(func.count())
            .select_from(UserPasskey)
            .where(UserPasskey.user_id == user_id)
        )
    ).one()


async def begin_registration(
    session: AsyncSession, *, user_id: int, account_name: str, display_name: str
) -> Ceremony:
    """Options for making a new credential on this account.

    The credentials the account already holds go out as ``excludeCredentials``,
    so an authenticator that already has one for this deployment says so rather
    than quietly making a second.
    """
    existing = await list_for_user(session, user_id=user_id)
    if len(existing) >= MAX_PASSKEYS_PER_USER:
        raise PasskeyLimitReached
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
            # Required: a credential registered here proves the person — a
            # PIN, a fingerprint, a face — as well as the device, which is
            # what makes signing in with one a multi-factor authentication and
            # why no code is asked for afterwards. The row still records what
            # the ceremony reported.
            user_verification=UserVerificationRequirement.REQUIRED,
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
        require_user_verification=True,
    )
    response = credential.get("response")
    return RegisteredCredential(
        credential_id=bytes(verified.credential_id),
        public_key=bytes(verified.credential_public_key),
        sign_count=int(verified.sign_count),
        aaguid=verified.aaguid,
        user_verified=bool(verified.user_verified),
        backed_up=bool(verified.credential_backed_up),
        transports=_accepted_transports(
            response.get("transports") if isinstance(response, dict) else None
        ),
    )


def _accepted_transports(reported: Any) -> list[str]:
    """The transports the browser reported, keeping the ones WebAuthn defines.

    The value arrives from the client, and the column and the options sent back
    to a browser later hold whatever is kept, so anything the specification does
    not name is dropped.
    """
    if not isinstance(reported, list):
        return []
    kept: list[str] = []
    for value in reported:
        if not isinstance(value, str):
            continue
        try:
            AuthenticatorTransport(value)
        except ValueError:
            continue
        kept.append(value)
    return kept


async def store(
    session: AsyncSession,
    *,
    user_id: int,
    registered: RegisteredCredential,
    name: str,
) -> UserPasskey:
    """Keep a verified credential. The caller commits.

    Locking the account makes the limit authoritative even when two empty
    slots are inspected concurrently. There is no passkey row to lock when an
    account registers its first credential, so the stable parent is the
    serialization point.
    """
    users = await session.exec(select(User).where(User.id == user_id).with_for_update())
    if users.first() is None:
        raise ValueError("cannot store a passkey for an unknown user")
    if await count_for_user(session, user_id=user_id) >= MAX_PASSKEYS_PER_USER:
        raise PasskeyLimitReached

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


def begin_authentication(*, credentials: Sequence[UserPasskey] = ()) -> Ceremony:
    """Options for answering with a credential.

    With no ``credentials`` the allow-list is empty, which is what lets
    somebody sign in without saying who they are first: the authenticator
    offers what it holds for this domain and the assertion names the
    credential. A step-up hands over the account's own rows, which it has
    already read, so the browser is asked for one of those.
    """
    allow = [PublicKeyCredentialDescriptor(id=row.credential_id) for row in credentials]
    options = webauthn.generate_authentication_options(
        rp_id=relying_party_id(),
        timeout=CEREMONY_TIMEOUT_MS,
        allow_credentials=allow or None,
        # Required, as at registration: the assertion proves the person as
        # well as the device, so the session it opens is a multi-factor one.
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return Ceremony(
        options=_options_to_dict(options), challenge=bytes(options.challenge)
    )


async def find_by_credential_id(
    session: AsyncSession, *, credential_id: bytes, for_update: bool = False
) -> UserPasskey | None:
    statement = select(UserPasskey).where(UserPasskey.credential_id == credential_id)
    if for_update:
        statement = statement.with_for_update()
    rows = await session.exec(statement)
    return rows.first()


@dataclass(frozen=True)
class Assertion:
    """What answering with a credential proved."""

    passkey: UserPasskey
    user_verified: bool


@dataclass(frozen=True)
class AssertionRefusal:
    """Why an assertion proved nothing, and the credential it named.

    ``unknown`` is a credential id this deployment holds no row for,
    ``wrong_rp`` one registered while it answered to another domain, and
    ``invalid`` one whose signature did not check out. ``passkey`` is the row
    the id named where there is one, so the caller can write the refusal down
    against the account it belongs to. What the caller answers the client with
    is the same for all three.
    """

    reason: Literal["unknown", "wrong_rp", "invalid"]
    passkey: UserPasskey | None = None


async def finish_authentication(
    session: AsyncSession, *, credential: dict[str, Any], expected_challenge: bytes
) -> Assertion | AssertionRefusal:
    """Check an assertion and record that the credential was used.

    An :class:`AssertionRefusal` where nothing was proved, carrying which of
    the three it was and the credential the id named. An assertion that did not
    verify the person is one of the ones that does not verify: user
    verification is required here.
    """
    raw_id = credential.get("rawId") or credential.get("id")
    if not raw_id:
        return AssertionRefusal(reason="unknown")
    try:
        credential_id = webauthn.base64url_to_bytes(raw_id)
    except Exception:
        return AssertionRefusal(reason="unknown")

    row = await find_by_credential_id(
        session, credential_id=credential_id, for_update=True
    )
    if row is None:
        return AssertionRefusal(reason="unknown")

    rp_id = relying_party_id()
    if row.rp_id != rp_id:
        # Registered when this deployment answered to another name. It cannot
        # verify here, and saying so is better than a failed signature.
        return AssertionRefusal(reason="wrong_rp", passkey=row)

    try:
        verified = webauthn.verify_authentication_response(
            credential=credential,
            expected_challenge=expected_challenge,
            expected_rp_id=rp_id,
            expected_origin=expected_origin(),
            credential_public_key=row.public_key,
            credential_current_sign_count=row.sign_count,
            require_user_verification=True,
        )
    except Exception:
        return AssertionRefusal(reason="invalid", passkey=row)

    row.sign_count = int(verified.new_sign_count)
    row.last_used_at = _now()
    row.backed_up = bool(verified.credential_backed_up)
    session.add(row)
    await session.flush()
    return Assertion(passkey=row, user_verified=bool(verified.user_verified))


async def rename(
    session: AsyncSession, *, user_id: int, passkey_id: Any, name: str
) -> UserPasskey | None:
    """Give the account's credential another name, and hand the row back.

    ``None`` when the account holds no such credential.
    """
    row = await session.get(UserPasskey, passkey_id)
    if row is None or row.user_id != user_id:
        return None
    row.name = name[:MAX_NAME_LENGTH]
    session.add(row)
    await session.flush()
    return row


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
