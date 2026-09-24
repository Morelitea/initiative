"""Maintaining the catalog, and serving the artwork it is drawn with.

Reading the marketplace is not here: what a guild is offered depends on which
apps it has installed, so the shelf and a listing's page are guild-addressed
and live in ``tenant_endpoints/marketplace.py``.

What is here is everything that decides *what this deployment carries*, which
is a property of the deployment rather than of any guild. The owner's routes
are gated on the capability that governs deployment configuration — because
that is what publishing a listing is: the rescan of their own catalog
directory, "refresh now" for the signed registry, uploading a listing file,
and reviewing what members share. A member's own routes here are the listings
they shared: reading them, and taking one down. Every write runs on the system
engine; sharing itself starts from inside a community, where the item is read
(``tenant_endpoints/marketplace.py``).

The third route is public: the mirrored artwork a registry's listings are
served from, which is the same bytes for everyone and carries nothing about
any guild.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import SessionDep, UserSessionDep, get_current_active_user
from app.api.v1.platform_endpoints.operator import ConfigManageDep
from app.core.audit_events import AuditEventType
from app.core.config import settings
from app.core.messages import MarketplaceMessages, MarketplaceRegistryMessages
from app.db.session import get_system_session
from app.models.platform.marketplace_registry import MarketplaceMedia
from app.models.platform.user import User
from app.schemas.platform.marketplace import (
    ListingUploadRequest,
    ListingUploadResult,
    MarketplaceLocalSettings,
    MarketplacePendingVersionRead,
    MarketplaceSharedListingRead,
    OperatorCatalogProblem,
    OperatorCatalogScanResult,
    serialize_listing_summary,
)
from app.schemas.platform.marketplace_registry import (
    RegistryRefreshRead,
    RegistrySkippedListing,
    RegistryStatusRead,
)
from app.services import audit as audit_service
from app.services.marketplace import catalog as catalog_service
from app.services.marketplace import local_listings
from app.services.marketplace import registry as registry_service
from app.services.marketplace.catalog import CatalogError
from app.services.platform import app_settings as app_settings_service
from app.services.marketplace import operator_catalog as operator_catalog_service

router = APIRouter()

SystemSessionDep = Annotated[AsyncSession, Depends(get_system_session)]
CurrentUser = Annotated[User, Depends(get_current_active_user)]

#: A mirrored image is addressed by the hex SHA-256 of its own bytes.
_DIGEST_LENGTH = 64
_HEX_DIGITS = frozenset("0123456789abcdef")


@router.post("/operator-catalog/rescan", response_model=OperatorCatalogScanResult)
async def rescan_operator_catalog(
    session: SystemSessionDep,
    owner: ConfigManageDep,
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
    await audit_service.record(
        session,
        event_type=AuditEventType.MARKETPLACE_CATALOG_REFRESHED,
        actor_user_id=owner.id,
        detail={
            "source": "operator_catalog",
            "published": scan.published,
            "withdrawn": scan.withdrawn,
            "skipped": scan.skipped,
        },
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
    session: SystemSessionDep, current_user: ConfigManageDep
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
    session: SystemSessionDep, current_user: ConfigManageDep
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
    # The refresh owns its own transaction, so the record follows it on this
    # session rather than riding the write it describes.
    await audit_service.record(
        session,
        event_type=AuditEventType.MARKETPLACE_CATALOG_REFRESHED,
        actor_user_id=current_user.id,
        detail={
            "source": "registry",
            "published": result.upserted,
            "withdrawn": result.withdrawn,
            "skipped": len(result.skipped),
        },
    )
    await session.commit()
    return _refresh_read(result)


# --- what this deployment adds itself (local) --------------------------------


def _local_error(exc: local_listings.LocalListingError) -> HTTPException:
    return HTTPException(
        status_code=(
            status.HTTP_404_NOT_FOUND if exc.not_found else status.HTTP_409_CONFLICT
        ),
        detail=exc.code,
    )


@router.get("/local/settings", response_model=MarketplaceLocalSettings)
async def read_local_marketplace_settings(
    session: UserSessionDep, _owner: ConfigManageDep
) -> MarketplaceLocalSettings:
    """How this deployment takes its members' shares (``config.manage``)."""
    return MarketplaceLocalSettings(
        members_publish_directly=await app_settings_service.marketplace_members_publish_directly(
            session
        )
    )


@router.put("/local/settings", response_model=MarketplaceLocalSettings)
async def update_local_marketplace_settings(
    payload: MarketplaceLocalSettings,
    session: UserSessionDep,
    owner: ConfigManageDep,
) -> MarketplaceLocalSettings:
    """Let members publish straight to the shelf, or have each share wait for
    review. Changing it moves nothing already waiting."""
    row = await app_settings_service.update_marketplace_settings(
        session,
        members_publish_directly=payload.members_publish_directly,
        actor_user_id=owner.id,
    )
    return MarketplaceLocalSettings(
        members_publish_directly=row.marketplace_members_publish_directly
    )


