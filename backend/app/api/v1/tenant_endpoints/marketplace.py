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

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.models.platform.user import User
from app.schemas.platform.marketplace import (
    ListingKind,
    MarketplaceListingPage,
    serialize_listing_summary,
)
from app.services.marketplace import catalog as catalog_service
from app.services.marketplace.installs import installed_app_uids

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
