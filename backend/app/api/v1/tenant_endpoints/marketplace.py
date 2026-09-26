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

Listings are written by the system engine (boot seeding, the operator's
catalog directory, the registry refresh) through the platform routes. Installing
writes the guild's own schema: a tool's listing through that tool's importer
(below), an app through the guild's app routes.
"""

from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.api.deps import (
    RLSSessionDep,
    GuildContextDep,
    CurrentUser,
)
from app.core.messages import ImportEngineMessages, MarketplaceMessages
from app.models.platform.marketplace import MarketplaceListing
from app.schemas.platform.marketplace import (
    ListingKind,
    ListingStartFrom,
    MarketplaceInstallRequest,
    MarketplaceInstallResult,
    MarketplaceListingDetail,
    MarketplaceListingPage,
    MarketplaceShareRequest,
    MarketplaceShareResult,
    serialize_listing_summary,
)
from app.services.marketplace import catalog as catalog_service
from app.services.marketplace import registration_lookup
from app.services.import_engine.contract import ImportEngineError
from app.services.marketplace.definitions import TOOL_LISTING_KINDS
from app.services.marketplace.installs import (
    ListingInstallError,
    count_install,
    installed_app_uids,
    listing_is_offered,
    resolve_listing_install,
)
from app.services.marketplace import local_listings
from app.services.marketplace.listing_assets import (
    MAX_IMAGE_BYTES,
    MAX_LISTING_IMAGES,
    UploadedImageError,
    store_uploaded_image,
)
from app.services.tenant import guild_apps as guild_apps_service
from app.services.tenant.attachments import FileTooLargeError, read_upload_bounded
from app.services.marketplace.publish_profile import export_for_listing
from app.services.marketplace.tool_listings import (
    example_is_generated,
    install_tool_listing,
    listing_example,
)
from app.core.audit_events import AuditEventType
from app.core.user_display import handle_of
from app.db import cohorts
from app.services import audit as audit_service
from app.services.platform import app_settings as app_settings_service

router = APIRouter()


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
    definition = dict(latest.definition) if latest else {}
    # What the install dialog asks the seat about, from the version it would
    # install and the registration's ceiling. Empty for anything not an app.
    requested: list[str] = []
    grantable: list[str] = []
    if listing.kind == "app":
        requested = guild_apps_service.requested_scopes(definition)
        registration = await registration_lookup.registration_for_definition(definition)
        grantable = guild_apps_service.grantable_scopes(
            definition, registration.scope_ceiling if registration else ()
        )
    return MarketplaceListingDetail(
        **summary.model_dump(),
        requested_scopes=requested,
        grantable_scopes=grantable,
        app_names=await guild_apps_service.app_scope_names(session, requested),
        has_initiative_surfaces=(
            listing.kind == "app"
            and guild_apps_service.has_initiative_surfaces(definition)
        ),
        long_description=listing.long_description,
        # A preview of what installing would produce. The install path re-reads
        # the catalog itself, so this is display data, not an input.
        definition=dict(latest.definition) if latest else None,
        example=(
            listing_example(TOOL_LISTING_KINDS[listing.kind], listing.uid, latest)
            if latest is not None and listing.kind in TOOL_LISTING_KINDS
            else None
        ),
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


@router.post(
    "/listings/by-uid/{uid}/install",
    response_model=MarketplaceInstallResult,
    status_code=status.HTTP_201_CREATED,
)
async def install_marketplace_listing(
    uid: str,
    payload: MarketplaceInstallRequest,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> MarketplaceInstallResult:
    """Install a tool's listing: import a copy of it into an initiative.

    Any member who may create that tool in the initiative may install one —
    content runs no code and reaches nothing, so this is the importer's own
    permission and nothing more. The copy is the member's: it records the
    listing and version it came from, and nothing links it back.

    Apps and profile packs install elsewhere; a uid naming one reads as not
    found here, as it would from any installer that cannot install it.
    """
    # Installing is authoring, like any import: a community whose content is
    # frozen takes none, and a grant reaches existing content only.
    if guild_context.content_read_only or guild_context.is_pam:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ImportEngineMessages.IMPORT_WRITE_REQUIRED,
        )
    listing = await catalog_service.get_listing_by_uid(session, uid)
    tool = TOOL_LISTING_KINDS.get(listing.kind) if listing is not None else None
    if listing is None or tool is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=MarketplaceMessages.LISTING_NOT_FOUND,
        )
    try:
        listing, version = await resolve_listing_install(
            session, uid, kind=listing.kind
        )
    except ListingInstallError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND if exc.not_found else status.HTTP_409_CONFLICT
            ),
            detail=exc.code,
        ) from exc
    if payload.start_from == ListingStartFrom.example and (
        example_is_generated(tool) or not version.example
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=MarketplaceMessages.LISTING_HAS_NO_EXAMPLE,
        )

    try:
        result = await install_tool_listing(
            session,
            tool=tool,
            listing=listing,
            version=version,
            user=current_user,
            guild_id=guild_context.guild_id,
            initiative_id=payload.initiative_id,
            start_from=payload.start_from.value,
            starts_on=payload.starts_on,
        )
    except ImportEngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    await session.commit()
    await count_install(listing.id)
    return MarketplaceInstallResult(
        kind=listing.kind,
        listing_uid=listing.uid,
        listing_version=version.version,
        result=result,
    )


@router.post(
    "/share",
    response_model=MarketplaceShareResult,
    status_code=status.HTTP_201_CREATED,
)
async def share_to_marketplace(
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    kind: Annotated[ListingKind, Form()],  # type: ignore[valid-type]
    entity_id: Annotated[int, Form()],
    name: Annotated[str, Form()],
    description: Annotated[str, Form()],
    example_entity_id: Annotated[Optional[int], Form()] = None,
    long_description: Annotated[Optional[str], Form()] = None,
    release_notes: Annotated[Optional[str], Form()] = None,
    listing_uid: Annotated[Optional[str], Form()] = None,
    images: Annotated[list[UploadFile], File()] = [],  # noqa: B006 — FastAPI reads the default, never mutates it
) -> MarketplaceShareResult:
    """Share an item from this community to the deployment's marketplace.

    The item is read the way exporting it reads it, on the member's own
    session — so a member shares only what they could export — and stripped
    to what belongs to the work (``publish_profile``). It then becomes a
    ``local`` listing, on the shelf straight away if the owner lets members
    publish directly, and otherwise waiting for the owner's review.

    Nothing is read from the community's storage: its pictures are its own.
    ``images`` are the pictures the member uploads for the listing with the
    share — the ones its card and page show — and they are the only pictures
    it has. A new version keeps the listing's pictures, like its name.
    """
    try:
        payload = MarketplaceShareRequest(
            kind=kind,
            entity_id=entity_id,
            example_entity_id=example_entity_id,
            name=name,
            description=description,
            long_description=long_description,
            release_notes=release_notes,
            listing_uid=listing_uid,
        )
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc
    if len(images) > MAX_LISTING_IMAGES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=MarketplaceMessages.SHARE_IMAGE_INVALID,
        )
    uploaded: list[bytes] = []
    for image in images:
        try:
            uploaded.append(await read_upload_bounded(image, MAX_IMAGE_BYTES))
        except FileTooLargeError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=MarketplaceMessages.SHARE_IMAGE_INVALID,
            ) from exc

    if guild_context.is_pam:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=MarketplaceMessages.SHARE_NOT_PERMITTED,
        )
    tool = TOOL_LISTING_KINDS.get(payload.kind)
    if tool is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=MarketplaceMessages.SHARE_INVALID,
        )
    if payload.example_entity_id is not None and example_is_generated(tool):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=MarketplaceMessages.SHARE_INVALID,
        )

    envelope = await export_for_listing(
        session,
        tool=tool,
        entity_id=payload.entity_id,
        user=current_user,
        guild_id=guild_context.guild_id,
    )
    example = (
        await export_for_listing(
            session,
            tool=tool,
            entity_id=payload.example_entity_id,
            user=current_user,
            guild_id=guild_context.guild_id,
        )
        if payload.example_entity_id is not None
        else None
    )

    # The catalogue's writer is the system engine, on this community's cohort;
    # the member's session has done its part by reading the item.
    async with cohorts.system_session(guild_context.guild_id) as system:
        hold = not await app_settings_service.marketplace_members_publish_directly(
            system
        )
        # The pictures the member uploaded become files in the marketplace's
        # media, in the same transaction as the listing that shows them.
        try:
            image_paths = [
                await store_uploaded_image(system, data) for data in uploaded
            ]
        except UploadedImageError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=MarketplaceMessages.SHARE_IMAGE_INVALID,
            ) from exc
        try:
            listing, version = await local_listings.submit_share(
                system,
                tool=tool,
                envelope=envelope,
                example=example,
                name=payload.name,
                description=payload.description,
                long_description=payload.long_description,
                release_notes=payload.release_notes,
                # The handle, which names the account the same way on every
                # shelf; a real name is each community's to show or not.
                publisher=handle_of(current_user),
                submitter_id=current_user.id,
                listing_uid=payload.listing_uid,
                images=image_paths,
                hold_for_review=hold,
            )
        except local_listings.LocalListingError as exc:
            raise HTTPException(
                status_code=(
                    status.HTTP_404_NOT_FOUND
                    if exc.not_found
                    else status.HTTP_422_UNPROCESSABLE_CONTENT
                ),
                detail=exc.code,
            ) from exc
        await audit_service.record(
            system,
            event_type=AuditEventType.MARKETPLACE_LISTING_SHARED,
            actor_user_id=current_user.id,
            guild_id=guild_context.guild_id,
            detail={
                "listing_uid": listing.uid,
                "kind": listing.kind,
                "version": version.version,
                "awaiting_review": version.awaiting_review,
            },
        )
        await system.commit()
    return MarketplaceShareResult(
        uid=listing.uid,
        public_id=listing.public_id,
        version=version.version,
        awaiting_review=version.awaiting_review,
    )
