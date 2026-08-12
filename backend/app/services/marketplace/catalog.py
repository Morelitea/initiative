"""Reading and populating the marketplace catalog.

Two audiences, and the split between them is the security shape of this module:

* **Readers** — every browse and detail query, and the listing lookup an install
  does. These run on whatever session the request already has (a platform tier,
  or a guild role), and touch nothing but the two catalog tables.
* **The writer** — ``upsert_listing``, called only from the system-engine path
  (boot seeding today, the registry refresh later). No user request reaches it.

Everything a publisher supplies is validated before it lands: the uid's shape,
the ``public_id``'s, the version string's, and the definition's — the last by the
same validator the guild-scoped API uses.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import func, or_, update as sa_update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.version import get_version
from app.models.platform.marketplace import (
    MarketplaceListing,
    MarketplaceListingVersion,
    UID_ALPHABET,
    UID_LENGTH,
)
from app.services.marketplace.definitions import (
    LISTING_KINDS,
    ListingDefinitionError,
    normalize_listing_definition,
)

__all__ = [
    "CatalogError",
    "list_listings",
    "get_listing",
    "get_listing_by_uid",
    "get_listing_version",
    "resolve_installable_version",
    "listing_versions",
    "upsert_listing",
    "bump_installs_count",
    "version_is_compatible",
]

#: Characters a ``public_id`` may use: ``<publisher>.<slug>``, lowercase.
_PUBLIC_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789.-_")
_MAX_PUBLIC_ID = 120
#: Characters a version string may use. Deliberately an explicit set rather than
#: a semver pattern — the catalog stores what the publisher published and only
#: needs it to be a safe, short, comparable token.
_VERSION_CHARS = frozenset("0123456789.-+abcdefghijklmnopqrstuvwxyz")
_MAX_VERSION = 32

_SOURCES = frozenset({"builtin", "registry"})


class CatalogError(ValueError):
    """A listing the catalog will not accept. Raised during seeding/refresh, so
    the message names the problem for whoever is publishing."""


def _check_uid(uid: str) -> str:
    if len(uid) != UID_LENGTH:
        raise CatalogError(f"uid must be {UID_LENGTH} characters, got {len(uid)}")
    for char in uid:
        if char not in UID_ALPHABET:
            raise CatalogError(f"uid contains {char!r}, which is not in the alphabet")
    return uid


def _check_public_id(public_id: str) -> str:
    if not public_id or len(public_id) > _MAX_PUBLIC_ID:
        raise CatalogError("public_id must be 1..120 characters")
    for char in public_id:
        if char not in _PUBLIC_ID_CHARS:
            raise CatalogError(f"public_id contains {char!r}, which is not allowed")
    if "." not in public_id:
        raise CatalogError("public_id must be '<publisher>.<slug>'")
    return public_id


def _check_version(version: str) -> str:
    if not version or len(version) > _MAX_VERSION:
        raise CatalogError("version must be 1..32 characters")
    for char in version:
        if char not in _VERSION_CHARS:
            raise CatalogError(f"version contains {char!r}, which is not allowed")
    return version


def _version_tuple(value: str) -> tuple[int, ...]:
    """A version as comparable integers, ignoring any pre-release suffix.

    Only used to answer "is this deployment new enough", so a coarse reading is
    the right one: `1.2.3-rc1` and `1.2.3` are the same floor.
    """
    head = value.split("-", 1)[0].split("+", 1)[0]
    parts: list[int] = []
    for chunk in head.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            break
    return tuple(parts)


def version_is_compatible(min_app_version: Optional[str]) -> bool:
    """Whether this deployment is new enough to run a listing version.

    A definition can name only what its app build has a renderer for, so a
    version needing a newer app is hidden from browse and refused on install
    rather than landing as a canvas full of error tiles.
    """
    if not min_app_version:
        return True
    return _version_tuple(get_version()) >= _version_tuple(min_app_version)


# --- reads ------------------------------------------------------------------


async def list_listings(
    session: AsyncSession,
    *,
    kind: Optional[str] = None,
    query: Optional[str] = None,
    include_unavailable: bool = False,
    offset: int = 0,
    limit: int = 50,
) -> tuple[Sequence[MarketplaceListing], int]:
    """A page of listings, newest first, with the total that matched."""
    statement = select(MarketplaceListing)
    count_statement = select(func.count()).select_from(MarketplaceListing)

    filters = []
    if not include_unavailable:
        filters.append(MarketplaceListing.available.is_(True))
    if kind:
        filters.append(MarketplaceListing.kind == kind)
    if query:
        # Case-insensitive across the three fields someone would actually type.
        needle = f"%{query.strip()}%"
        filters.append(
            or_(
                MarketplaceListing.name.ilike(needle),
                MarketplaceListing.description.ilike(needle),
                MarketplaceListing.publisher.ilike(needle),
            )
        )
    for condition in filters:
        statement = statement.where(condition)
        count_statement = count_statement.where(condition)

    total = (await session.exec(count_statement)).one()
    statement = statement.order_by(MarketplaceListing.name).offset(offset).limit(limit)
    return (await session.exec(statement)).all(), int(total)


async def get_listing(
    session: AsyncSession, public_id: str
) -> Optional[MarketplaceListing]:
    return (
        await session.exec(
            select(MarketplaceListing).where(MarketplaceListing.public_id == public_id)
        )
    ).first()


async def get_listing_by_uid(
    session: AsyncSession, uid: str
) -> Optional[MarketplaceListing]:
    return (
        await session.exec(
            select(MarketplaceListing).where(MarketplaceListing.uid == uid)
        )
    ).first()


async def get_listing_version(
    session: AsyncSession, version_id: Optional[int]
) -> Optional[MarketplaceListingVersion]:
    if version_id is None:
        return None
    return (
        await session.exec(
            select(MarketplaceListingVersion).where(
                MarketplaceListingVersion.id == version_id
            )
        )
    ).first()


async def resolve_installable_version(
    session: AsyncSession, listing: MarketplaceListing
) -> Optional[MarketplaceListingVersion]:
    """The version a guild would get right now, or ``None`` if there is none it
    can run. A listing whose latest version needs a newer app is not silently
    downgraded to an older one — the guild is told to upgrade instead."""
    version = await get_listing_version(session, listing.latest_version_id)
    if version is None:
        return None
    return version if version_is_compatible(version.min_app_version) else None


# --- writes (system engine only) --------------------------------------------


async def upsert_listing(
    session: AsyncSession,
    manifest: dict[str, Any],
    *,
    source: str,
) -> MarketplaceListing:
    """Create or update one listing and the version its manifest describes.

    Idempotent by ``uid``: re-seeding the same manifest updates metadata in place
    and leaves the version rows alone. Both identities are unique and neither is
    reassignable — a uid already held by a different ``public_id`` is refused,
    and vice versa, so a uid keeps meaning the listing it was first published
    for.
    """
    if source not in _SOURCES:
        raise CatalogError(f"unknown listing source {source!r}")

    uid = _check_uid(str(manifest.get("uid", "")))
    public_id = _check_public_id(str(manifest.get("public_id", "")))
    kind = str(manifest.get("kind", ""))
    if kind not in LISTING_KINDS:
        raise CatalogError(f"unknown listing kind {kind!r}")
    version_str = _check_version(str(manifest.get("version", "")))

    try:
        definition = normalize_listing_definition(kind, manifest.get("definition"))
    except ListingDefinitionError as exc:
        raise CatalogError(f"{public_id}: {exc}") from exc

    for required in ("name", "publisher", "description", "avatar_url"):
        if not manifest.get(required):
            raise CatalogError(f"{public_id}: {required} is required")

    images = manifest.get("images") or []
    if not isinstance(images, list) or any(not isinstance(i, str) for i in images):
        raise CatalogError(f"{public_id}: images must be a list of strings")

    existing = await get_listing_by_uid(session, uid)
    if existing is None:
        # A public_id that exists under a *different* uid is the same conflict
        # from the other side: both identities are unique, and neither may be
        # reassigned by a later publish.
        by_public_id = await get_listing(session, public_id)
        if by_public_id is not None:
            raise CatalogError(
                f"{public_id} is already published under uid {by_public_id.uid}"
            )
    elif existing.public_id != public_id:
        raise CatalogError(
            f"uid {uid} is already held by {existing.public_id}; refusing to reassign"
        )

    now = datetime.now(timezone.utc)
    # Everything a publish sets, whether the row is new or being updated. Built
    # once so a new listing is constructed complete rather than assembled by
    # assignment after the fact.
    published = {
        "kind": kind,
        "source": source,
        "name": str(manifest["name"]),
        "publisher": str(manifest["publisher"]),
        "description": str(manifest["description"]),
        "long_description": manifest.get("long_description"),
        "avatar_url": str(manifest["avatar_url"]),
        "images": list(images),
        "available": True,
        "updated_at": now,
    }
    if existing is None:
        listing = MarketplaceListing(
            uid=uid, public_id=public_id, created_at=now, **published
        )
    else:
        listing = existing
        for field, value in published.items():
            setattr(listing, field, value)
    session.add(listing)
    await session.flush()

    version = (
        await session.exec(
            select(MarketplaceListingVersion).where(
                MarketplaceListingVersion.listing_id == listing.id,
                MarketplaceListingVersion.version == version_str,
            )
        )
    ).first()
    release_notes = manifest.get("release_notes")
    min_app_version = manifest.get("min_app_version")
    if version is None:
        version = MarketplaceListingVersion(
            listing_id=listing.id,
            version=version_str,
            published_at=now,
            definition=definition,
            release_notes=release_notes,
            min_app_version=min_app_version,
        )
        session.add(version)
        await session.flush()
    elif (
        version.definition != definition
        or version.release_notes != release_notes
        or version.min_app_version != min_app_version
    ):
        # A published version is immutable, for two reasons:
        #
        #   * instances *pin* a version, and the upgrade path has nothing to
        #     offer an instance already on this one — so a changed body under an
        #     unchanged version would never reach whoever installed it;
        #   * the catalog is shared, so `uid` + version has to name the same
        #     content on every deployment for a shared code to be meaningful.
        #
        # Correcting a listing means publishing a new version. Its name, blurb
        # and artwork are listing-level and stay editable without one.
        raise CatalogError(
            f"{public_id}: version {version_str} is already published with "
            "different content; publish a new version instead"
        )

    listing.latest_version_id = version.id
    session.add(listing)
    await session.flush()
    return listing


async def listing_versions(
    session: AsyncSession, listing_id: int
) -> Sequence[MarketplaceListingVersion]:
    """Every published version of a listing, newest first."""
    return (
        await session.exec(
            select(MarketplaceListingVersion)
            .where(MarketplaceListingVersion.listing_id == listing_id)
            .order_by(MarketplaceListingVersion.published_at.desc())
        )
    ).all()


async def bump_installs_count(session: AsyncSession, listing_id: int) -> None:
    """Add one to a listing's cumulative install count.

    A number and nothing else: no guild is recorded, so this stays catalog
    telemetry rather than tenant data. Called post-commit and best-effort by the
    install path — a failed bump must never fail an install.
    """
    # One statement, incremented in the database: two installs landing together
    # would otherwise both read the same number and both write it back plus one,
    # quietly losing an install.
    await session.exec(
        sa_update(MarketplaceListing)
        .where(MarketplaceListing.id == listing_id)
        .values(installs_count=MarketplaceListing.installs_count + 1)
    )
