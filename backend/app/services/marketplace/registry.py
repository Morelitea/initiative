"""The signed-registry client.

A registry is not a service. It is a signed JSON index plus the manifest and
image files that index names by digest, sitting on any static host — object
storage, a CDN, a plain web server. The only code that runs is here, which is
what makes "point a deployment at any registry" real: publishing is putting
signed files somewhere, so a community or a self-hoster can run one with their
own key.

Because the signature covers the index bytes and every artifact is pinned to a
digest recorded in those bytes, the host serving the files is not trusted with
anything. It holds no key, and it cannot change a manifest, swap an image, or
add a listing without the signature failing.

The order of operations is the design:

1. fetch the detached signature document, then the index bytes;
2. verify the signature against **the bytes as they arrived**;
3. only then parse them as JSON.

Nothing in the index is read — not a listing, not an artifact URL — until step
2 has succeeded, so a modified byte anywhere in the document stops the refresh
before any of its content has been looked at. Verifying a re-serialized parse
instead would mean the bytes that were checked and the bytes that were used are
not the same object, which is why the signature is over the raw response and
canonicalization plays no part in the trust path.

On top of the signature the client enforces what a signature alone cannot say:

* **freshness and a monotonic serial**, so a copy of an older index that is
  still perfectly signed is refused rather than rolling the catalog backwards.
  Both are compared against ``marketplace_registry_state``, which is persisted
  precisely so restarting the process does not forget them.
* **publisher namespaces are bound to signing keys.** A key is configured with
  the publisher prefixes it may publish under, so one publisher's key cannot
  produce a listing in another's namespace. ``core.*`` names listings shipped
  in this repository and is never accepted from a registry at all.
* **images are mirrored here.** A listing's stored artwork always points at
  this deployment, so browsing the catalog never makes a request to anybody
  else's host.

Listings land through the same ``upsert_listing`` and the same validator that
boot seeding uses, with ``source="registry"``, and a listing that a newly
verified index no longer carries is withdrawn — kept as a row so a guild that
installed it keeps its app and its provenance, but no longer offered.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy import text as sa_text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import API_V1_STR, settings
from app.core.messages import MarketplaceRegistryMessages as Codes
from app.models.platform.marketplace import MarketplaceListing
from app.models.platform.marketplace_registry import (
    MarketplaceMedia,
    MarketplaceRegistryState,
)
from app.services.marketplace.catalog import (
    CatalogError,
    upsert_listing,
    withdraw_listing,
)
from app.services.marketplace.definitions import (
    ListingDefinitionError,
    normalize_listing_definition,
)
from app.services.safe_http import request_public_target
from app.services.webhook_target_url import (
    WebhookTargetUrlError,
    WebhookTargetUrlPrivateError,
)

logger = logging.getLogger(__name__)

__all__ = [
    "RegistryError",
    "RefreshResult",
    "SkippedListing",
    "TrustedKey",
    "load_trusted_keys",
    "registry_configured",
    "refresh_registry",
    "process_registry_refresh",
    "read_registry_state",
    "media_path",
]

#: The catalog source every listing from here is stored under.
SOURCE = "registry"

#: Reserved for listings shipped in this repository. A registry never holds it,
#: whatever its key is authorized for.
RESERVED_PREFIX = "core"

#: The signature for an index lives beside it, at the same URL plus this
#: suffix — one more static file, no server logic.
SIGNATURE_SUFFIX = ".sig"

#: The only signature algorithm accepted. One algorithm rather than a
#: negotiated set: the publish pipeline is ours to change, and a client that
#: accepts exactly one thing cannot be talked into accepting a weaker one.
SIGNATURE_ALG = "Ed25519"

#: Response ceilings. An index describing hundreds of listings is well under a
#: megabyte; artwork is icons and screenshots.
MAX_SIGNATURE_BYTES = 8 * 1024
MAX_INDEX_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MAX_IMAGE_BYTES = 1024 * 1024

#: Structural ceilings on one index.
MAX_LISTINGS = 500
MAX_IMAGES_PER_LISTING = 8

#: Per-request budget for one fetch.
FETCH_TIMEOUT_SECONDS = 15.0

#: How far ahead of this deployment's clock an index may be dated before it
#: reads as wrong rather than merely fresh.
CLOCK_SKEW_SECONDS = 300

#: The index format this client understands.
SUPPORTED_SCHEMA_VERSION = 1

#: Where mirrored artwork is served from. Same-origin by construction, and
#: addressed by the digest of the bytes, so the URL is stable and cacheable.
MEDIA_URL_PREFIX = f"{API_V1_STR}/marketplace/media/"

#: Image types a listing may carry, each with the leading bytes a file of that
#: type starts with. Raster formats only — the artwork renders in a plain
#: ``<img>`` and carries no document of its own.
_IMAGE_MAGIC: dict[str, tuple[bytes, ...]] = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    # WebP is a RIFF container; the format tag sits at offset 8 and is checked
    # separately below.
    "image/webp": (b"RIFF",),
}

_HEX_DIGITS = frozenset("0123456789abcdef")
_DIGEST_LENGTH = 64


class RegistryError(Exception):
    """A refusal, carrying the message code that names it.

    Raised for anything that stops an index — or one listing in it — from being
    accepted. The code is what an operator sees and what the state row records.
    """

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


# --- trusted keys -----------------------------------------------------------


@dataclass(frozen=True)
class TrustedKey:
    """One key this deployment accepts an index from, and what it may publish."""

    kid: str
    public_key: Ed25519PublicKey
    #: Publisher prefixes this key is authorized for. ``{"*"}`` means any
    #: prefix — the sensible setting for a self-hoster signing their own
    #: catalog with one key.
    prefixes: frozenset[str]

    def may_publish(self, publisher_prefix: str) -> bool:
        return "*" in self.prefixes or publisher_prefix in self.prefixes


def _b64url_decode(value: str, *, field_name: str) -> bytes:
    """Decode unpadded base64url, which is how JWK members and the signature
    are written."""
    if not isinstance(value, str) or not value:
        raise RegistryError(Codes.KEYS_INVALID, f"{field_name} is missing")
    padded = value + "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(padded)
    except (binascii.Error, ValueError) as exc:
        raise RegistryError(
            Codes.KEYS_INVALID, f"{field_name} is not base64url: {exc}"
        ) from exc


def load_trusted_keys(raw: Optional[str]) -> dict[str, TrustedKey]:
    """Parse the configured JWKS document into keys by id.

    The shape is a JWKS so a registry can rotate: several keys are listed at
    once, the publisher starts signing with the new one, and the old one is
    dropped a release later. Each key additionally states the publisher
    prefixes it may publish under, which is what stops a key from being usable
    outside the namespace it was issued for.
    """
    if not raw or not raw.strip():
        raise RegistryError(Codes.KEYS_INVALID, "no key set configured")
    try:
        document = json.loads(raw)
    except ValueError as exc:
        raise RegistryError(Codes.KEYS_INVALID, f"not JSON: {exc}") from exc

    entries: Any
    if isinstance(document, Mapping):
        entries = document.get("keys")
    else:
        entries = document
    if not isinstance(entries, list) or not entries:
        raise RegistryError(Codes.KEYS_INVALID, "no keys in the key set")

    keys: dict[str, TrustedKey] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise RegistryError(Codes.KEYS_INVALID, "a key is not an object")
        if entry.get("kty") != "OKP" or entry.get("crv") != SIGNATURE_ALG:
            raise RegistryError(
                Codes.KEYS_INVALID,
                f"only OKP/{SIGNATURE_ALG} keys are accepted",
            )
        kid = entry.get("kid")
        if not isinstance(kid, str) or not kid or len(kid) > 128:
            raise RegistryError(Codes.KEYS_INVALID, "a key has no usable 'kid'")
        if kid in keys:
            raise RegistryError(Codes.KEYS_INVALID, f"duplicate key id {kid!r}")
        material = _b64url_decode(entry.get("x", ""), field_name=f"key {kid!r} 'x'")
        try:
            public_key = Ed25519PublicKey.from_public_bytes(material)
        except (ValueError, TypeError) as exc:
            raise RegistryError(
                Codes.KEYS_INVALID, f"key {kid!r} is not a usable public key: {exc}"
            ) from exc

        raw_prefixes = entry.get("publisher_prefixes")
        if raw_prefixes is None:
            raise RegistryError(
                Codes.KEYS_INVALID,
                f"key {kid!r} does not say which publishers it may publish for",
            )
        if not isinstance(raw_prefixes, list) or not raw_prefixes:
            raise RegistryError(
                Codes.KEYS_INVALID, f"key {kid!r} publisher_prefixes must be a list"
            )
        prefixes: set[str] = set()
        for prefix in raw_prefixes:
            if not isinstance(prefix, str) or not prefix:
                raise RegistryError(
                    Codes.KEYS_INVALID, f"key {kid!r} has an empty publisher prefix"
                )
            if prefix == RESERVED_PREFIX:
                raise RegistryError(
                    Codes.KEYS_INVALID,
                    f"key {kid!r} claims the reserved {RESERVED_PREFIX!r} prefix",
                )
            prefixes.add(prefix)
        keys[kid] = TrustedKey(
            kid=kid, public_key=public_key, prefixes=frozenset(prefixes)
        )
    return keys


def registry_configured() -> bool:
    """Whether this deployment ingests from a registry at all.

    A URL and a key set are both required, and the operator switch has to be
    on. With any of them missing there is no half-open state: no refresh runs,
    the endpoints answer that it is not configured, and the catalog holds only
    what this build ships.
    """
    return bool(
        settings.MARKETPLACE_REGISTRY_ENABLED
        and settings.MARKETPLACE_REGISTRY_URL
        and settings.MARKETPLACE_REGISTRY_PUBLIC_KEYS
    )


def media_path(digest: str) -> str:
    """The same-origin path a mirrored image is served from."""
    return f"{MEDIA_URL_PREFIX}{digest}"


# --- fetching ---------------------------------------------------------------


async def _fetch(
    url: str,
    *,
    max_bytes: int,
    unreachable_code: str,
    oversize_code: str,
) -> bytes:
    """GET ``url`` through the shared egress layer and return its body.

    The egress layer resolves the host once, connects to the address it
    validated, and does not follow redirects; a registry is an ordinary public
    static host, so private targets are not permitted here. The body is capped:
    anything larger than a registry file has any business being is refused
    rather than kept.
    """
    try:
        response = await request_public_target(
            "GET",
            url,
            headers={"Accept": "application/json, */*"},
            timeout=httpx.Timeout(FETCH_TIMEOUT_SECONDS),
        )
    except (
        httpx.HTTPError,
        WebhookTargetUrlError,
        WebhookTargetUrlPrivateError,
    ) as exc:
        raise RegistryError(unreachable_code, f"{url}: {exc}") from exc
    if response.status_code != 200:
        raise RegistryError(unreachable_code, f"{url} returned {response.status_code}")
    body = response.content
    if len(body) > max_bytes:
        raise RegistryError(
            oversize_code, f"{url} is larger than the {max_bytes}-byte ceiling"
        )
    return body


def _parse_json_object(raw: bytes, *, code: str, what: str) -> dict[str, Any]:
    """Parse bytes as a JSON object and nothing else.

    JSON only, and an object at the top: a document is data to be read, never
    something evaluated, and a bare scalar or array is not the shape any of
    these files take.
    """
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise RegistryError(code, f"{what} is not JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RegistryError(code, f"{what} is not a JSON object")
    return parsed


def _same_origin_url(index_url: str, raw: Any) -> str:
    """Resolve an artifact reference against the index and keep it on the
    registry's own origin.

    Artifacts are named relative to the index, so a registry is a directory of
    files that can be moved or mirrored wholesale. An absolute reference is
    accepted only when it lands on the same scheme, host, and port as the index
    itself, which keeps one refresh talking to exactly one host.
    """
    if not isinstance(raw, str) or not raw:
        raise RegistryError(Codes.ARTIFACT_INVALID, "artifact has no url")
    resolved = httpx.URL(index_url).join(raw)
    index = httpx.URL(index_url)
    if (
        resolved.scheme != index.scheme
        or resolved.host != index.host
        or resolved.port != index.port
    ):
        raise RegistryError(
            Codes.ARTIFACT_INVALID,
            f"{raw!r} is not served by the registry itself",
        )
    return str(resolved)


def _check_digest(data: bytes, spec: Mapping[str, Any], *, what: str) -> str:
    """Confirm downloaded bytes are the ones the signed index named.

    The digest is the whole reason the serving host needs no trust: the index
    is signed, the index says what each file hashes to, and bytes that hash to
    something else are not the file.
    """
    expected = spec.get("sha256")
    if (
        not isinstance(expected, str)
        or len(expected) != _DIGEST_LENGTH
        or any(char not in _HEX_DIGITS for char in expected)
    ):
        raise RegistryError(
            Codes.ARTIFACT_INVALID, f"{what} has no usable sha256 in the index"
        )
    declared_size = spec.get("size")
    if isinstance(declared_size, int) and not isinstance(declared_size, bool):
        if declared_size != len(data):
            raise RegistryError(
                Codes.ARTIFACT_INVALID,
                f"{what} is {len(data)} bytes, the index says {declared_size}",
            )
    actual = hashlib.sha256(data).hexdigest()
    if not hmac.compare_digest(actual, expected):
        raise RegistryError(Codes.ARTIFACT_INVALID, f"{what} does not match its digest")
    return actual


# --- signature --------------------------------------------------------------


def _parse_signature_document(raw: bytes) -> list[tuple[str, bytes]]:
    """Read the detached signature file into ``(kid, signature)`` pairs.

    This document is parsed before anything is verified because it is where
    the signature is. It carries no catalog content — a key id and a signature
    value, nothing that is read into the catalog — so the ordering rule that
    matters, that the index is verified before it is parsed, is untouched.
    """
    document = _parse_json_object(
        raw, code=Codes.INDEX_MALFORMED, what="the signature document"
    )
    entries: Any = document.get("signatures", [document])
    if not isinstance(entries, list) or not entries:
        raise RegistryError(Codes.INDEX_MALFORMED, "the signature document is empty")
    pairs: list[tuple[str, bytes]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise RegistryError(Codes.INDEX_MALFORMED, "a signature is not an object")
        alg = entry.get("alg", SIGNATURE_ALG)
        if alg != SIGNATURE_ALG:
            raise RegistryError(
                Codes.SIGNATURE_INVALID, f"unsupported signature algorithm {alg!r}"
            )
        kid = entry.get("kid")
        if not isinstance(kid, str) or not kid:
            raise RegistryError(Codes.INDEX_MALFORMED, "a signature has no 'kid'")
        value = entry.get("sig")
        if not isinstance(value, str) or not value:
            raise RegistryError(
                Codes.INDEX_MALFORMED, f"signature {kid!r} has no 'sig'"
            )
        padded = value + "=" * (-len(value) % 4)
        try:
            pairs.append((kid, base64.urlsafe_b64decode(padded)))
        except (binascii.Error, ValueError) as exc:
            raise RegistryError(
                Codes.SIGNATURE_INVALID, f"signature {kid!r} is not base64url: {exc}"
            ) from exc
    return pairs


async def _fetch_verified_index(
    index_url: str, keys: Mapping[str, TrustedKey]
) -> tuple[bytes, TrustedKey, str]:
    """Fetch the index and return its bytes only once they verify.

    Returns the raw bytes, the key that signed them, and their digest. Nothing
    in the index has been read at this point — that is the caller's next step,
    and it happens on bytes that are already known to be the publisher's.
    """
    signature_bytes = await _fetch(
        index_url + SIGNATURE_SUFFIX,
        max_bytes=MAX_SIGNATURE_BYTES,
        unreachable_code=Codes.UNREACHABLE,
        oversize_code=Codes.INDEX_TOO_LARGE,
    )
    signatures = _parse_signature_document(signature_bytes)

    index_bytes = await _fetch(
        index_url,
        max_bytes=MAX_INDEX_BYTES,
        unreachable_code=Codes.UNREACHABLE,
        oversize_code=Codes.INDEX_TOO_LARGE,
    )

    for kid, signature in signatures:
        key = keys.get(kid)
        if key is None:
            continue
        try:
            key.public_key.verify(signature, index_bytes)
        except InvalidSignature as exc:
            raise RegistryError(
                Codes.SIGNATURE_INVALID,
                f"the index does not verify against key {kid!r}",
            ) from exc
        return index_bytes, key, hashlib.sha256(index_bytes).hexdigest()

    offered = ", ".join(sorted(kid for kid, _ in signatures)) or "none"
    raise RegistryError(
        Codes.KEY_UNKNOWN, f"the index is signed by untrusted key ids: {offered}"
    )


# --- index shape ------------------------------------------------------------


@dataclass(frozen=True)
class _Index:
    serial: int
    generated_at: datetime
    listings: tuple[Mapping[str, Any], ...]


def _parse_timestamp(value: Any, *, what: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise RegistryError(Codes.INDEX_MALFORMED, f"{what} is missing")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise RegistryError(
            Codes.INDEX_MALFORMED, f"{what} is not a timestamp: {value!r}"
        ) from exc
    if parsed.tzinfo is None:
        raise RegistryError(Codes.INDEX_MALFORMED, f"{what} carries no timezone")
    return parsed.astimezone(timezone.utc)


def _parse_index(index_bytes: bytes) -> _Index:
    """Read verified bytes into the handful of fields an index has."""
    document = _parse_json_object(
        index_bytes, code=Codes.INDEX_MALFORMED, what="the index"
    )
    if document.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        raise RegistryError(
            Codes.INDEX_MALFORMED,
            f"unsupported index schema_version {document.get('schema_version')!r}",
        )
    serial = document.get("serial")
    if not isinstance(serial, int) or isinstance(serial, bool) or serial < 0:
        raise RegistryError(Codes.INDEX_MALFORMED, "serial must be a whole number")
    generated_at = _parse_timestamp(document.get("generated_at"), what="generated_at")

    listings = document.get("listings")
    if not isinstance(listings, list):
        raise RegistryError(Codes.INDEX_MALFORMED, "listings must be a list")
    if len(listings) > MAX_LISTINGS:
        raise RegistryError(
            Codes.INDEX_MALFORMED,
            f"the index carries {len(listings)} listings, more than {MAX_LISTINGS}",
        )
    for entry in listings:
        if not isinstance(entry, Mapping):
            raise RegistryError(
                Codes.INDEX_MALFORMED, "a listing entry is not an object"
            )
    return _Index(
        serial=serial,
        generated_at=generated_at,
        listings=tuple(listings),
    )


def _check_freshness(index: _Index, now: datetime) -> None:
    """Refuse an index that is too old, or dated implausibly far ahead.

    A signature stays valid for as long as the key does, so freshness is the
    part that stops a correctly signed copy from being served forever after the
    publisher moved on.
    """
    max_age = timedelta(seconds=settings.MARKETPLACE_REGISTRY_MAX_AGE_SECONDS)
    age = now - index.generated_at
    if age > max_age:
        raise RegistryError(
            Codes.INDEX_STALE,
            f"the index was generated {int(age.total_seconds())}s ago, "
            f"beyond the {int(max_age.total_seconds())}s window",
        )
    if index.generated_at - now > timedelta(seconds=CLOCK_SKEW_SECONDS):
        raise RegistryError(Codes.INDEX_STALE, "the index is dated in the future")


def _check_serial(
    index: _Index, digest: str, state: Optional[MarketplaceRegistryState]
) -> bool:
    """Compare the index's counter with the last one accepted.

    Returns whether there is new content to ingest. A lower serial is a refusal
    — it is the shape a replaced-by-an-older-copy looks like. The same serial
    carrying different bytes is refused too: a serial names one published
    state, so content changing underneath it is not something to reconcile.
    """
    if state is None or state.last_serial is None:
        return True
    if index.serial < state.last_serial:
        raise RegistryError(
            Codes.SERIAL_REGRESSION,
            f"serial {index.serial} is older than the accepted {state.last_serial}",
        )
    if index.serial > state.last_serial:
        return True
    if digest != state.last_index_sha256:
        raise RegistryError(
            Codes.SERIAL_REGRESSION,
            f"serial {index.serial} was already accepted with different content",
        )
    # Byte-identical to what is already in the catalog. Re-ingest only when the
    # last run left something undone.
    return state.last_error is not None


# --- artwork ----------------------------------------------------------------


def _check_image_bytes(data: bytes, content_type: Any) -> str:
    """Confirm the bytes are an image of the type the signed index declares."""
    if not isinstance(content_type, str) or content_type not in _IMAGE_MAGIC:
        raise RegistryError(
            Codes.ARTIFACT_INVALID, f"unsupported image type {content_type!r}"
        )
    if not any(data.startswith(prefix) for prefix in _IMAGE_MAGIC[content_type]):
        raise RegistryError(Codes.ARTIFACT_INVALID, f"the bytes are not {content_type}")
    if content_type == "image/webp" and data[8:12] != b"WEBP":
        raise RegistryError(Codes.ARTIFACT_INVALID, "the bytes are not image/webp")
    return content_type


async def _mirror_image(
    session: AsyncSession, *, index_url: str, spec: Mapping[str, Any], now: datetime
) -> str:
    """Download one image, check it against the index, and store it here.

    Returns the same-origin path the listing will carry. Storing is keyed on
    the digest, so an image that several listings share, or that survives a
    republish unchanged, is kept once.
    """
    url = _same_origin_url(index_url, spec.get("url"))
    data = await _fetch(
        url,
        max_bytes=MAX_IMAGE_BYTES,
        unreachable_code=Codes.ARTIFACT_UNREACHABLE,
        oversize_code=Codes.ARTIFACT_INVALID,
    )
    digest = _check_digest(data, spec, what=f"image {url}")
    content_type = _check_image_bytes(data, spec.get("content_type"))

    existing = (
        await session.exec(
            select(MarketplaceMedia).where(MarketplaceMedia.sha256 == digest)
        )
    ).first()
    if existing is None:
        session.add(
            MarketplaceMedia(
                sha256=digest,
                content_type=content_type,
                byte_size=len(data),
                data=data,
                source_url=url[:2000],
                created_at=now,
            )
        )
        await session.flush()
    return media_path(digest)


# --- one listing ------------------------------------------------------------


def _publisher_prefix(public_id: str) -> str:
    return public_id.split(".", 1)[0]


async def _ingest_listing(
    session: AsyncSession,
    *,
    entry: Mapping[str, Any],
    index_url: str,
    key: TrustedKey,
    now: datetime,
) -> None:
    """Fetch, check, and upsert one listing the verified index names."""
    public_id = entry.get("public_id")
    uid = entry.get("uid")
    if not isinstance(public_id, str) or not public_id:
        raise RegistryError(Codes.INDEX_MALFORMED, "a listing entry has no public_id")
    if not isinstance(uid, str) or not uid:
        raise RegistryError(Codes.INDEX_MALFORMED, f"{public_id} has no uid")

    prefix = _publisher_prefix(public_id)
    if prefix == RESERVED_PREFIX:
        raise RegistryError(
            Codes.RESERVED_NAMESPACE,
            f"{public_id} is in the namespace reserved for shipped listings",
        )
    if not key.may_publish(prefix):
        raise RegistryError(
            Codes.PUBLISHER_NOT_AUTHORIZED,
            f"key {key.kid!r} may not publish for {prefix!r}",
        )

    manifest_spec = entry.get("manifest")
    if not isinstance(manifest_spec, Mapping):
        raise RegistryError(Codes.INDEX_MALFORMED, f"{public_id} names no manifest")
    manifest_url = _same_origin_url(index_url, manifest_spec.get("url"))
    manifest_bytes = await _fetch(
        manifest_url,
        max_bytes=MAX_MANIFEST_BYTES,
        unreachable_code=Codes.ARTIFACT_UNREACHABLE,
        oversize_code=Codes.ARTIFACT_INVALID,
    )
    _check_digest(manifest_bytes, manifest_spec, what=f"manifest {manifest_url}")
    manifest = _parse_json_object(
        manifest_bytes, code=Codes.ARTIFACT_INVALID, what=f"manifest {manifest_url}"
    )

    # The signed index is what names a listing; the manifest has to agree with
    # it, so identity comes from the document that was verified.
    if manifest.get("uid") != uid or manifest.get("public_id") != public_id:
        raise RegistryError(
            Codes.ARTIFACT_INVALID,
            f"{public_id}: the manifest names a different listing",
        )

    # Validate the body before anything is downloaded for it: a listing the
    # validator will not take is not worth fetching artwork for.
    try:
        normalize_listing_definition(
            str(manifest.get("kind", "")), manifest.get("definition")
        )
    except ListingDefinitionError as exc:
        raise RegistryError(Codes.LISTING_REJECTED, f"{public_id}: {exc}") from exc

    # Artwork comes from the index, never from the manifest. Whatever the
    # manifest says its images are is discarded and replaced with the mirrored
    # copies, so a stored listing always points at this deployment.
    avatar_spec = entry.get("avatar")
    if not isinstance(avatar_spec, Mapping):
        raise RegistryError(
            Codes.ARTIFACT_INVALID, f"{public_id}: the index names no avatar image"
        )
    manifest["avatar_url"] = await _mirror_image(
        session, index_url=index_url, spec=avatar_spec, now=now
    )

    image_specs = entry.get("images") or []
    if not isinstance(image_specs, list):
        raise RegistryError(
            Codes.INDEX_MALFORMED, f"{public_id}: images must be a list"
        )
    if len(image_specs) > MAX_IMAGES_PER_LISTING:
        raise RegistryError(
            Codes.INDEX_MALFORMED,
            f"{public_id} carries more than {MAX_IMAGES_PER_LISTING} images",
        )
    mirrored: list[str] = []
    for spec in image_specs:
        if not isinstance(spec, Mapping):
            raise RegistryError(
                Codes.INDEX_MALFORMED, f"{public_id}: an image entry is not an object"
            )
        mirrored.append(
            await _mirror_image(session, index_url=index_url, spec=spec, now=now)
        )
    manifest["images"] = mirrored

    try:
        await upsert_listing(session, manifest, source=SOURCE)
    except CatalogError as exc:
        raise RegistryError(Codes.LISTING_REJECTED, str(exc)) from exc


# --- state ------------------------------------------------------------------


async def read_registry_state(
    session: AsyncSession, registry_url: Optional[str] = None
) -> Optional[MarketplaceRegistryState]:
    """The bookkeeping row for a registry, or ``None`` before the first run."""
    url = registry_url or settings.MARKETPLACE_REGISTRY_URL
    if not url:
        return None
    return (
        await session.exec(
            select(MarketplaceRegistryState).where(
                MarketplaceRegistryState.registry_url == url
            )
        )
    ).first()


async def _state_row(
    session: AsyncSession, registry_url: str, now: datetime
) -> MarketplaceRegistryState:
    state = await read_registry_state(session, registry_url)
    if state is None:
        state = MarketplaceRegistryState(
            registry_url=registry_url, created_at=now, updated_at=now
        )
        session.add(state)
        await session.flush()
    return state


def _advisory_key(registry_url: str) -> int:
    """A stable 64-bit lock id for one registry URL."""
    digest = hashlib.sha256(f"marketplace-registry:{registry_url}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


async def _claim_refresh(session: AsyncSession, registry_url: str) -> bool:
    """Take the cross-process refresh lock, or report that someone else holds it.

    Transaction-scoped, so it is released by the commit or rollback that ends
    the refresh however that goes. Two replicas polling the same registry on
    the same schedule would otherwise both ingest the same index.
    """
    result = await session.exec(
        sa_text("SELECT pg_try_advisory_xact_lock(:key)"),
        params={"key": _advisory_key(registry_url)},
    )
    return bool(result.one()[0])


# --- the refresh ------------------------------------------------------------


@dataclass(frozen=True)
class SkippedListing:
    """One listing a verified index carried that did not land."""

    public_id: str
    code: str


@dataclass
class RefreshResult:
    """What one refresh did."""

    #: Whether the refresh actually ran (false when unconfigured or already
    #: in flight).
    ran: bool
    #: The refusal that stopped it, or ``None`` when it applied cleanly.
    code: Optional[str] = None
    serial: Optional[int] = None
    key_id: Optional[str] = None
    upserted: int = 0
    withdrawn: int = 0
    #: The index was byte-identical to the one already applied.
    unchanged: bool = False
    skipped: list[SkippedListing] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.ran and self.code is None


#: One refresh at a time inside this process. The cross-process half is the
#: advisory lock above; this one keeps the operator's button and the background
#: worker from running over each other in the same replica.
_refresh_lock = asyncio.Lock()


async def _run_refresh(
    session: AsyncSession, *, registry_url: str, force: bool, now: datetime
) -> RefreshResult:
    keys = load_trusted_keys(settings.MARKETPLACE_REGISTRY_PUBLIC_KEYS)

    if not await _claim_refresh(session, registry_url):
        return RefreshResult(ran=False, code=Codes.REFRESH_IN_PROGRESS)

    state = await _state_row(session, registry_url, now)

    index_bytes, key, digest = await _fetch_verified_index(registry_url, keys)
    index = _parse_index(index_bytes)
    _check_freshness(index, now)
    has_new_content = _check_serial(index, digest, state)

    # ``force`` is the operator's "refresh now": it re-applies an index that
    # is byte-identical to the one already in place. It does not reach the
    # checks above — a stale or rolled-back index is refused for the button
    # exactly as it is for the background run.
    if not has_new_content and not force:
        state.last_fetched_at = now
        state.updated_at = now
        session.add(state)
        return RefreshResult(
            ran=True, serial=index.serial, key_id=key.kid, unchanged=True
        )

    upserted = 0
    skipped: list[SkippedListing] = []
    present: set[str] = set()
    for entry in index.listings:
        public_id = str(entry.get("public_id") or "?")
        uid = entry.get("uid")
        if isinstance(uid, str) and uid:
            # Recorded whatever happens next: a listing the index still carries
            # is not withdrawn just because this deployment could not take it.
            present.add(uid)
        try:
            # Each listing lands inside a savepoint, so one that is refused
            # part-way through leaves nothing of itself behind — not a
            # half-updated row, not the images fetched for it — while the
            # listings already applied in this refresh stay applied.
            async with session.begin_nested():
                await _ingest_listing(
                    session, entry=entry, index_url=registry_url, key=key, now=now
                )
            upserted += 1
        except RegistryError as exc:
            logger.warning(
                "marketplace registry: skipping %s (%s): %s",
                public_id,
                exc.code,
                exc.detail,
            )
            skipped.append(SkippedListing(public_id=public_id, code=exc.code))

    withdrawn = 0
    stale = (
        await session.exec(
            select(MarketplaceListing).where(
                MarketplaceListing.source == SOURCE,
                MarketplaceListing.available.is_(True),
            )
        )
    ).all()
    for listing in stale:
        # A key retires listings only in the namespaces it may publish under.
        # An index signed by one publisher says nothing about another's
        # listings, and reading absence as a retirement would let any
        # authorized key take down every other publisher by leaving them out.
        if not key.may_publish(_publisher_prefix(listing.public_id)):
            continue
        if listing.uid not in present and await withdraw_listing(session, listing.uid):
            withdrawn += 1
            logger.info(
                "marketplace registry: withdrew %s — no longer in the index",
                listing.public_id,
            )

    state.last_fetched_at = now
    state.updated_at = now
    state.key_id = key.kid
    state.last_serial = index.serial
    state.last_index_sha256 = digest
    state.last_generated_at = index.generated_at
    state.listing_count = len(index.listings)
    # A skipped listing leaves the run marked incomplete, which is what makes
    # the next refresh re-ingest this same serial instead of treating it as
    # already applied.
    state.last_error = skipped[0].code if skipped else None
    if not skipped:
        state.last_success_at = now
    session.add(state)

    return RefreshResult(
        ran=True,
        serial=index.serial,
        key_id=key.kid,
        upserted=upserted,
        withdrawn=withdrawn,
        skipped=skipped,
    )


async def _record_failure(
    session: AsyncSession, *, registry_url: str, code: str, now: datetime
) -> None:
    """Note a refusal on the bookkeeping row, leaving the catalog untouched.

    Runs after the refresh transaction was rolled back, so the only thing it
    writes is when the attempt happened and why it stopped.
    """
    try:
        state = await _state_row(session, registry_url, now)
        state.last_fetched_at = now
        state.last_error = code
        state.updated_at = now
        session.add(state)
        await session.commit()
    except Exception:  # pragma: no cover - bookkeeping must not mask the refusal
        await session.rollback()
        logger.exception("marketplace registry: could not record the failed refresh")


async def refresh_registry(
    session: AsyncSession, *, force: bool = False
) -> RefreshResult:
    """Fetch, verify, and apply the configured registry's index.

    The catalog moves as one transaction: either the whole verified index is
    applied and the bookkeeping row moves with it, or nothing is written and
    the catalog stays exactly where it was. A listing the index carries that
    this deployment cannot take is reported as skipped rather than failing the
    refresh, and is not withdrawn — the publisher still lists it.

    ``session`` must be a system-engine session: the catalog has no
    request-path writer.
    """
    if not registry_configured():
        return RefreshResult(ran=False, code=Codes.NOT_CONFIGURED)
    registry_url = str(settings.MARKETPLACE_REGISTRY_URL)

    if _refresh_lock.locked():
        return RefreshResult(ran=False, code=Codes.REFRESH_IN_PROGRESS)

    async with _refresh_lock:
        now = datetime.now(timezone.utc)
        try:
            result = await _run_refresh(
                session, registry_url=registry_url, force=force, now=now
            )
        except RegistryError as exc:
            await session.rollback()
            logger.warning(
                "marketplace registry: refresh refused (%s): %s", exc.code, exc.detail
            )
            await _record_failure(
                session, registry_url=registry_url, code=exc.code, now=now
            )
            return RefreshResult(ran=True, code=exc.code)
        except Exception:
            await session.rollback()
            raise
        await session.commit()
        return result


async def process_registry_refresh() -> None:
    """The background refresh, on its own system-engine session.

    Registered only when a registry is configured, so an install without one
    runs no worker for it at all.
    """
    if not registry_configured():
        return
    from app.db.session import AdminSessionLocal

    async with AdminSessionLocal() as session:
        result = await refresh_registry(session)
    if result.ok and not result.unchanged:
        logger.info(
            "marketplace registry: serial %s applied — %d listing(s), %d withdrawn",
            result.serial,
            result.upserted,
            result.withdrawn,
        )
