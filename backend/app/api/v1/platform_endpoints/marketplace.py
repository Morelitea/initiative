"""Browsing the marketplace.

Platform-addressed on purpose: the marketplace is one shared experience with
globally unique identifiers, so these routes take no guild segment. The catalog
holds catalog metadata only, which is why "which of these do I already have?" is
answered by the guild-scoped tool endpoints and merged in the client.

Browsing is read-only. The catalog's only writer is the system engine (boot
seeding, the operator's own catalog directory, and the registry refresh);
installing writes a guild's own schema through the tool's endpoints, never here.

What this deployment *carries* is narrower than what its catalog holds. An app
is realized by a service the operator runs, so a listing for one is offered only
where that service is registered and switched on: browse leaves the rest out and
these routes answer 404 for them, which is the same answer the install gives.

Two write routes and one public one live on this surface: the operator's rescan
of their catalog directory, their "refresh now" for the signed registry — both
gated on the capability that governs deployment configuration, because that is
what publishing a listing is — and the mirrored artwork a registry's listings
are served from.
"""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_current_active_user, SessionDep, UserSessionDep
from app.api.v1.platform_endpoints.admin import ConfigManageDep
from app.core.config import settings
from app.core.messages import MarketplaceMessages, MarketplaceRegistryMessages
from app.db.session import get_admin_session
from app.models.platform.marketplace import (
    MarketplaceListing,
    MarketplaceListingVersion,
)
from app.models.platform.marketplace_registry import MarketplaceMedia
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
from app.schemas.platform.marketplace_registry import (
    RegistryRefreshRead,
    RegistrySkippedListing,
    RegistryStatusRead,
)
from app.services.marketplace import catalog as catalog_service
from app.services.marketplace import registration_lookup
from app.services.marketplace import registry as registry_service
from app.services.marketplace import operator_catalog as operator_catalog_service

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_active_user)]
AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]

MAX_PAGE_SIZE = 100

#: A mirrored image is addressed by the hex SHA-256 of its own bytes.
_DIGEST_LENGTH = 64
_HEX_DIGITS = frozenset("0123456789abcdef")


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
    if not await registration_lookup.app_is_offered(
        latest.definition if latest else None
    ):
        # The same answer browse gives by leaving it out. A catalog is
        # published to every deployment; running the service behind an app is
        # what makes this one carry it, so until an operator has wired that up
        # there is nothing here to read or install.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=MarketplaceMessages.LISTING_NOT_FOUND,
        )
    summary = _summary(listing, latest)
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


# --- mirrored listing artwork ------------------------------------------------


@router.get("/media/{digest}", include_in_schema=False)
async def read_marketplace_media(digest: str, session: SessionDep) -> Response:
    """Serve one mirrored listing image.

    These bytes stand in for the image files this build ships under
    ``/marketplace/``, and are served the same way: no session required, and
    the same for everyone. They are catalog artwork — a listing's icon and
    screenshots — and carry nothing about any guild.

    Addressed by the digest of the bytes, so the content at a URL never
    changes and the response can be cached indefinitely. The content type is
    the one recorded when the image was mirrored, which came from the signed
    index rather than from the host that served it.
    """
    if len(digest) != _DIGEST_LENGTH or any(c not in _HEX_DIGITS for c in digest):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=MarketplaceMessages.MEDIA_NOT_FOUND,
        )
    media = (
        await session.exec(
            select(MarketplaceMedia).where(MarketplaceMedia.sha256 == digest)
        )
    ).first()
    if media is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=MarketplaceMessages.MEDIA_NOT_FOUND,
        )
    return Response(
        content=media.data,
        media_type=media.content_type,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


# --- the signed registry (operator) -----------------------------------------


def _refresh_read(result: registry_service.RefreshResult) -> RegistryRefreshRead:
    return RegistryRefreshRead(
        serial=result.serial,
        key_id=result.key_id,
        upserted=result.upserted,
        withdrawn=result.withdrawn,
        unchanged=result.unchanged,
        skipped=[
            RegistrySkippedListing(public_id=item.public_id, code=item.code)
            for item in result.skipped
        ],
    )


@router.get("/registry/status", response_model=RegistryStatusRead)
async def read_registry_status(
    session: AdminSessionDep, current_user: ConfigManageDep
) -> RegistryStatusRead:
    """Where this deployment stands with its configured registry.

    Answers "is anything coming from a registry, and did the last refresh
    work". With no registry configured every field is empty — the feature is
    absent rather than idle.
    """
    if not registry_service.registry_configured():
        return RegistryStatusRead(configured=False)
    state = await registry_service.read_registry_state(session)
    if state is None:
        return RegistryStatusRead(
            configured=True, registry_url=settings.MARKETPLACE_REGISTRY_URL
        )
    return RegistryStatusRead(
        configured=True,
        registry_url=state.registry_url,
        key_id=state.key_id,
        last_serial=state.last_serial,
        last_generated_at=state.last_generated_at,
        last_fetched_at=state.last_fetched_at,
        last_success_at=state.last_success_at,
        last_error=state.last_error,
        listing_count=state.listing_count,
    )


@router.post("/registry/refresh", response_model=RegistryRefreshRead)
async def refresh_registry_now(
    session: AdminSessionDep, current_user: ConfigManageDep
) -> RegistryRefreshRead:
    """Fetch and apply the registry index now.

    The same code path the background refresh runs, so there is one set of
    checks rather than a shortcut for the button. A refresh already in flight
    is reported rather than queued, and a refusal answers with the code naming
    it so the reason is legible instead of "it didn't work".
    """
    result = await registry_service.refresh_registry(session, force=True)
    if result.code == MarketplaceRegistryMessages.NOT_CONFIGURED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=result.code
        )
    if result.code == MarketplaceRegistryMessages.REFRESH_IN_PROGRESS:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result.code)
    if result.code is not None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=result.code)
    return _refresh_read(result)
