"""What one person may dress their profile in.

One function answers it — :func:`owned_decorations` — over two sources: what
ships with the app, which everyone has, and what the account acquired, which is
a row in ``public.user_decorations``. Every caller goes through it, so the
picker offers exactly what the write path accepts.

A pack is an ordinary marketplace listing of kind ``profile_pack``: the ones
that ship with this build differ from a published one only by ``source``, and
what a granted row records is the listing's ``uid`` — the one name that means
this pack on every deployment carrying the catalog.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import delete, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.profile_decorations import SHIPPED_DECORATIONS
from app.models.platform.marketplace import MarketplaceListing
from app.models.platform.user import User
from app.models.platform.user_decoration import UserDecoration
from app.services.marketplace import catalog as catalog_service
from app.schemas.platform.user import OwnedDecoration, ProfileDecorations

#: A ceiling on one read of the shelf. The catalog paginates; this surface does
#: not, because a person's decoration store is not a browsing problem.
_MAX_PACKS = 200


async def _granted_names(session: AsyncSession, sources: set[str]) -> dict[str, str]:
    """``decoration id -> the name its pack gave it``, for these packs.

    A pack from outside this build has no translation here, so the name its
    publisher wrote is the only one there is. One lookup for the packs an
    account holds, rather than one per decoration.
    """
    if not sources:
        return {}
    listings = [
        listing
        for listing in [
            await catalog_service.get_listing_by_uid(session, uid) for uid in sources
        ]
        if listing is not None and listing.kind == "profile_pack"
    ]
    versions = await catalog_service.get_listing_versions(
        session, [listing.latest_version_id for listing in listings]
    )
    names: dict[str, str] = {}
    for listing in listings:
        version = versions.get(listing.latest_version_id)
        definition = (version.definition if version is not None else None) or {}
        for entry in definition.get("decorations", []):
            if isinstance(entry, dict) and entry.get("id") and entry.get("name"):
                names[str(entry["id"])] = str(entry["name"])
    return names


async def owned_decorations(
    session: AsyncSession, user_id: int
) -> list[OwnedDecoration]:
    """Everything this account may wear, shipped first and then acquired.

    Shipped decorations carry no ``source``: nobody granted them, they came
    with the app, and their names are translated in the client. An acquired one
    carries the uid of the pack that granted it and the name that pack gave it.

    An acquired row naming an id that also ships is dropped rather than listed
    twice — you cannot own a thing twice, and a pack that includes a default
    should not make the picker stutter.
    """
    owned = [
        OwnedDecoration(id=decoration_id, kind=kind, name=None, source=None)
        for decoration_id, kind in SHIPPED_DECORATIONS.items()
    ]
    rows = (
        await session.exec(
            select(UserDecoration)
            .where(UserDecoration.user_id == user_id)
            .order_by(
                UserDecoration.acquired_at.asc(), UserDecoration.decoration_id.asc()
            )
        )
    ).all()
    granted = [row for row in rows if row.decoration_id not in SHIPPED_DECORATIONS]
    names = await _granted_names(session, {row.source for row in granted if row.source})
    owned.extend(
        OwnedDecoration(
            id=row.decoration_id,
            kind=row.kind,
            name=names.get(row.decoration_id),
            source=row.source,
        )
        for row in granted
    )
    return owned


async def owned_kinds(session: AsyncSession, user_id: int) -> dict[str, str]:
    """``id -> slot`` for everything this account may wear.

    The shape the write path checks against: an id has to be here, and it has
    to be here as the slot it is being put in.
    """
    return {item.id: item.kind for item in await owned_decorations(session, user_id)}


def unwearable(wanted: Iterable[tuple[str, str]], owned: dict[str, str]) -> list[str]:
    """Which of these ``(id, slot)`` pairs this library does not answer for.

    Both failures land here: an id the account does not have, and one it has
    in a different slot — a badge cannot be worn as a frame.
    """
    return [
        decoration_id
        for decoration_id, kind in wanted
        if owned.get(decoration_id) != kind
    ]


@dataclass(frozen=True)
class Pack:
    """A profile pack, as the install path needs it.

    A listing plus the decorations its published version grants. The listing is
    the identity — ``uid`` is what a granted row records, because it is the one
    name for this pack on every deployment that carries the catalog.
    """

    listing: MarketplaceListing
    decorations: dict[str, str]

    @property
    def uid(self) -> str:
        return self.listing.uid


def _decorations_of(version) -> dict[str, str]:
    """``id -> slot`` from a published version's definition."""
    definition = (version.definition if version is not None else None) or {}
    return {
        str(entry["id"]): str(entry["slot"])
        for entry in definition.get("decorations", [])
        if isinstance(entry, dict) and "id" in entry and "slot" in entry
    }


