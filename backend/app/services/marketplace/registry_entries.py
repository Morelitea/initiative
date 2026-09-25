"""Applying one verified registry listing to this deployment.

A registry listing is the signed target ``publishers/<prefix>/<uid>/listing.json``
(the entry), beside the files it names: each version's manifest and the
listing's pictures. The TUF client has already verified the entry and checks
every file it fetches here against its own target metadata; this module checks
that the files are the ones the entry names, and turns the entry into rows:

* **a publisher** (``publishers``), matched by prefix, with the display name
  and verified flag from the publisher's record — the target
  ``publishers/<prefix>.json`` the top-level ``targets`` role signs. An
  operator's row for the same prefix wins: the entry is refused and logged.
* **a listing and its versions** (``marketplace_listings``,
  ``marketplace_listing_versions``), ``source='registry'``, through the same
  ``upsert_listing`` and validator every other source uses. A uid or name
  another source already published is refused, never taken over. Pictures are
  kept in ``marketplace_media`` by digest.
* **for an app, a registration** (``app_service_registrations``,
  ``source='registry'``): the listing it speaks for, its keys, its scope
  ceiling (only the scopes this build defines), its reference sectors, and
  either the container image (the operator gives the location) or the hosted
  address. The operator keeps the switch, grants, mandatory flag, origins and a
  container's location; nothing here writes those. An operator's registration
  for the same app wins.

The caller runs each entry in its own savepoint, so a refusal part-way leaves
nothing of that entry behind.

**Withdrawal** (:func:`withdraw_missing`): a listing the repository no longer
carries is marked unavailable and its registration switched off. Nothing is
deleted, so installs keep their data.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Mapping, NamedTuple, Optional

from fastapi import HTTPException
from sqlalchemy import update as sa_update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.app_scopes import ALL_SCOPES
from app.core.audit_events import AuditEventType
from app.core.messages import MarketplaceRegistryMessages as Codes
from app.models.platform.app_service_registration import (
    IMAGE_REFERENCE_MAX_LENGTH,
    REFERENCE_SECTORS,
    AppServiceRegistration,
    RegistrationSource,
)
from app.models.platform.marketplace import (
    UID_ALPHABET,
    UID_LENGTH,
    MarketplaceListing,
    MarketplaceListingVersion,
)
from app.models.platform.marketplace_registry import MarketplaceMedia
from app.models.platform.publisher import (
    FIRST_PARTY_PUBLISHER_PREFIX,
    Publisher,
    PublisherSource,
    publisher_prefix,
)
from app.services import audit as audit_service
from app.services.marketplace import media
from app.services.marketplace import publishers as publishers_service
from app.services.marketplace import registrations as registrations_service
from app.services.marketplace.catalog import (
    DEFAULT_AVATAR_URL,
    REGISTRY_SOURCE,
    CatalogError,
    CatalogSourceConflict,
    upsert_listing,
    withdraw_listing,
)
from app.services.marketplace.definitions import LISTING_KINDS
from app.services.marketplace.registration_lookup import service_public_id

logger = logging.getLogger(__name__)

__all__ = [
    "EntryContext",
    "ListingPath",
    "MAX_PUBLISHER_RECORD_BYTES",
    "RegistryError",
    "UnsupportedEntry",
    "apply_entry",
    "listing_path",
    "parse_listing_path",
    "parse_prefix",
    "publisher_record_path",
    "withdraw_missing",
]

#: The entry format this client reads.
ENTRY_SCHEMA = 1

#: Ceilings on what one entry may name, and on each file.
MAX_ENTRY_BYTES = 256 * 1024
MAX_MANIFEST_BYTES = 512 * 1024
MAX_IMAGE_BYTES = 1024 * 1024
MAX_PUBLISHER_RECORD_BYTES = 16 * 1024
MAX_IMAGES = 12
MAX_VERSIONS = 50

#: ``core`` names listings shipped in this repository and is never a
#: registry publisher.
RESERVED_PREFIX = "core"

_HEX_DIGITS = frozenset("0123456789abcdef")
_DIGEST_LENGTH = 64

#: Characters a path inside a listing's directory may use.
_PATH_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)

#: Characters a container image reference may use (``<repository>@sha256:``).
_IMAGE_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789._/:-@")
_IMAGE_DIGEST_MARK = "@sha256:"


class RegistryError(Exception):
    """A refusal, carrying the message code that names it."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


