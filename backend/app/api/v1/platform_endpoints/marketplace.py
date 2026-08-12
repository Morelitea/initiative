"""Browsing the marketplace.

Platform-addressed on purpose: the marketplace is one shared experience with
globally unique identifiers, so these routes take no guild segment. The catalog
holds catalog metadata only, which is why "which of these do I already have?" is
answered by the guild-scoped tool endpoints and merged in the client.

Read-only. The catalog's only writer is the system engine (boot seeding, and
later the registry refresh); installing writes a guild's own schema through the
tool's endpoints, never here.
"""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from app.api.deps import get_current_active_user, UserSessionDep
from app.core.messages import MarketplaceMessages
from app.models.platform.marketplace import (
    MarketplaceListing,
    MarketplaceListingVersion,
)
from app.models.platform.user import User
from app.schemas.platform.marketplace import (
    ListingKind,
    MarketplaceListingDetail,
    MarketplaceListingPage,
    MarketplaceListingSummary,
    MarketplaceVersionRead,
)
from app.services.marketplace import catalog as catalog_service

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_active_user)]

MAX_PAGE_SIZE = 100


def _version_read(
    version: Optional[MarketplaceListingVersion],
) -> Optional[MarketplaceVersionRead]:
    if version is None:
        return None
    return MarketplaceVersionRead(
        version=version.version,
        release_notes=version.release_notes,
        min_app_version=version.min_app_version,
        published_at=version.published_at,
        compatible=catalog_service.version_is_compatible(version.min_app_version),
    )


def _summary(
    listing: MarketplaceListing,
    latest: Optional[MarketplaceListingVersion],
) -> MarketplaceListingSummary:
    version = _version_read(latest)
    return MarketplaceListingSummary(
        uid=listing.uid,
        public_id=listing.public_id,
        kind=listing.kind,
        source=listing.source,
        name=listing.name,
        publisher=listing.publisher,
        # Attribution travels with the provenance that bounds it: a card, the
        # detail page and the install dialog all answer "who wrote this?" from
        # these two fields together, so neither is served without the other.
        author_name=listing.author_name,
        author_url=listing.author_url,
        author_contact=listing.author_contact,
        description=listing.description,
        avatar_url=listing.avatar_url,
        images=list(listing.images or []),
        installs_count=listing.installs_count or 0,
        available=listing.available,
        latest_version=version,
        # Everything that has to be true for the install button to do anything:
        # still offered, has a version, and that version runs on this build.
        installable=bool(listing.available and version and version.compatible),
        updated_at=listing.updated_at,
    )


@router.get("/listings", response_model=MarketplaceListingPage)
async def list_marketplace_listings(
    session: UserSessionDep,
    current_user: CurrentUser,
    kind: Optional[ListingKind] = Query(default=None),  # type: ignore[valid-type]
    q: Optional[str] = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=MAX_PAGE_SIZE),
) -> MarketplaceListingPage:
    """A page of listings, searchable by name, description, or publisher."""
    listings, total = await catalog_service.list_listings(
        session,
        kind=kind,
        query=q,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    items = []
    for listing in listings:
        latest = await catalog_service.get_listing_version(
            session, listing.latest_version_id
        )
        items.append(_summary(listing, latest))
    return MarketplaceListingPage(items=items, total=total)


async def _detail(session, listing: MarketplaceListing) -> MarketplaceListingDetail:
    latest = await catalog_service.get_listing_version(
        session, listing.latest_version_id
    )
    versions = await catalog_service.listing_versions(session, listing.id)
    summary = _summary(listing, latest)
    return MarketplaceListingDetail(
        **summary.model_dump(),
        long_description=listing.long_description,
        # A preview of what installing would produce. The install path re-reads
        # the catalog itself, so this is display data, not an input.
        definition=dict(latest.definition) if latest else None,
        versions=[read for v in versions if (read := _version_read(v))],
    )


# Declared before ``/listings/{public_id}`` so the literal segment wins: uids and
# public ids are different identifier spaces and a path has to pick one.
@router.get("/listings/by-uid/{uid}", response_model=MarketplaceListingDetail)
async def resolve_marketplace_listing(
    uid: str,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> MarketplaceListingDetail:
    """The listing a code names.

    This is what an installed instance uses to find where it came from: the
    instance stores the uid, and the catalog answers with the listing and the
    version it currently publishes.
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
    session: UserSessionDep,
    current_user: CurrentUser,
) -> MarketplaceListingDetail:
    """One listing, with what it would install and every version it has."""
    listing = await catalog_service.get_listing(session, public_id)
    if listing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=MarketplaceMessages.LISTING_NOT_FOUND,
        )
    return await _detail(session, listing)
