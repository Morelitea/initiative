"""Which entities are ours to put in a file.

A dashboard, or any tool entity, may be *derived from an app* — installed from
the marketplace and carrying its publisher's definition in
``listing_uid``/``definition``. Three sources publish into the catalog
(``marketplace.definitions.LISTING_SOURCES``): ``builtin`` is what this build
ships, while ``operator`` and ``registry`` come from somebody else.

Only ``builtin`` is exported. An entity built on somebody else's app is
restored by installing that app in the destination and letting it produce the
entity again — unpacking a copy of its definition out of an archive would
carry a publisher's work into an instance that never installed it, and pin it
at a version the publisher has no way to update.

An entity with **no** ``listing_uid`` was made by hand, in this community, and
is exported like anything else. That is the common case, and it is why this is
a filter on provenance rather than a switch on the tool.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlmodel.ext.asyncio.session import AsyncSession

# The one catalog source this build publishes itself.
BUILTIN_SOURCE = "builtin"

# The manifest ``skipped`` reason recorded for what this filter removes, so an
# archive states that the entity existed rather than silently omitting it.
THIRD_PARTY_REASON = "third_party_app"


async def builtin_listing_uids(
    session: AsyncSession, uids: Iterable[str | None]
) -> frozenset[str]:
    """Of ``uids``, the ones naming a listing this build ships.

    Reads ``marketplace_listings``, which a guild-routed session may SELECT
    (the catalog is read under a platform tier or a guild role). Anything that
    does not come back — a third-party listing, or a uid whose listing is gone
    — is absent from the result and therefore treated as not exportable.
    """
    from sqlmodel import select

    from app.models.platform.marketplace import MarketplaceListing

    wanted = {uid for uid in uids if uid}
    if not wanted:
        return frozenset()
    rows = await session.exec(
        select(MarketplaceListing.uid).where(
            MarketplaceListing.uid.in_(wanted),
            MarketplaceListing.source == BUILTIN_SOURCE,
        )
    )
    return frozenset(rows)


def is_exportable(listing_uid: str | None, builtin: frozenset[str]) -> bool:
    """True when the entity is hand-made here, or built on a built-in app."""
    return not listing_uid or listing_uid in builtin


__all__ = [
    "BUILTIN_SOURCE",
    "THIRD_PARTY_REASON",
    "builtin_listing_uids",
    "is_exportable",
]
