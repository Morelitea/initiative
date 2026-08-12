"""Browsing the marketplace.

Platform-addressed on purpose: the marketplace is one shared experience with
globally unique identifiers, so these routes take no guild segment. The catalog
holds catalog metadata only, which is why "which of these do I already have?" is
answered by the guild-scoped tool endpoints and merged in the client.

Browsing is read-only. The catalog's only writer is the system engine (boot
seeding, and later the registry refresh); installing writes a guild's own schema
through the tool's endpoints, never here.

One route writes: the operator's rescan of their own catalog directory. It runs
the boot scan on demand, on the system engine, gated on the capability that
governs deployment configuration — because that is what publishing a listing
from a mounted volume is.
"""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_current_active_user, UserSessionDep
from app.api.v1.platform_endpoints.admin import ConfigManageDep
from app.core.messages import MarketplaceMessages
from app.db.session import get_admin_session
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
    OperatorCatalogProblem,
    OperatorCatalogScanResult,
)
from app.services.marketplace import catalog as catalog_service
from app.services.marketplace import operator_catalog as operator_catalog_service

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_active_user)]
AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]

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


@router.post("/operator-catalog/rescan", response_model=OperatorCatalogScanResult)
async def rescan_operator_catalog(
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> OperatorCatalogScanResult:
    """Re-read the deployment's own catalog directory (``config.manage``).

    The same scan the boot runs, so a manifest dropped into the mounted
    directory appears without a restart, and one removed from it retires its
    listing. Answers 400 when no directory is configured or the configured one
    is not there, and 409 while a scan is already running.
    """
    if operator_catalog_service.operator_catalog_dir() is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=MarketplaceMessages.OPERATOR_CATALOG_NOT_CONFIGURED,
        )
    try:
        scan = await operator_catalog_service.scan_operator_catalog(session)
    except operator_catalog_service.OperatorCatalogScanRunning:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=MarketplaceMessages.OPERATOR_CATALOG_SCAN_RUNNING,
        ) from None
    if scan.directory_missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=MarketplaceMessages.OPERATOR_CATALOG_DIR_MISSING,
        )
    await session.commit()
    return OperatorCatalogScanResult(
        published=scan.published,
        withdrawn=scan.withdrawn,
        skipped=scan.skipped,
        problems=[
            OperatorCatalogProblem(file=problem.file, reason=problem.reason)
            for problem in scan.problems
        ],
    )