class UnsupportedEntry(Exception):
    """An entry of a kind this build does not carry. Skipped and logged, and
    not a failure of the refresh: a newer build may carry it."""


class ListingPath(NamedTuple):
    prefix: str
    uid: str


def parse_prefix(value: str) -> Optional[str]:
    """``value`` when it can be a registry publisher's prefix, else ``None``."""
    if value == RESERVED_PREFIX or not publishers_service.valid_prefix(value):
        return None
    return value


def _valid_uid(value: str) -> bool:
    return len(value) == UID_LENGTH and all(char in UID_ALPHABET for char in value)


def listing_path(prefix: str, uid: str) -> str:
    return f"publishers/{prefix}/{uid}/listing.json"


def publisher_record_path(prefix: str) -> str:
    """The publisher's record, signed by the top-level ``targets`` role."""
    return f"publishers/{prefix}.json"


def parse_listing_path(path: str) -> Optional[ListingPath]:
    """The publisher and uid a listing target names, or ``None`` when ``path``
    is not ``publishers/<prefix>/<uid>/listing.json``."""
    parts = path.split("/")
    if len(parts) != 4 or parts[0] != "publishers" or parts[3] != "listing.json":
        return None
    prefix = parse_prefix(parts[1])
    if prefix is None or not _valid_uid(parts[2]):
        return None
    return ListingPath(prefix=prefix, uid=parts[2])


@dataclass(frozen=True)
class EntryContext:
    """What applying an entry needs from the verified repository."""

    #: A target's bytes, checked against its metadata, capped at the size.
    fetch: Callable[[str, int], Awaitable[bytes]]
    #: The bytes of ``publishers/<prefix>.json`` as the top-level role signs
    #: it, or ``None`` when there is no record.
    publisher_record: Callable[[str], Awaitable[Optional[bytes]]]
    #: Whether the repository verified under the root shipped in the image.
    root_is_builtin: bool
    now: datetime


# --- reading the entry ---------------------------------------------------------


def _invalid(detail: str) -> RegistryError:
    return RegistryError(Codes.ENTRY_INVALID, detail)


