"""The registration handshake with an external app service.

Two round trips, both outbound, both bounded:

1. ``GET {base_url}/.well-known/initiative-app.json`` — the app describes
   itself. The body is run through the *same* listing validator every other
   ingestion path uses, so a served manifest is held to the vocabulary an
   authored one is, and then hashed. The hash is what the registration keeps:
   a later verification that hashes differently means the app changed what it
   claims, which is an operator decision rather than a silent update.
2. ``POST {base_url}/v1/handshake`` — a random challenge goes out, and
   ``HMAC-SHA256(secret, challenge)`` comes back. Both ends prove they hold the
   same secret and neither transmits it.

Every request goes through :mod:`app.services.safe_http`, which resolves the
host once and connects to the address it validated. ``allow_private`` is set:
an app service is an operator-configured destination and is typically a
container on the deployment's own network. Plain ``http`` remains confined to
those non-public addresses by the target policy itself.

Responses are read as a bounded stream and parsed as JSON only — an app that
answers with something enormous, or with something that is not JSON, is
recorded as unreachable rather than allowed to consume the caller.
"""

from __future__ import annotations

import hashlib
import logging
import hmac
import json
import secrets
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.core.messages import AppServiceMessages
from app.models.platform.app_service_registration import AppServiceStatus
from app.services.marketplace import contract
from app.services.marketplace.definitions import (
    ListingDefinitionError,
    normalize_listing_definition,
)
from app.services.safe_http import build_validated_request
from app.services.webhook_target_url import (
    WebhookTargetUrlError,
    WebhookTargetUrlPrivateError,
)

__all__ = [
    "APP_PROTOCOL_VERSION",
    "HandshakeError",
    "HandshakeResult",
    "manifest_path",
    "canonical_manifest_hash",
    "perform_handshake",
]

#: The wire protocol this build speaks. An app announcing anything else is
#: refused by number rather than guessed at.
APP_PROTOCOL_VERSION = 1

logger = logging.getLogger(__name__)

_MANIFEST_PATH = "/.well-known/initiative-app.json"
_HANDSHAKE_PATH = "/v1/handshake"

#: Response ceilings. A manifest is metadata and artwork paths; a handshake
#: answer is one hex digest. Both are read as a bounded stream.
_MANIFEST_MAX_BYTES = 128 * 1024
_HANDSHAKE_MAX_BYTES = 8 * 1024

#: Per-request budget. Connect and read are capped separately so a service that
#: accepts a connection and then stalls still returns within the budget.
_TIMEOUT = httpx.Timeout(5.0, connect=5.0)

#: Length of the random challenge, in bytes, before hex encoding.
_CHALLENGE_BYTES = 32


class HandshakeError(Exception):
    """A handshake that did not complete.

    ``code`` is the API message code for the operator; ``status`` is the value
    to record on the registration, so a failure is legible on the row without
    re-reading a log.
    """

    def __init__(self, code: str, status: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class HandshakeResult:
    """What a completed handshake establishes about an app service."""

    public_id: str
    listing_uid: Optional[str]
    manifest_hash: str
    protocol_version: int
    manifest: dict[str, Any]
    #: Terms the served definition carried that this build's contract does not
    #: name. Dropped rather than refused — an app may target a newer contract
    #: than the deployment shipped with — so they are reported here instead of
    #: disappearing silently. Empty is the ordinary case.
    discarded: tuple[str, ...] = ()


def manifest_path(base_url: str) -> str:
    """The well-known manifest URL for a registration's base URL."""
    return f"{base_url.rstrip('/')}{_MANIFEST_PATH}"


def _handshake_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}{_HANDSHAKE_PATH}"


def canonical_manifest_hash(manifest: dict[str, Any]) -> str:
    """sha256 over the manifest in canonical form.

    Key order and whitespace are normalized first, so re-serving the same
    content formatted differently is not read as a change.
    """
    canonical = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _read_json(
    method: str,
    url: str,
    *,
    max_bytes: int,
    json_body: Any = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Any:
    """Send one bounded request and return the decoded JSON body.

    Raises :class:`HandshakeError` (``unreachable``) for anything that is not a
    successful JSON response within the size and time budget.
    """

    def _unreachable(detail: str) -> HandshakeError:
        return HandshakeError(
            AppServiceMessages.UNREACHABLE, AppServiceStatus.UNREACHABLE, detail
        )

    try:
        request = await build_validated_request(
            method,
            url,
            headers={"Accept": "application/json"},
            json=json_body,
            allow_private=True,
        )
    except (WebhookTargetUrlError, WebhookTargetUrlPrivateError) as exc:
        raise _unreachable(f"target refused: {exc}") from exc

    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, follow_redirects=False, transport=transport
        ) as client:
            response = await client.send(request, stream=True)
            try:
                if response.status_code >= 400:
                    raise _unreachable(f"{url} answered {response.status_code}")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise _unreachable(f"{url} response exceeded {max_bytes} bytes")
                    chunks.append(chunk)
            finally:
                await response.aclose()
    except httpx.HTTPError as exc:
        raise _unreachable(f"{url} could not be read: {exc}") from exc

    try:
        return json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _unreachable(f"{url} did not answer with JSON") from exc


