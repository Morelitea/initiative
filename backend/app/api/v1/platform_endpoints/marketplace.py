"""Maintaining the catalog, and serving the artwork it is drawn with.

Reading the marketplace is not here: what a guild is offered depends on which
apps it has installed, so the shelf and a listing's page are guild-addressed
and live in ``tenant_endpoints/marketplace.py``.

What is here is everything that decides *what this deployment carries*, which
is a property of the deployment rather than of any guild. Two write routes,
both gated on the capability that governs deployment configuration — because
that is what publishing a listing is: the operator's rescan of their own
catalog directory, and their "refresh now" for the signed registry. The
catalog has no other writer; the system engine does the rest (boot seeding and
the background refresh), and installing writes a guild's own schema through
the tool's endpoints.

The third route is public: the mirrored artwork a registry's listings are
served from, which is the same bytes for everyone and carries nothing about
any guild.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import SessionDep
from app.api.v1.platform_endpoints.admin import ConfigManageDep
from app.core.config import settings
from app.core.messages import MarketplaceMessages, MarketplaceRegistryMessages
from app.db.session import get_admin_session
from app.models.platform.marketplace_registry import MarketplaceMedia
from app.schemas.platform.marketplace import (
    OperatorCatalogProblem,
    OperatorCatalogScanResult,
)
from app.schemas.platform.marketplace_registry import (
    RegistryRefreshRead,
    RegistrySkippedListing,
    RegistryStatusRead,
)
from app.services.marketplace import registry as registry_service
from app.services.marketplace import operator_catalog as operator_catalog_service

router = APIRouter()

AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]

#: A mirrored image is addressed by the hex SHA-256 of its own bytes.
_DIGEST_LENGTH = 64
_HEX_DIGITS = frozenset("0123456789abcdef")


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