@router.get("/local/pending", response_model=list[MarketplacePendingVersionRead])
async def list_pending_shares(
    session: SystemSessionDep, _owner: ConfigManageDep
) -> list[MarketplacePendingVersionRead]:
    """Every shared version waiting for review, oldest first, with what it
    would publish — the envelope and its example, as the shelf would carry
    them."""
    return [
        MarketplacePendingVersionRead(
            uid=pending.listing.uid,
            public_id=pending.listing.public_id,
            kind=pending.listing.kind,
            name=pending.listing.name,
            publisher=pending.listing.publisher,
            description=pending.listing.description,
            version=pending.version.version,
            release_notes=pending.version.release_notes,
            submitted_at=pending.version.published_at,
            is_new_listing=pending.listing.latest_version_id is None,
            definition=dict(pending.version.definition or {}),
            example=dict(pending.version.example) if pending.version.example else None,
        )
        for pending in await local_listings.pending_versions(session)
    ]


async def _review(
    session: AsyncSession, owner_id: int, uid: str, version: str, *, approve: bool
) -> None:
    try:
        if approve:
            await local_listings.approve_version(session, uid, version)
        else:
            await local_listings.reject_version(session, uid, version)
    except local_listings.LocalListingError as exc:
        raise _local_error(exc) from exc
    await audit_service.record(
        session,
        event_type=AuditEventType.MARKETPLACE_LISTING_REVIEWED,
        actor_user_id=owner_id,
        detail={
            "listing_uid": uid,
            "version": version,
            "decision": "approved" if approve else "refused",
        },
    )
    await session.commit()


@router.post(
    "/local/{uid}/versions/{version}/approve",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def approve_shared_version(
    uid: str, version: str, session: SystemSessionDep, owner: ConfigManageDep
) -> Response:
    """Put a shared version on the shelf. It becomes the listing's latest."""
    await _review(session, owner.id, uid, version, approve=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/local/{uid}/versions/{version}/refuse",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def refuse_shared_version(
    uid: str, version: str, session: SystemSessionDep, owner: ConfigManageDep
) -> Response:
    """Refuse a shared version. It is deleted, and so is a listing left with no
    version — it was never offered, so nothing depends on it."""
    await _review(session, owner.id, uid, version, approve=False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/local/upload",
    response_model=ListingUploadResult,
    status_code=status.HTTP_201_CREATED,
)
async def upload_listing_file(
    payload: ListingUploadRequest, session: SystemSessionDep, owner: ConfigManageDep
) -> Response:
    """Publish a listing file (``config.manage``).

    The manifest a catalog directory or a registry carries, published as a
    ``local`` listing, on the shelf straight away. A file the catalogue will
    not take answers 422 with the validator's reason beside the code, so the
    person who uploaded it can see what to fix.
    """
    try:
        listing = await local_listings.upload_listing(session, payload.manifest)
    except CatalogError as exc:
        await session.rollback()
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "detail": MarketplaceMessages.LISTING_UPLOAD_INVALID,
                "problem": str(exc)[:500],
            },
        )
    version = await catalog_service.get_listing_version(
        session, listing.latest_version_id
    )
    await audit_service.record(
        session,
        event_type=AuditEventType.MARKETPLACE_LISTING_UPLOADED,
        actor_user_id=owner.id,
        detail={
            "listing_uid": listing.uid,
            "kind": listing.kind,
            "version": version.version if version else None,
        },
    )
    await session.commit()
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=ListingUploadResult(
            uid=listing.uid,
            public_id=listing.public_id,
            version=version.version if version else "",
        ).model_dump(mode="json"),
    )


@router.get("/local/mine", response_model=list[MarketplaceSharedListingRead])
async def list_my_shares(
    session: UserSessionDep, current_user: CurrentUser
) -> list[MarketplaceSharedListingRead]:
    """The listings the signed-in member shared, with any version still
    waiting for review."""
    listings = await local_listings.listings_submitted_by(session, current_user.id)
    versions = await catalog_service.get_listing_versions(
        session, [listing.latest_version_id for listing in listings]
    )
    waiting = await local_listings.waiting_versions_of(
        session, [listing.id for listing in listings if listing.id is not None]
    )
    return [
        MarketplaceSharedListingRead(
            **serialize_listing_summary(
                listing, versions.get(listing.latest_version_id)
            ).model_dump(),
            pending_versions=waiting.get(listing.id, []),
        )
        for listing in listings
    ]


@router.delete("/local/{uid}", status_code=status.HTTP_204_NO_CONTENT)
async def withdraw_my_share(
    uid: str, session: SystemSessionDep, current_user: CurrentUser
) -> Response:
    """Take down a listing the signed-in member shared. Communities that
    installed a copy keep it."""
    try:
        await local_listings.withdraw_share(session, uid, current_user.id)
    except local_listings.LocalListingError as exc:
        raise _local_error(exc) from exc
    await audit_service.record(
        session,
        event_type=AuditEventType.MARKETPLACE_LISTING_WITHDRAWN,
        actor_user_id=current_user.id,
        detail={"listing_uid": uid},
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