async def available_packs(session: AsyncSession) -> list[Pack]:
    """Every profile pack this deployment offers, with what each one grants.

    Read from the catalog rather than a list in this repository: a pack is an
    ordinary listing, and the ones that ship with the build differ from a
    published one only by ``source``.
    """
    listings, _total = await catalog_service.list_listings(
        session, kind="profile_pack", limit=_MAX_PACKS
    )
    versions = await catalog_service.get_listing_versions(
        session, [listing.latest_version_id for listing in listings]
    )
    packs = []
    for listing in listings:
        version = versions.get(listing.latest_version_id)
        decorations = _decorations_of(version)
        # A listing whose published version grants nothing is not offered:
        # there would be nothing to take.
        if decorations:
            packs.append(Pack(listing=listing, decorations=decorations))
    return packs


async def pack_by_uid(session: AsyncSession, uid: str) -> Pack | None:
    """One pack, by the uid a granted row records."""
    listing = await catalog_service.get_listing_by_uid(session, uid)
    if listing is None or listing.kind != "profile_pack" or not listing.available:
        return None
    version = await catalog_service.get_listing_version(
        session, listing.latest_version_id
    )
    decorations = _decorations_of(version)
    return Pack(listing=listing, decorations=decorations) if decorations else None


async def installed_pack_ids(session: AsyncSession, user_id: int) -> set[str]:
    """Which packs this account has, by listing uid. A pack is installed when
    its rows are there, so nothing else records it."""
    sources = (
        await session.exec(
            select(UserDecoration.source).where(
                UserDecoration.user_id == user_id,
                UserDecoration.source.is_not(None),
            )
        )
    ).all()
    return {source for source in sources if source}


async def install_pack(session: AsyncSession, *, user_id: int, pack: Pack) -> None:
    """Put a pack's decorations in this account's library.

    One statement, and it is the insert: reading first and then inserting what
    was missing is two steps that two requests can interleave, and both would
    conclude the same row was missing. ``ON CONFLICT DO NOTHING`` lets the
    primary key settle it instead, so a double click is idempotent rather than
    a race.

    Runs on the system engine — the request path reads its library and never
    writes it.
    """
    rows = [
        {
            "user_id": user_id,
            "decoration_id": decoration_id,
            "kind": kind,
            "source": pack.uid,
            "acquired_at": datetime.now(timezone.utc),
        }
        for decoration_id, kind in pack.decorations.items()
    ]
    await session.exec(
        pg_insert(UserDecoration)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["user_id", "decoration_id"])
    )


async def remove_pack(
    session: AsyncSession,
    *,
    user_id: int,
    pack: Pack,
) -> ProfileDecorations:
    """Take a pack out of a library, and off the profile, in one transaction.

    Both halves or neither. A library emptied without the profile being
    undressed leaves the account wearing what it does not have, which the
    write path would refuse on the next unrelated edit — so the two are one
    statement pair the caller commits once, rather than two commits with a
    window between them.

    What is being worn is read **here, under a row lock**, not passed in.
    Undressing is a read-modify-write of one JSONB value, so the read and the
    write belong to the same transaction: the lock makes concurrent writers of
    that column take turns, and an edit either lands first and is read, or
    waits and is applied to the stripped value.

    The delete is scoped to rows this pack granted: a decoration that arrived
    from somewhere else and happens to share an id is not this pack's to
    remove. Returns what the profile is left wearing.
    """
    worn_raw = (
        await session.exec(
            select(User.profile_decorations).where(User.id == user_id).with_for_update()
        )
    ).first()
    worn = ProfileDecorations.model_validate(worn_raw or {})

    await session.exec(
        delete(UserDecoration).where(
            UserDecoration.user_id == user_id,
            UserDecoration.source == pack.uid,
        )
    )
    stripped = undress(worn, pack)
    if stripped != worn:
        await session.exec(
            update(User)
            .where(User.id == user_id)
            .values(
                profile_decorations=stripped.model_dump(),
                updated_at=datetime.now(timezone.utc),
            )
        )
    return stripped


def undress(worn: ProfileDecorations, gone: Pack) -> ProfileDecorations:
    """The same look with anything from ``gone`` taken off.

    Removing a pack has to take its pieces off the profile as well as out of
    the library, or the profile would go on wearing something the account no
    longer has — which the write path would then refuse to save on the next
    unrelated edit.
    """
    return ProfileDecorations(
        banner=None if worn.banner in gone.decorations else worn.banner,
        frame=None if worn.frame in gone.decorations else worn.frame,
        badges=[badge for badge in worn.badges if badge not in gone.decorations],
    )
