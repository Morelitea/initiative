"""Browsing the marketplace from inside a guild.

The catalog itself is platform data — one shared set of listings with globally
unique ids, and no guild column anywhere in it. Browsing it is nevertheless
guild-addressed, because what is *offered* depends on the guild asking: a
dashboard an app ships with draws that app's widgets, so it appears only where
the app is installed.

That makes the guild a required part of the question rather than a filter the
client applies afterwards, and it puts browse on the same footing as the
install: both run on the guild-routed session, and both read the guild's own
installs through :func:`installed_app_uids`, so a card and the install behind
it always agree.

Reading is all that happens here. Listings are written by the system engine
(boot seeding, the operator's catalog directory, the registry refresh) through
the platform routes; installing writes the guild's own schema through the
tool's endpoints.
"""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.messages import MarketplaceMessages
from app.models.platform.marketplace import MarketplaceListing
from app.models.platform.user import User
from app.schemas.platform.marketplace import (
    ListingKind,
    MarketplaceListingDetail,
    MarketplaceListingPage,
    serialize_listing_summary,
)
from app.services.marketplace import catalog as catalog_service
from app.services.marketplace import registration_lookup
from app.services.marketplace.installs import installed_app_uids, listing_is_offered

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_active_user)]
GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]

MAX_PAGE_SIZE = 100


@router.get("/listings", response_model=MarketplaceListingPage)
async def list_marketplace_listings(
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    kind: Optional[ListingKind] = Query(default=None),  # type: ignore[valid-type]
    q: Optional[str] = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=MAX_PAGE_SIZE),
) -> MarketplaceListingPage:
    """A page of listings this guild can install, searchable by name,
    description, or publisher.

    A guild with none of an app installed sees the same catalog as before —
    the apps themselves, and the dashboards that stand alone.
    """
    listings, total = await catalog_service.list_listings(
        session,
        kind=kind,
        query=q,
        bundled_with=sorted(await installed_app_uids(session)),
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    # One query for the page's versions rather than one per card.
    versions = await catalog_service.get_listing_versions(
        session, [listing.latest_version_id for listing in listings]
    )
    return MarketplaceListingPage(
        items=[
            serialize_listing_summary(listing, versions.get(listing.latest_version_id))
            for listing in listings
        ],
        total=total,
    )


async def _detail(session, listing: MarketplaceListing) -> MarketplaceListingDetail:
    """A listing's page, or the answer the shelf gives by leaving it out.

    Two things put a listing out of reach, and both read as *not found* here
    because both are already true of the shelf: an app whose service this
    deployment does not run, and a dashboard whose app this guild has not
    installed.
    """
    latest = await catalog_service.get_listing_version(
        session, listing.latest_version_id
    )
    offered = await registration_lookup.app_is_offered(
        latest.definition if latest else None
    ) and await listing_is_offered(session, listing)
    if not offered:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=MarketplaceMessages.LISTING_NOT_FOUND,
        )
    summary = serialize_listing_summary(listing, latest)
    return MarketplaceListingDetail(
        **summary.model_dump(),
        long_description=listing.long_description,
        # A preview of what installing would produce. The install path re-reads
        # the catalog itself, so this is display data, not an input.
        definition=dict(latest.definition) if latest else None,
    )


# Declared before ``/listings/{public_id}`` so the literal segment wins: uids and
# public ids are different identifier spaces and a path has to pick one.
@router.get("/listings/by-uid/{uid}", response_model=MarketplaceListingDetail)
async def resolve_marketplace_listing(
    uid: str,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> MarketplaceListingDetail:
    """The listing a code names.

    This is what an installed instance uses to find where it came from: the
    instance stores the uid, and the catalog answers with the listing and the
    version it currently publishes. A listing this guild can no longer take —
    a bundled dashboard whose app it removed — answers 404, which is what
    stops an update being offered that the install would refuse.
    """
    listing = await catalog_service.get_listing_by_uid(session, uid)
    if listing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=MarketplaceMessages.LISTING_NOT_FOUND,
        )
    return await _detail(session, listing)


@router.get("/listings/{public_id}", response_model=MarketplaceListingDetail)
async def read_marketplace_listing(
    public_id: str,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> MarketplaceListingDetail:
    """One listing, with what it would install and every version it has."""
    listing = await catalog_service.get_listing(session, public_id)
    if listing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=MarketplaceMessages.LISTING_NOT_FOUND,
        )
    return await _detail(session, listing)