def _json_object(raw: bytes, *, what: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise _invalid(f"{what} is not JSON") from exc
    if not isinstance(parsed, dict):
        raise _invalid(f"{what} is not a JSON object")
    return parsed


def _digest(value: Any, *, what: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _DIGEST_LENGTH
        or any(char not in _HEX_DIGITS for char in value)
    ):
        raise _invalid(f"{what} has no usable sha256")
    return value


def _matches(data: bytes, expected: str) -> bool:
    return hmac.compare_digest(hashlib.sha256(data).hexdigest(), expected)


def _relative(directory: str, value: Any, *, what: str) -> str:
    """A path inside the listing's directory, as a target path."""
    if not isinstance(value, str) or not value or len(value) > 200:
        raise _invalid(f"{what} has no usable path")
    parts = value.split("/")
    for part in parts:
        if part in ("", ".", "..") or any(char not in _PATH_CHARS for char in part):
            raise _invalid(f"{what} path {value!r} is not a plain relative path")
    return directory + value


def _optional_text(entry: Mapping[str, Any], key: str) -> Optional[str]:
    value = entry.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid(f"{key} must be a string")
    return value


@dataclass(frozen=True)
class _Version:
    version: str
    manifest: str
    sha256: str
    min_app_version: Optional[str]
    release_notes: Optional[str]


def _versions(entry: Mapping[str, Any], directory: str) -> list[_Version]:
    """The entry's versions, oldest first: the last one is the latest."""
    raw = entry.get("versions")
    if not isinstance(raw, list) or not raw:
        raise _invalid("versions must be a non-empty list")
    if len(raw) > MAX_VERSIONS:
        raise _invalid(f"more than {MAX_VERSIONS} versions")
    versions: list[_Version] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            raise _invalid("a version is not an object")
        version = item.get("version")
        if not isinstance(version, str) or not version or version in seen:
            raise _invalid("a version has no usable version string")
        seen.add(version)
        versions.append(
            _Version(
                version=version,
                manifest=_relative(
                    directory, item.get("manifest"), what=f"version {version}"
                ),
                sha256=_digest(item.get("sha256"), what=f"version {version}"),
                min_app_version=_optional_text(item, "min_app_version"),
                release_notes=_optional_text(item, "release_notes"),
            )
        )
    return versions


# --- the publisher ---------------------------------------------------------------


async def _publisher_fields(context: EntryContext, prefix: str) -> tuple[str, bool]:
    """The display name and verified flag the publisher's record gives, or
    the prefix itself, unverified, when the repository carries no record."""
    raw = await context.publisher_record(prefix)
    if raw is None:
        return prefix, False
    record = _json_object(raw, what=f"publisher record {prefix}")
    if record.get("prefix") != prefix:
        raise _invalid(f"publisher record {prefix} names another prefix")
    name = record.get("name")
    try:
        display_name = publishers_service.normalize_display_name(
            name if isinstance(name, str) else ""
        )
    except HTTPException as exc:
        raise _invalid(f"publisher record {prefix} has no usable name") from exc
    return display_name, record.get("verified") is True


async def _apply_publisher(
    session: AsyncSession, context: EntryContext, prefix: str
) -> Publisher:
    display_name, verified = await _publisher_fields(context, prefix)
    row = await publishers_service.publisher_by_prefix(session, prefix)
    if row is not None and row.source == PublisherSource.OPERATOR:
        raise RegistryError(
            Codes.PUBLISHER_CONFLICT,
            f"this deployment's operator added the publisher {prefix!r}",
        )
    if row is None:
        row = Publisher(
            prefix=prefix,
            display_name=display_name,
            verified=verified,
            enabled=True,
            source=PublisherSource.REGISTRY,
        )
        session.add(row)
        await session.flush()
        await audit_service.record(
            session,
            event_type=AuditEventType.APP_PUBLISHER_CREATED,
            actor_user_id=None,
            target_type="app_publisher",
            target_id=row.id,
            detail={
                "via": "registry",
                **audit_service.changed_fields(
                    {},
                    audit_service.snapshot(row, publishers_service.AUDITED_FIELDS),
                ),
            },
        )
        return row

    # The seeded row, or one an earlier refresh added: the registry keeps it
    # up to date. Its switch is the operator's and is left alone.
    before = audit_service.snapshot(row, publishers_service.AUDITED_FIELDS)
    row.display_name = display_name
    row.verified = verified
    row.source = PublisherSource.REGISTRY
    session.add(row)
    changed = audit_service.changed_fields(
        before, audit_service.snapshot(row, publishers_service.AUDITED_FIELDS)
    )
    if changed["changed"]:
        await audit_service.record(
            session,
            event_type=AuditEventType.APP_PUBLISHER_UPDATED,
            actor_user_id=None,
            target_type="app_publisher",
            target_id=row.id,
            detail={"via": "registry", **changed},
        )
    return row


# --- pictures ----------------------------------------------------------------------


async def _keep_picture(
    session: AsyncSession,
    context: EntryContext,
    directory: str,
    spec: Any,
    *,
    what: str,
) -> Optional[str]:
    """Keep one picture the entry names, and return the path it is served
    from; ``None`` for a picture of a type the catalogue does not keep.

    Keyed on the digest the entry gives, so a picture already kept is not
    fetched again.
    """
    if not isinstance(spec, Mapping):
        raise _invalid(f"{what} is not an object")
    target = _relative(directory, spec.get("path"), what=what)
    digest = _digest(spec.get("sha256"), what=what)
    kept = (
        await session.exec(
            select(MarketplaceMedia.id).where(MarketplaceMedia.sha256 == digest)
        )
    ).first()
    if kept is not None:
        return media.media_path(digest)
    data = await context.fetch(target, MAX_IMAGE_BYTES)
    if not _matches(data, digest):
        raise RegistryError(
            Codes.TARGET_REJECTED, f"{target} does not match the sha256 the entry gives"
        )
    content_type = media.image_type_of(data)
    if content_type is None:
        logger.info(
            "marketplace registry: %s is not a picture type the catalogue keeps",
            target,
        )
        return None
    return await media.store_media(
        session, data, content_type=content_type, source_url=target, now=context.now
    )


# --- versions -------------------------------------------------------------------------


def _pack_decorations(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    definition = manifest.get("definition")
    if not isinstance(definition, dict):
        return []
    entries = definition.get("decorations")
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


async def _manifest(
    context: EntryContext,
    version: _Version,
    *,
    uid: str,
    public_id: str,
    kind: str,
) -> dict[str, Any]:
    """One version's manifest, checked against the digest the entry gives
    and against the entry's identity."""
    raw = await context.fetch(version.manifest, MAX_MANIFEST_BYTES)
    if not _matches(raw, version.sha256):
        raise RegistryError(
            Codes.TARGET_REJECTED,
            f"{version.manifest} does not match the sha256 the entry gives",
        )
    manifest = _json_object(raw, what=version.manifest)
    # The entry names the listing; a manifest that says otherwise is not its.
    for key, expected in (("uid", uid), ("public_id", public_id), ("kind", kind)):
        if key in manifest and manifest[key] != expected:
            raise _invalid(f"{version.manifest} names a different {key}")
    if "definition" not in manifest:
        raise _invalid(f"{version.manifest} has no definition")
    return manifest


# --- the registration ------------------------------------------------------------------


def _image_reference(value: Any) -> str:
    """A container image pinned by digest: ``<repository>@sha256:<hex>``."""
    if (
        not isinstance(value, str)
        or not value
        or len(value) > IMAGE_REFERENCE_MAX_LENGTH
        or any(char not in _IMAGE_CHARS for char in value)
        or value.count("@") != 1
    ):
        raise _invalid("the container image is not a usable reference")
    repository, mark, digest = value.partition(_IMAGE_DIGEST_MARK)
    if not repository or not mark:
        raise _invalid("the container image is not pinned by sha256 digest")
    _digest(digest, what="the container image")
    return value


def _vocabulary(values: Any, allowed: frozenset[str], *, what: str) -> list[str]:
    """``values`` ∩ ``allowed``, sorted; anything else is dropped and logged."""
    if values is None:
        return []
    if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
        raise _invalid(f"{what} must be a list of strings")
    kept = sorted({value for value in values if value in allowed})
    dropped = sorted({value for value in values if value not in allowed})
    if dropped:
        logger.warning(
            "marketplace registry: %s drops what this build does not define: %s",
            what,
            ", ".join(dropped),
        )
    return kept


def _normalized(call: Callable[[], Any], *, what: str) -> Any:
    """Run one of the registration validators, as an entry refusal."""
    try:
        return call()
    except HTTPException as exc:
        raise _invalid(f"{what}: {exc.detail}") from exc


async def _apply_registration(
    session: AsyncSession,
    context: EntryContext,
    *,
    spec: Any,
    uid: str,
    prefix: str,
    publisher: Publisher,
    definition: Any,
) -> None:
    if not isinstance(spec, Mapping):
        raise _invalid("registration is not an object")
    publisher_id = publisher.id
    assert publisher_id is not None  # flushed by _apply_publisher
    public_id = service_public_id(definition if isinstance(definition, dict) else None)
    if public_id is None:
        raise _invalid("an app with a registration must be a service app")
    public_id = _normalized(
        lambda: registrations_service.normalize_public_id(public_id),
        what="the service public_id",
    )
    if publisher_prefix(public_id) != prefix:
        raise _invalid("the service is published under another prefix")

    kind = spec.get("kind")
    jwks = _normalized(
        lambda: registrations_service.normalize_jwks(spec.get("jwks")), what="jwks"
    )
    base_url: Optional[str] = None
    embed_origin: Optional[str] = None
    jwks_uri: Optional[str] = None
    image: Optional[str] = None
    if kind == "container":
        if any(spec.get(key) for key in ("base_url", "embed_origin", "jwks_uri")):
            raise _invalid("a container's location is the operator's to give")
        image = _image_reference(spec.get("image"))
    elif kind == "hosted":
        if spec.get("image"):
            raise _invalid("a hosted app names no image")
        base_url = _normalized(
            lambda: registrations_service.normalize_base_url(str(spec.get("base_url"))),
            what="base_url",
        )
        declared_embed = spec.get("embed_origin")
        if declared_embed:
            embed_origin = _normalized(
                lambda: registrations_service.normalize_embed_origin(
                    str(declared_embed)
                ),
                what="embed_origin",
            )
        declared_uri = spec.get("jwks_uri")
        if declared_uri:
            jwks_uri = _normalized(
                lambda: registrations_service.normalize_jwks_uri(
                    str(declared_uri), base_url=str(base_url)
                ),
                what="jwks_uri",
            )
    else:
        raise _invalid("registration.kind must be container or hosted")
    if jwks is None and jwks_uri is None:
        raise _invalid("a registration needs keys")

    ceiling = _vocabulary(
        spec.get("scope_ceiling"), frozenset(ALL_SCOPES), what=f"{public_id} ceiling"
    )
    sectors = _vocabulary(
        spec.get("reference_sectors"),
        REFERENCE_SECTORS,
        what=f"{public_id} reference sectors",
    )
    if sectors and prefix != FIRST_PARTY_PUBLISHER_PREFIX:
        # A sector names one of this deployment's own services, so only this
        # project's own apps are given one.
        logger.warning(
            "marketplace registry: %s is not this project's app; reference "
            "sectors dropped",
            public_id,
        )
        sectors = []

    row = (
        await session.exec(
            select(AppServiceRegistration).where(
                AppServiceRegistration.public_id == public_id
            )
        )
    ).first()
    if row is not None and row.source != RegistrationSource.REGISTRY:
        raise RegistryError(
            Codes.REGISTRATION_CONFLICT,
            f"this deployment's operator registered {public_id}",
        )

    if row is None:
        browser = embed_origin or base_url
        row = AppServiceRegistration(
            public_id=public_id,
            listing_uid=uid,
            publisher_id=publisher_id,
            base_url=base_url,
            embed_origin=embed_origin,
            allowed_origins=(
                registrations_service.normalize_origins(None, browser_base=browser)
                if browser
                else []
            ),
            grants=[],
            jwks=jwks,
            jwks_uri=jwks_uri,
            scope_ceiling=ceiling,
            mandatory=False,
            enabled=True,
            source=RegistrationSource.REGISTRY,
            image_digest=image,
            reference_sectors=sectors,
            root_is_builtin=context.root_is_builtin,
            created_at=context.now,
            updated_at=context.now,
        )
        session.add(row)
        await session.flush()
        await audit_service.record(
            session,
            event_type=AuditEventType.APP_SERVICE_CREATED,
            actor_user_id=None,
            target_type="app_service_registration",
            target_id=row.id,
            detail={
                "via": "registry",
                **audit_service.changed_fields(
                    {},
                    audit_service.snapshot(row, registrations_service.AUDITED_FIELDS),
                ),
            },
        )
        return

    before = audit_service.snapshot(row, registrations_service.AUDITED_FIELDS)
    old_base = registrations_service.row_browser_base(row)
    origins_were_default = (
        list(row.allowed_origins or [])
        == registrations_service.normalize_origins(None, browser_base=old_base)
        if old_base
        else not row.allowed_origins
    )
    row.listing_uid = uid
    row.publisher_id = publisher_id
    row.jwks = jwks
    row.jwks_uri = jwks_uri
    row.scope_ceiling = ceiling
    row.reference_sectors = sectors
    row.root_is_builtin = context.root_is_builtin
    if image is not None:
        if row.image_digest is None:
            # Was hosted, now a container: the hosted address is not where the
            # container runs, so it waits for the operator's location.
            row.base_url = None
            row.embed_origin = None
        row.image_digest = image
    else:
        row.image_digest = None
        row.base_url = base_url
        row.embed_origin = embed_origin
    new_base = registrations_service.row_browser_base(row)
    if origins_were_default:
        row.allowed_origins = (
            registrations_service.normalize_origins(None, browser_base=new_base)
            if new_base
            else []
        )
    row.updated_at = context.now
    session.add(row)
    changed = audit_service.changed_fields(
        before, audit_service.snapshot(row, registrations_service.AUDITED_FIELDS)
    )
    if changed["changed"]:
        await audit_service.record(
            session,
            event_type=AuditEventType.APP_SERVICE_UPDATED,
            actor_user_id=None,
            target_type="app_service_registration",
            target_id=row.id,
            detail={"via": "registry", **changed},
        )


# --- one entry ------------------------------------------------------------------------


async def apply_entry(session: AsyncSession, path: str, context: EntryContext) -> None:
    """Apply the entry at ``path``. Raises ``RegistryError`` to refuse it and
    ``UnsupportedEntry`` for a kind this build does not carry."""
    parsed = parse_listing_path(path)
    if parsed is None:
        raise _invalid(f"{path} is not a listing path")
    prefix, uid = parsed
    directory = f"publishers/{prefix}/{uid}/"

    entry = _json_object(await context.fetch(path, MAX_ENTRY_BYTES), what=path)
    if entry.get("schema") != ENTRY_SCHEMA:
        raise _invalid(f"{path} is not entry schema {ENTRY_SCHEMA}")
    if entry.get("uid") != uid:
        raise _invalid(f"{path} names another uid")
    if entry.get("publisher") != prefix:
        raise _invalid(f"{path} names another publisher")
    public_id = entry.get("public_id")
    if not isinstance(public_id, str) or publisher_prefix(public_id) != prefix:
        raise _invalid(f"{path} has a public_id outside its publisher")
    if prefix == RESERVED_PREFIX:  # pragma: no cover - refused by the path
        raise RegistryError(Codes.RESERVED_NAMESPACE, public_id)
    kind = entry.get("kind")
    if not isinstance(kind, str) or kind not in LISTING_KINDS:
        raise UnsupportedEntry(f"{path} is a {kind!r} listing")
    registration = entry.get("registration")
    if (registration is not None) != (kind == "app"):
        raise _invalid("an app carries a registration, and nothing else does")

    versions = _versions(entry, directory)
    publisher = await _apply_publisher(session, context, prefix)

    avatar_url = DEFAULT_AVATAR_URL
    if entry.get("avatar") is not None:
        avatar_url = (
            await _keep_picture(
                session, context, directory, entry["avatar"], what="avatar"
            )
            or DEFAULT_AVATAR_URL
        )
    image_specs = entry.get("images") or []
    if not isinstance(image_specs, list) or len(image_specs) > MAX_IMAGES:
        raise _invalid(f"images must be a list of at most {MAX_IMAGES}")
    images: list[str] = []
    for index, spec in enumerate(image_specs):
        kept = await _keep_picture(
            session, context, directory, spec, what=f"image {index}"
        )
        if kept is not None:
            images.append(kept)

    held = {
        row
        for row in (
            await session.exec(
                select(MarketplaceListingVersion.version)
                .join(
                    MarketplaceListing,
                    MarketplaceListing.id == MarketplaceListingVersion.listing_id,
                )
                .where(MarketplaceListing.uid == uid)
            )
        ).all()
    }
    listing: Optional[MarketplaceListing] = None
    latest_definition: Any = None
    for index, version in enumerate(versions):
        latest = index == len(versions) - 1
        if version.version in held and not latest:
            # A published version is immutable; there is nothing to read again.
            continue
        manifest = await _manifest(
            context, version, uid=uid, public_id=public_id, kind=kind
        )
        if kind == "profile_pack":
            # A pack's pictures come from its own assets, not from inside the
            # manifest.
            for decoration in _pack_decorations(manifest):
                decoration.pop("image", None)
        published = {
            **manifest,
            "uid": uid,
            "public_id": public_id,
            "kind": kind,
            "name": entry.get("name") or manifest.get("name"),
            "publisher": publisher.display_name,
            "description": entry.get("summary") or manifest.get("description"),
            "long_description": entry.get("description")
            or manifest.get("long_description"),
            "avatar_url": avatar_url,
            "images": images,
            "version": version.version,
            "min_app_version": version.min_app_version,
            "release_notes": version.release_notes,
        }
        try:
            listing = await upsert_listing(session, published, source=REGISTRY_SOURCE)
        except CatalogSourceConflict as exc:
            raise RegistryError(Codes.SOURCE_CONFLICT, str(exc)) from exc
        except CatalogError as exc:
            raise RegistryError(Codes.LISTING_REJECTED, str(exc)) from exc
        if latest:
            latest_definition = published.get("definition")

    assert listing is not None  # the latest version is always published
    listing.publisher_id = publisher.id
    listing.publisher_verified = publisher.verified
    session.add(listing)
    # The dashboards an app bundles are its publish, and share its provenance.
    await session.exec(
        sa_update(MarketplaceListing)
        .where(MarketplaceListing.bundled_with_uid == uid)
        .values(publisher_id=publisher.id, publisher_verified=publisher.verified)
    )
    await session.flush()

    if registration is not None:
        await _apply_registration(
            session,
            context,
            spec=registration,
            uid=uid,
            prefix=prefix,
            publisher=publisher,
            definition=latest_definition,
        )


# --- withdrawal -------------------------------------------------------------------------


async def withdraw_missing(
    session: AsyncSession,
    *,
    present: set[str],
    uncertain: Callable[[str], bool],
    now: datetime,
) -> int:
    """Withdraw what the repository no longer carries. Returns how many
    listings were withdrawn.

    ``present`` is every uid the repository lists; ``uncertain`` says whether a
    listing path falls under a publisher whose role did not load this time, and
    so is unknown rather than gone. Bundled dashboards go with their app.
    """
    withdrawn = 0
    listings = (
        await session.exec(
            select(MarketplaceListing).where(
                MarketplaceListing.source == REGISTRY_SOURCE,
                MarketplaceListing.available.is_(True),
                MarketplaceListing.bundled_with_uid.is_(None),
            )
        )
    ).all()
    for listing in listings:
        if listing.uid in present:
            continue
        if uncertain(listing_path(publisher_prefix(listing.public_id), listing.uid)):
            continue
        if await withdraw_listing(session, listing.uid):
            withdrawn += 1
            logger.info(
                "marketplace registry: withdrew %s — no longer in the repository",
                listing.public_id,
            )

    registrations = (
        await session.exec(
            select(AppServiceRegistration).where(
                AppServiceRegistration.source == RegistrationSource.REGISTRY,
                AppServiceRegistration.enabled.is_(True),
            )
        )
    ).all()
    for row in registrations:
        if row.listing_uid in present:
            continue
        if row.listing_uid is not None and uncertain(
            listing_path(publisher_prefix(row.public_id), row.listing_uid)
        ):
            continue
        before = audit_service.snapshot(row, registrations_service.AUDITED_FIELDS)
        row.enabled = False
        row.updated_at = now
        session.add(row)
        await audit_service.record(
            session,
            event_type=AuditEventType.APP_SERVICE_UPDATED,
            actor_user_id=None,
            target_type="app_service_registration",
            target_id=row.id,
            detail={
                "via": "registry",
                **audit_service.changed_fields(
                    before,
                    audit_service.snapshot(row, registrations_service.AUDITED_FIELDS),
                ),
            },
        )
    await session.flush()
    return withdrawn
