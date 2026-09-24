"""The app platform's token endpoint: who is asking, and what they are given.

Initiative is the authorization server for the apps a deployment registers.
One endpoint, form-encoded per RFC 6749, authenticates the app by a JWT it
signs with a key its registration publishes (RFC 7523 §2.2,
``private_key_jwt``) and issues one of two sealed access tokens
(:mod:`app.core.app_access_token`):

* ``client_credentials`` alone: an **app token**, which lists the app's installs;
* ``client_credentials`` with ``installation``: an **installation token** for
  that install, optionally down-scoped (``scope``, RFC 6749 §3.3) and narrowed
  to one initiative it is placed in (``resource``, RFC 8707).

The member grant (``urn:ietf:params:oauth:grant-type:jwt-bearer``) is refused
as unsupported for now.

Everything here runs on the system engine. A community's rows are read with
the session routed by ``guild_id`` alone, as any sweep reads them.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.app_access_token import (
    ACCESS_TOKEN_LIFETIME_SECONDS,
    seal_app_token,
    seal_install_token,
)
from app.core.app_scopes import expand, ALL_SCOPES, UnknownAppScope, validate_scopes
from app.core.config import API_V1_STR, settings
from app.db.session import clear_rls_context, set_rls_context
from app.models.platform.app_assertion_jti import ASSERTION_JTI_MAX_LENGTH
from app.models.platform.guild import LIVE_STATUS_VALUES, Guild
from app.services.marketplace import app_refs, registration_lookup
from app.services.marketplace.registration_lookup import RegistrationSnapshot

logger = logging.getLogger(__name__)

__all__ = [
    "ASSERTION_TYPE",
    "GRANT_CLIENT_CREDENTIALS",
    "GRANT_JWT_BEARER",
    "INITIATIVE_RESOURCE_PREFIX",
    "InstallationListing",
    "IssuedToken",
    "OAuthError",
    "TOKEN_PATH",
    "issue_token",
    "list_installations",
    "token_endpoint_url",
    "verify_client_assertion",
]

#: Where the endpoint is mounted, under the API prefix.
TOKEN_PATH = f"{API_V1_STR}/app-platform/oauth/token"

ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
GRANT_CLIENT_CREDENTIALS = "client_credentials"
GRANT_JWT_BEARER = "urn:ietf:params:oauth:grant-type:jwt-bearer"
#: A ``resource`` naming one initiative: this prefix, then its id.
INITIATIVE_RESOURCE_PREFIX = "urn:initiative:initiative:"

#: The longest an assertion may be valid for, from its ``iat`` to its ``exp``.
MAX_ASSERTION_LIFETIME_SECONDS = 300
#: How far ahead of this server's clock an assertion's ``iat`` may be.
IAT_CLOCK_SKEW_SECONDS = 60

_DIGITS = frozenset("0123456789")
#: An initiative id is a Postgres ``integer``.
_MAX_INITIATIVE_ID = 2**31 - 1


class OAuthError(Exception):
    """An error response the token endpoint owes its caller (RFC 6749 §5.2)."""

    def __init__(self, error: str, description: str, status_code: int = 400) -> None:
        super().__init__(f"{error}: {description}")
        self.error = error
        self.description = description
        self.status_code = status_code


def _invalid_client(description: str) -> OAuthError:
    return OAuthError("invalid_client", description, status_code=401)


def token_endpoint_url() -> str:
    """The token endpoint's absolute URL: the ``aud`` every client assertion
    must carry, exactly.

    Built from ``APP_URL`` the way every other public callback address is: the
    API is served under the same origin as the app, at ``API_V1_STR``.
    """
    return f"{settings.APP_URL.rstrip('/')}{TOKEN_PATH}"


# --- client authentication ----------------------------------------------------


def _algorithm_for(key: Any) -> str | None:
    """The one algorithm a key may verify with, decided by its type."""
    if isinstance(key, rsa.RSAPublicKey):
        return "RS256"
    if isinstance(key, ec.EllipticCurvePublicKey) and isinstance(
        key.curve, ec.SECP256R1
    ):
        return "ES256"
    return None


def _numeric_date(claims: Mapping[str, Any], name: str) -> float:
    value = claims.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid_client(f"{name} must be a NumericDate")
    return float(value)


async def verify_client_assertion(
    session: AsyncSession,
    *,
    assertion_type: str | None,
    assertion: str | None,
    client_id: str | None = None,
    now: float | None = None,
) -> RegistrationSnapshot:
    """Authenticate the app behind a client assertion, and spend the assertion.

    Returns the registration it verified against. Raises :class:`OAuthError`
    (``invalid_client``) on any failure.

    The registration, its key and the key's algorithm come from rows, never from
    the assertion's own say-so: ``iss`` selects the registration, ``kid`` the key
    in its set, and the key's type the algorithm. The ``jti`` is recorded in the
    same statement that confirms the registration is still enabled, and a
    second presentation meets the primary key.
    """
    if assertion_type != ASSERTION_TYPE or not assertion:
        raise _invalid_client("a jwt-bearer client assertion is required")

    try:
        header = jwt.get_unverified_header(assertion)
        unverified = jwt.decode(assertion, options={"verify_signature": False})
    except jwt.PyJWTError as exc:
        raise _invalid_client("the client assertion is not a JWT") from exc

    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise _invalid_client("the client assertion names no kid")
    issuer = unverified.get("iss")
    if not isinstance(issuer, str) or not issuer:
        raise _invalid_client("the client assertion names no issuer")
    if client_id is not None and client_id != issuer:
        raise _invalid_client("client_id does not match the assertion")

    snapshot = (await registration_lookup.load_registrations()).get(issuer)
    if snapshot is None or not snapshot.enabled:
        raise _invalid_client("unknown client")
    key = snapshot.keys.get(kid)
    if key is None:
        raise _invalid_client("unknown key")
    algorithm = _algorithm_for(key)
    if algorithm is None:
        raise _invalid_client("the key cannot verify a client assertion")
    if header.get("alg") != algorithm:
        raise _invalid_client("the assertion's algorithm does not match its key")

    audience = token_endpoint_url()
    try:
        claims = jwt.decode(
            assertion,
            key,
            algorithms=[algorithm],
            audience=audience,
            issuer=issuer,
            subject=issuer,
            leeway=0,
            options={
                "require": ["iss", "sub", "aud", "jti", "iat", "exp"],
                "strict_aud": True,
                # Checked below with the skew this endpoint allows.
                "verify_iat": False,
            },
        )
    except jwt.PyJWTError as exc:
        raise _invalid_client("the client assertion did not verify") from exc

    if claims.get("aud") != audience:
        raise _invalid_client("the assertion is not for this endpoint")
    current = time.time() if now is None else now
    issued_at = _numeric_date(claims, "iat")
    expires_at = _numeric_date(claims, "exp")
    if issued_at > current + IAT_CLOCK_SKEW_SECONDS:
        raise _invalid_client("the assertion was issued in the future")
    if expires_at <= current:
        raise _invalid_client("the assertion has expired")
    if expires_at <= issued_at:
        raise _invalid_client("the assertion expires before it was issued")
    if expires_at - issued_at > MAX_ASSERTION_LIFETIME_SECONDS:
        raise _invalid_client("the assertion is valid for too long")
    jti = claims.get("jti")
    if not isinstance(jti, str) or not jti or len(jti) > ASSERTION_JTI_MAX_LENGTH:
        raise _invalid_client("the assertion's jti is not usable")

    # One statement: the registration is read fresh (the snapshot may be up to
    # a minute old) and the jti recorded against it. No row back means the
    # registration was switched off, or the jti has been spent.
    spent = (
        await session.exec(
            text(
                "INSERT INTO public.app_assertion_jtis "
                "(registration_id, jti, expires_at) "
                "SELECT r.id, :jti, :expires_at "
                "FROM public.app_service_registrations r "
                "WHERE r.public_id = :public_id AND r.enabled "
                "ON CONFLICT DO NOTHING "
                "RETURNING registration_id"
            ),
            params={
                "jti": jti,
                "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc),
                "public_id": issuer,
            },
        )
    ).first()
    await session.commit()
    if spent is None:
        raise _invalid_client("the assertion was already used")
    return snapshot


# --- grants -------------------------------------------------------------------


@dataclass(frozen=True)
class IssuedToken:
    access_token: str
    expires_in: int
    scope: str


def _initiative_resource(value: str) -> int:
    """The initiative a ``resource`` names, or ``invalid_target``."""
    if not value.startswith(INITIATIVE_RESOURCE_PREFIX):
        raise OAuthError("invalid_target", "resource must name an initiative")
    digits = value[len(INITIATIVE_RESOURCE_PREFIX) :]
    if not digits or not set(digits) <= _DIGITS or len(digits) > 10:
        raise OAuthError("invalid_target", "resource must name an initiative")
    initiative_id = int(digits)
    if initiative_id <= 0 or initiative_id > _MAX_INITIATIVE_ID:
        raise OAuthError("invalid_target", "resource must name an initiative")
    return initiative_id


def _covered(requested: frozenset[str], granted: frozenset[str]) -> bool:
    """Whether every requested scope is within the grant. A written resource
    may be asked for at read."""
    readable, writable = expand(granted)
    wanted_read, wanted_write = expand(requested)
    return wanted_read <= readable and wanted_write <= writable


def _requested_scopes(value: str | None) -> frozenset[str] | None:
    """The scopes a ``scope`` parameter asks for; ``None`` when it asks for
    none in particular."""
    if value is None:
        return None
    requested = frozenset(value.split())
    if not requested:
        return None
    try:
        return validate_scopes(requested)
    except UnknownAppScope as exc:
        raise OAuthError("invalid_scope", f"{exc.scope!r} is not a scope") from exc


_INSTALL_SQL = text(
    "SELECT a.listing_uid, a.enabled, a.granted_scopes, "
    "ARRAY(SELECT p.initiative_id FROM app_placements p "
    "WHERE p.install_id = a.id ORDER BY p.initiative_id) AS placed "
    "FROM guild_apps a WHERE a.id = :install_id"
)


async def _installation_token(
    session: AsyncSession,
    client: RegistrationSnapshot,
    *,
    installation: str,
    scope: str | None,
    resource: str | None,
) -> IssuedToken:
    resolved = await app_refs.resolve_app_guild_ref(ref=installation)
    if resolved is None:
        raise OAuthError("invalid_grant", "unknown installation")
    guild_id, install_id = resolved

    try:
        await set_rls_context(session, guild_id=guild_id)
        row = (
            await session.exec(_INSTALL_SQL, params={"install_id": install_id})
        ).first()
    except DBAPIError as exc:
        # A community that was deleted has no role left to route into.
        await session.rollback()
        raise OAuthError("invalid_grant", "unknown installation") from exc
    finally:
        clear_rls_context(session)
    await session.rollback()

    if (
        row is None
        or client.listing_uid is None
        or row.listing_uid != client.listing_uid
        or not row.enabled
    ):
        raise OAuthError("invalid_grant", "unknown installation")

    # A scope the vocabulary no longer defines is left out rather than sealed:
    # the token could never be used with it.
    granted = frozenset(row.granted_scopes or ()) & frozenset(ALL_SCOPES)
    requested = _requested_scopes(scope)
    if requested is not None and not _covered(requested, granted):
        raise OAuthError("invalid_scope", "a requested scope has not been granted")
    scopes = granted if requested is None else requested

    initiative_id: int | None = None
    if resource is not None:
        initiative_id = _initiative_resource(resource)
        if initiative_id not in set(row.placed or ()):
            raise OAuthError(
                "invalid_target", "the installation is not placed in that initiative"
            )

    token, _exp = seal_install_token(
        guild_id=guild_id,
        install_id=install_id,
        client_id=client.public_id,
        scopes=scopes,
        initiative_id=initiative_id,
    )
    return IssuedToken(
        access_token=token,
        expires_in=ACCESS_TOKEN_LIFETIME_SECONDS,
        scope=" ".join(sorted(scopes)),
    )


async def issue_token(
    session: AsyncSession,
    *,
    grant_type: str | None,
    client_assertion_type: str | None,
    client_assertion: str | None,
    client_id: str | None = None,
    installation: str | None = None,
    scope: str | None = None,
    resource: str | None = None,
) -> IssuedToken:
    """Answer one token request, or raise :class:`OAuthError`."""
    if not grant_type:
        raise OAuthError("invalid_request", "grant_type is required")
    if grant_type == GRANT_JWT_BEARER:
        raise OAuthError("unsupported_grant_type", "member tokens are not issued yet")
    if grant_type != GRANT_CLIENT_CREDENTIALS:
        raise OAuthError("unsupported_grant_type", "unsupported grant_type")

    client = await verify_client_assertion(
        session,
        assertion_type=client_assertion_type,
        assertion=client_assertion,
        client_id=client_id,
    )

    if installation is None:
        if _requested_scopes(scope) is not None:
            raise OAuthError("invalid_scope", "an app token carries no scope")
        if resource is not None:
            raise OAuthError("invalid_target", "an app token names no resource")
        token, _exp = seal_app_token(client_id=client.public_id)
        return IssuedToken(
            access_token=token, expires_in=ACCESS_TOKEN_LIFETIME_SECONDS, scope=""
        )

    if not installation:
        raise OAuthError("invalid_request", "installation is empty")
    return await _installation_token(
        session,
        client,
        installation=installation,
        scope=scope,
        resource=resource,
    )


# --- the app's installs -------------------------------------------------------


@dataclass(frozen=True)
class InstallationListing:
    installation: str
    scopes: list[str]
    initiatives: list[int]


_INSTALLS_SQL = text(
    "SELECT a.id, a.granted_scopes, "
    "ARRAY(SELECT p.initiative_id FROM app_placements p "
    "WHERE p.install_id = a.id ORDER BY p.initiative_id) AS placed "
    "FROM guild_apps a WHERE a.listing_uid = :listing_uid AND a.enabled "
    "ORDER BY a.id"
)


async def list_installations(
    session: AsyncSession, client: RegistrationSnapshot
) -> list[InstallationListing]:
    """Every enabled install of ``client``'s listing, in every community in use.

    There is no cross-community index of installs, so this visits each
    community's schema in turn: one routing and one read per community on this
    deployment, plus a reference lookup per install found. It is paid by an app
    asking which installs it has, not by any request made within one.
    """
    if client.listing_uid is None:
        return []

    guild_ids = (
        await session.exec(
            select(Guild.id)
            .where(Guild.status.in_(LIVE_STATUS_VALUES))
            .order_by(Guild.id)
        )
    ).all()

    vocabulary = frozenset(ALL_SCOPES)
    found: list[tuple[int, int, list[str], list[int]]] = []
    for guild_id in guild_ids:
        try:
            await set_rls_context(session, guild_id=guild_id)
            rows = (
                await session.exec(
                    _INSTALLS_SQL, params={"listing_uid": client.listing_uid}
                )
            ).all()
        except DBAPIError:
            # Deleted between the list and the visit.
            await session.rollback()
            continue
        finally:
            clear_rls_context(session)
        await session.rollback()
        for row in rows:
            found.append(
                (
                    int(guild_id),
                    int(row.id),
                    sorted(set(row.granted_scopes or ()) & vocabulary),
                    [int(i) for i in (row.placed or ())],
                )
            )

    listings: list[InstallationListing] = []
    for guild_id, install_id, scopes_granted, placed in found:
        ref = await app_refs.ensure_app_guild_ref(
            guild_id=guild_id, app_install_id=install_id
        )
        listings.append(
            InstallationListing(
                installation=ref, scopes=scopes_granted, initiatives=placed
            )
        )
    return listings
