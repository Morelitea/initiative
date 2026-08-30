"""Resolving the catalog rows behind an install, for every kind of install.

Installing a dashboard and installing an app ask the catalog the same three
questions — does this listing exist, may it still be installed, and which
version does this build pin — and a second copy of that reasoning is how the two
drift into answering them differently. So there is one resolver, and the caller
says which kind of listing it is expecting.

The request supplies a uid and nothing else that matters: what gets stored comes
from the catalog row. Errors are raised as a plain exception carrying a message
code, so this stays free of any HTTP vocabulary and each router maps it to a
response.
"""

from __future__ import annotations

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import MarketplaceMessages
from app.models.platform.marketplace import (
    MarketplaceListing,
    MarketplaceListingVersion,
)
from app.models.tenant.guild_app import GuildApp
from app.services.marketplace import catalog as catalog_service
from app.services.marketplace import registration_lookup

__all__ = [
    "ListingInstallError",
    "installed_app_uids",
    "listing_is_offered",
    "resolve_listing_install",
]


class ListingInstallError(Exception):
    """A listing that cannot be installed, and why.

    ``code`` is a message code the client localizes; ``not_found`` separates
    "no such listing" (which the caller reports as 404) from the conflicts a
    real listing can be in.
    """

    def __init__(self, code: str, *, not_found: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.not_found = not_found


async def resolve_listing_install(
    session: AsyncSession,
    listing_uid: str,
    *,
    kind: str,
    already_installed: bool = False,
) -> tuple[MarketplaceListing, MarketplaceListingVersion]:
    """The listing and the version to pin, or a reason it cannot be installed.

    A listing of the wrong kind reads as *not found* rather than as a type
    error: a dashboard uid handed to the app installer names nothing that
    installer can install, and saying so any more precisely only describes the
    catalog to someone guessing at it.

    ``already_installed`` is set by the two paths that re-pin something a guild
    already has — the update sweep and the upgrade button. Whether this
    deployment runs an app's service decides whether a guild may *acquire* it;
    an install that exists is the guild's either way, and keeping it on the
    version its publisher currently ships is not a second acquisition.

    The lookup runs on the session the request already has, which holds read
    access to the catalog. For a dashboard an app ships with itself, that
    session is also routed into the guild, which is what lets the check below
    ask whether the guild has the app.
    """
    listing = await catalog_service.get_listing_by_uid(session, listing_uid)
    if listing is None or listing.kind != kind:
        raise ListingInstallError(MarketplaceMessages.LISTING_NOT_FOUND, not_found=True)
    if not listing.available:
        raise ListingInstallError(MarketplaceMessages.LISTING_UNAVAILABLE)
    if not await listing_is_offered(session, listing):
        raise ListingInstallError(MarketplaceMessages.LISTING_NEEDS_APP)
    version = await catalog_service.resolve_installable_version(session, listing)
    if version is None:
        # Either it has published nothing, or its current version needs a newer
        # app. Silently installing an older one would be worse: the guild would
        # get something other than what the listing page showed them.
        raise ListingInstallError(MarketplaceMessages.LISTING_VERSION_INCOMPATIBLE)
    if not already_installed and not await registration_lookup.app_is_offered(
        version.definition
    ):
        # An app whose service this deployment does not run is not in this
        # marketplace at all — browse leaves it out and its page answers 404 —
        # so a uid naming one names nothing to acquire here, and says so with
        # the same answer rather than a second one reachable only by asking
        # directly.
        raise ListingInstallError(MarketplaceMessages.LISTING_NOT_FOUND, not_found=True)
    return listing, version


async def installed_app_uids(session: AsyncSession) -> set[str]:
    """The listing uids of the apps the guild this session is routed to has,
    switched on.

    Reads the guild's own install rows, so the schema boundary is what answers —
    there is no guild id to pass and no chance of asking about the wrong one.

    One helper for both readers of this: browse asks which bundled dashboards
    to offer, and the install asks whether this particular one may be taken. A
    guild holds a handful of apps, so the set is small enough that answering
    both from one query is cheaper than keeping two ways to ask.
    """
    rows = await session.exec(
        select(GuildApp.listing_uid).where(GuildApp.enabled.is_(True))
    )
    return set(rows)


async def listing_is_offered(
    session: AsyncSession, listing: MarketplaceListing
) -> bool:
    """Whether the guild this session is routed to may take this listing.

    One rule today: a dashboard an app ships with itself draws that app's
    widgets, so it is offered where the app is and nowhere else.

    A listing's page asks this and answers 404 for it; the install asks it and
    refuses. The shelf reaches the same answer a page at a time, by filtering on
    the same set of installs. So a guild is told the same thing however it
    arrives at a listing.
    """
    if listing.bundled_with_uid is None:
        return True
    return listing.bundled_with_uid in await installed_app_uids(session)
