"""Authenticating an app service calling back into Initiative.

An app holds one thing: the shared secret its registration was wired with. Every
call it makes carries a signature computed from that secret over the request's
method, path, timestamp, nonce, and body — so the caller is established by the
signature rather than by anything it says about itself. The ``X-Initiative-App``
header names which registration to check against; it selects a key, and a
request that does not then verify under that key is refused. Nothing downstream
reads an app identity out of a body field.

Three properties the verifier keeps:

* **Signed over the raw bytes, before any parsing.** The body is hashed exactly
  as it arrived, so what was signed and what is acted on cannot differ.
* **Bounded freshness.** A signed timestamp more than
  :data:`SIGNATURE_WINDOW_SECONDS` from now is refused, which is what bounds how
  long the replay guard has to remember anything.
* **One use per nonce.** The (registration, nonce) pair is recorded on first
  presentation and a second one is refused — the same one-shot pattern the
  delegation and billing blocklists use, and rows are pruned by the shared jti
  janitor once their window has passed.

Order matters and is deliberate: shape, then freshness, then the signature, then
the registration's own state, and only then the nonce burn. Nothing is written
on behalf of a caller that has not proved it holds the secret.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.encryption import SALT_APP_SERVICE_SECRET, decrypt_field
from app.core.messages import AppChannelMessages
from app.models.platform.app_service_nonce import AppServiceNonce
from app.models.platform.app_service_registration import AppServiceRegistration

logger = logging.getLogger(__name__)

__all__ = [
    "APP_HEADER",
    "NONCE_HEADER",
    "SIGNATURE_HEADER",
    "SIGNATURE_WINDOW_SECONDS",
    "TIMESTAMP_HEADER",
    "AppChannelAuthError",
    "CallingApp",
    "SignedEnvelope",
    "app_channel_possible",
    "authenticate_caller",
    "read_envelope",
    "sign_request",
    "signing_material",
]

#: Names the registration whose secret the signature should verify under. A
#: selector, not a claim: the request still has to verify under that key.
APP_HEADER = "X-Initiative-App"
#: Unix seconds at which the caller signed.
TIMESTAMP_HEADER = "X-Initiative-Timestamp"
#: A value the caller does not repeat. Spent once, then refused.
NONCE_HEADER = "X-Initiative-Nonce"
#: ``sha256=<hex>``, matching the shape the outbound webhook dispatcher uses.
SIGNATURE_HEADER = "X-Initiative-Signature"

#: How far a signed timestamp may sit from now, in either direction. Five
#: minutes is the same allowance the outbound dispatcher documents for its own
#: receivers and the billing envelope defaults to: wide enough for ordinary
#: clock drift between two containers, narrow enough that the replay guard only
#: has to remember a few minutes of traffic.
SIGNATURE_WINDOW_SECONDS = 300

#: What the nonce column stores. Checked while verifying so an oversized value
#: is a clean refusal rather than an error at the insert.
MAX_NONCE_LENGTH = 64
#: An app id longer than the column it would be matched against cannot name a
#: registration, so it is refused without a query.
MAX_APP_ID_LENGTH = 120
_SIGNATURE_PREFIX = "sha256="


class AppChannelAuthError(Exception):
    """The call did not authenticate. ``code`` is the message code the endpoint
    surfaces, ``status_code`` the HTTP answer it belongs to."""

    def __init__(self, code: str, status_code: int = 401) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class SignedEnvelope:
    """What the headers claimed, after shape and freshness checks."""

    public_id: str
    timestamp: int
    nonce: str
    signature: str


@dataclass(frozen=True)
class CallingApp:
    """A verified caller: the registration whose secret signed the request."""

    registration: AppServiceRegistration
    nonce: str


def app_channel_possible() -> bool:
    """Whether this deployment can have app services calling in at all.

    Registrations arrive one of two ways — an operator wiring one up (which
    requires the app-platform signing key) or a mounted config file the boot
    reconciler reads. With neither present the table cannot have rows, so the
    channel has nothing to authenticate and its replay guard nothing to hold.
    """
    return bool(
        settings.APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM or settings.APP_SERVICES_CONFIG
    )


def signing_material(
    *, method: str, path: str, timestamp: str, nonce: str, body: bytes
) -> bytes:
    """The bytes both sides run the MAC over.

    Newline-joined fields, ending in a digest of the raw body: the same shape
    the billing envelope uses, with the nonce folded in so the value that makes
    a request one-shot is covered by the signature rather than swappable beside
    it.
    """
    return "\n".join(
        [
            method.upper(),
            path,
            timestamp,
            nonce,
            hashlib.sha256(body).hexdigest(),
        ]
    ).encode("utf-8")


def sign_request(
    secret: str, *, method: str, path: str, timestamp: str, nonce: str, body: bytes
) -> str:
    """The header value a caller holding ``secret`` would send.

    Lives here rather than only in the app-kit so this build can state the
    contract exactly once — the verifier below and the tests both read it.
    """
    digest = hmac.new(
        secret.encode("utf-8"),
        signing_material(
            method=method, path=path, timestamp=timestamp, nonce=nonce, body=body
        ),
        hashlib.sha256,
    ).hexdigest()
    return f"{_SIGNATURE_PREFIX}{digest}"


def read_envelope(headers: Mapping[str, str]) -> SignedEnvelope:
    """Header shape and freshness. Pure — no database, no secrets."""
    public_id = (headers.get(APP_HEADER) or "").strip().lower()
    raw_timestamp = (headers.get(TIMESTAMP_HEADER) or "").strip()
    nonce = (headers.get(NONCE_HEADER) or "").strip()
    signature = (headers.get(SIGNATURE_HEADER) or "").strip().lower()

    if not public_id or not raw_timestamp or not nonce or not signature:
        raise AppChannelAuthError(AppChannelMessages.MISSING_SIGNATURE)
    if len(public_id) > MAX_APP_ID_LENGTH or len(nonce) > MAX_NONCE_LENGTH:
        raise AppChannelAuthError(AppChannelMessages.MISSING_SIGNATURE)
    if not signature.startswith(_SIGNATURE_PREFIX):
        raise AppChannelAuthError(AppChannelMessages.MISSING_SIGNATURE)

    try:
        timestamp = int(raw_timestamp)
    except ValueError as exc:
        raise AppChannelAuthError(AppChannelMessages.STALE_TIMESTAMP) from exc
    if abs(time.time() - timestamp) > SIGNATURE_WINDOW_SECONDS:
        raise AppChannelAuthError(AppChannelMessages.STALE_TIMESTAMP)

    return SignedEnvelope(
        public_id=public_id,
        timestamp=timestamp,
        nonce=nonce,
        signature=signature,
    )


async def _registration_for(
    session: AsyncSession, public_id: str
) -> AppServiceRegistration:
    row = (
        await session.exec(
            select(AppServiceRegistration).where(
                AppServiceRegistration.public_id == public_id
            )
        )
    ).first()
    if row is None:
        raise AppChannelAuthError(AppChannelMessages.UNKNOWN_APP)
    return row


def _registration_secret(row: AppServiceRegistration) -> str:
    if not row.secret_encrypted:
        # A registration with no stored secret has nothing to verify a
        # signature against, so no request can authenticate as it.
        raise AppChannelAuthError(AppChannelMessages.INVALID_SIGNATURE)
    return decrypt_field(row.secret_encrypted, SALT_APP_SERVICE_SECRET)


async def _burn_nonce(
    session: AsyncSession, *, registration_id: int, nonce: str, expires_at: datetime
) -> None:
    """Spend this request's nonce, or refuse a second presentation.

    Committed on its own before the endpoint does any work, so the request is
    consumed whether or not the work that follows succeeds. A retry carries a
    fresh nonce and a fresh timestamp, which is what a caller signs per attempt
    anyway.
    """
    session.add(
        AppServiceNonce(
            registration_id=registration_id,
            nonce=nonce,
            seen_at=datetime.now(timezone.utc),
            expires_at=expires_at,
        )
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise AppChannelAuthError(AppChannelMessages.REPLAYED_REQUEST) from exc


async def authenticate_caller(
    session: AsyncSession,
    *,
    method: str,
    path: str,
    headers: Mapping[str, str],
    body: bytes,
) -> CallingApp:
    """Resolve which app is calling, or refuse.

    Runs on the system engine: ``app_service_registrations`` and the nonce guard
    carry no request-path grant, and this happens before any guild is known.
    """
    envelope = read_envelope(headers)
    registration = await _registration_for(session, envelope.public_id)
    secret = _registration_secret(registration)

    expected = sign_request(
        secret,
        method=method,
        path=path,
        timestamp=str(envelope.timestamp),
        nonce=envelope.nonce,
        body=body,
    )
    if not hmac.compare_digest(expected, envelope.signature):
        raise AppChannelAuthError(AppChannelMessages.INVALID_SIGNATURE)

    if not registration.enabled:
        # The operator's kill switch: every channel this app has stops, and it
        # is a state rather than a failure to authenticate.
        raise AppChannelAuthError(AppChannelMessages.APP_DISABLED, status_code=403)

    await _burn_nonce(
        session,
        registration_id=registration.id,
        nonce=envelope.nonce,
        expires_at=datetime.fromtimestamp(
            envelope.timestamp + SIGNATURE_WINDOW_SECONDS, tz=timezone.utc
        ),
    )
    logger.debug(
        "app channel: authenticated %s for %s %s", registration.public_id, method, path
    )
    return CallingApp(registration=registration, nonce=envelope.nonce)