def _read_manifest_document(document: Any) -> tuple[dict[str, Any], int]:
    """Pull the manifest and protocol version out of the well-known document.

    The document may be the manifest itself with a ``protocol_version`` key, or
    a wrapper carrying ``{protocol_version, manifest}`` — both shapes appear in
    the wild depending on how an app kit serializes, and neither changes what is
    validated.
    """

    def _invalid(detail: str) -> HandshakeError:
        return HandshakeError(
            AppServiceMessages.INVALID_MANIFEST,
            AppServiceStatus.MANIFEST_MISMATCH,
            detail,
        )

    if not isinstance(document, dict):
        raise _invalid("the well-known document must be a JSON object")

    raw_version = document.get("protocol_version")
    inner = document.get("manifest")
    manifest = inner if isinstance(inner, dict) else document
    if isinstance(inner, dict) and raw_version is None:
        raw_version = inner.get("protocol_version")

    if not isinstance(raw_version, int) or isinstance(raw_version, bool):
        raise _invalid("protocol_version must be an integer")
    if raw_version != APP_PROTOCOL_VERSION:
        raise _invalid(
            f"protocol version {raw_version} is not spoken by this build "
            f"(expected {APP_PROTOCOL_VERSION})"
        )
    return manifest, raw_version


def _validate_manifest(
    manifest: dict[str, Any],
) -> tuple[str, Optional[str], tuple[str, ...]]:
    """Check the manifest this build cares about and return what it establishes.

    The kind-specific body goes through ``normalize_listing_definition`` — the
    one validator — so a served definition is held to exactly the vocabulary an
    authored one is. The normalized result is deliberately discarded: publishing
    what an app serves as a catalog listing is a later phase, and this step only
    establishes that the manifest is acceptable and what it hashes to.
    """

    def _invalid(detail: str) -> HandshakeError:
        return HandshakeError(
            AppServiceMessages.INVALID_MANIFEST,
            AppServiceStatus.MANIFEST_MISMATCH,
            detail,
        )

    public_id = manifest.get("public_id")
    if not isinstance(public_id, str) or not public_id.strip():
        raise _invalid("manifest is missing public_id")

    kind = manifest.get("kind")
    if not isinstance(kind, str):
        raise _invalid("manifest is missing kind")

    try:
        normalize_listing_definition(kind, manifest.get("definition"))
    except ListingDefinitionError as exc:
        raise _invalid(f"manifest definition refused: {exc}") from exc

    uid = manifest.get("uid")
    listing_uid = uid.strip() if isinstance(uid, str) and uid.strip() else None
    discarded = tuple(contract.discarded_terms(manifest.get("definition")))
    return public_id.strip(), listing_uid, discarded


def _expected_signature(secret: str, challenge: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), challenge.encode("utf-8"), hashlib.sha256
    ).hexdigest()


async def _run_challenge(
    base_url: str,
    secret: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """Prove both ends hold the same secret, or raise."""
    challenge = secrets.token_hex(_CHALLENGE_BYTES)
    body = await _read_json(
        "POST",
        _handshake_url(base_url),
        max_bytes=_HANDSHAKE_MAX_BYTES,
        json_body={
            "challenge": challenge,
            "protocol_version": APP_PROTOCOL_VERSION,
        },
        transport=transport,
    )

    signature = body.get("signature") if isinstance(body, dict) else None
    if not isinstance(signature, str) or not hmac.compare_digest(
        signature, _expected_signature(secret, challenge)
    ):
        raise HandshakeError(
            AppServiceMessages.SIGNATURE_MISMATCH,
            AppServiceStatus.SIGNATURE_MISMATCH,
            "the app service answered the challenge with a different secret",
        )


def _report_discarded(public_id: str, discarded: tuple[str, ...]) -> None:
    """Say what a served definition carried that this build has no meaning for.

    The contract arrives from the app-kit and a deployment reads the copy it
    shipped with, so an app written against a newer one can serve terms this
    build drops. Dropping them is what lets that app install here at all — but
    dropping them silently leaves the publisher with nothing to see, so the
    registrar says so on every handshake: at registration, and on each sweep.
    """
    if not discarded:
        return
    logger.warning(
        "app service %s served %d term(s) this build does not read: %s "
        "(contract from app-kit %s)",
        public_id,
        len(discarded),
        ", ".join(discarded),
        contract.KIT_VERSION,
    )


async def perform_handshake(
    *,
    base_url: str,
    secret: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> HandshakeResult:
    """Fetch and validate the manifest, then run the challenge.

    ``transport`` is injectable for tests. Raises :class:`HandshakeError` with
    the code and the status to record; returns what the registration should
    store on success.
    """
    document = await _read_json(
        "GET",
        manifest_path(base_url),
        max_bytes=_MANIFEST_MAX_BYTES,
        transport=transport,
    )
    manifest, protocol_version = _read_manifest_document(document)
    public_id, listing_uid, discarded = _validate_manifest(manifest)
    _report_discarded(public_id, discarded)
    await _run_challenge(base_url, secret, transport=transport)
    return HandshakeResult(
        public_id=public_id,
        listing_uid=listing_uid,
        manifest_hash=canonical_manifest_hash(manifest),
        protocol_version=protocol_version,
        manifest=manifest,
        discarded=discarded,
    )
