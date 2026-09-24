"""Operator CRUD for the app service registry (``app_service_registrations``)
and its publishers (``publishers``).

A listing declares what an app is; a registration is this deployment's separate
statement that the app is wired up — which listing it is, its addresses, its
public keys, and the powers (``grants``) and reach (``mandatory``) an operator
confers on it. A publisher is the prefix of an app's ``public_id``, with a
switch that stops every app under it. Nothing here can be claimed by a
manifest, which is why the whole surface is gated on ``apps.manage`` (owner
tier) rather than on anything a publisher supplies.

Every route runs on the system engine: neither table carries a request-path
write grant. The logic lives in ``app.services.marketplace.registrations`` and
``app.services.marketplace.publishers``; these routers gate, translate, and
delegate.
"""

from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import require_capability
from app.core.capabilities import Capability
from app.core.messages import AppServiceMessages
from app.db.session import get_system_session
from app.models.platform.publisher import Publisher
from app.models.platform.user import User
from app.schemas.platform.app_service import (
    AppPublisherCreate,
    AppPublisherRead,
    AppPublisherUpdate,
    AppServiceRegistrationCreate,
    AppServiceRegistrationRead,
    AppServiceRegistrationUpdate,
)
from app.services.marketplace import publishers as publishers_service
from app.services.marketplace import registrations as registrations_service

router = APIRouter()
publishers_router = APIRouter()

SystemSessionDep = Annotated[AsyncSession, Depends(get_system_session)]
#: Wiring app services is deployment configuration — owner tier, like the rest
#: of the platform settings wall.
AppsManageDep = Annotated[User, Depends(require_capability(Capability.APPS_MANAGE))]


def _to_read(
    view: registrations_service.RegistrationView,
) -> AppServiceRegistrationRead:
    row = view.row
    return AppServiceRegistrationRead(
        id=row.id,
        public_id=row.public_id,
        listing_uid=row.listing_uid,
        publisher_id=view.publisher.id,
        publisher_prefix=view.publisher.prefix,
        publisher_name=view.publisher.display_name,
        publisher_enabled=view.publisher.enabled,
        base_url=row.base_url,
        embed_origin=row.embed_origin,
        allowed_origins=list(row.allowed_origins or []),
        grants=list(row.grants or []),
        jwks=row.jwks,
        jwks_uri=row.jwks_uri,
        scope_ceiling=list(row.scope_ceiling or []),
        mandatory=row.mandatory,
        enabled=row.enabled,
        source=row.source,
        image_digest=row.image_digest,
        live=view.live,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _read_one(
    session: AsyncSession, registration_id: int
) -> AppServiceRegistrationRead:
    views = await registrations_service.registration_views(session, registration_id)
    if not views:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AppServiceMessages.NOT_FOUND,
        )
    return _to_read(views[0])


@router.get("/", response_model=List[AppServiceRegistrationRead])
async def list_app_services(
    session: SystemSessionDep,
    _owner: AppsManageDep,
) -> List[AppServiceRegistrationRead]:
    """Every app service this deployment has wired up (``apps.manage``)."""
    views = await registrations_service.registration_views(session)
    return [_to_read(view) for view in views]


@router.post(
    "/",
    response_model=AppServiceRegistrationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_app_service(
    payload: AppServiceRegistrationCreate,
    session: SystemSessionDep,
    owner: AppsManageDep,
) -> AppServiceRegistrationRead:
    """Register an app service as stated: its id, its listing, its addresses
    and its keys. Its publisher is the one its id's prefix names, added
    unverified when there is none."""
    row = await registrations_service.create_registration(
        session,
        public_id=payload.public_id,
        listing_uid=payload.listing_uid,
        base_url=payload.base_url,
        embed_origin=payload.embed_origin,
        allowed_origins=payload.allowed_origins,
        grants=payload.grants,
        jwks=payload.jwks,
        jwks_uri=payload.jwks_uri,
        scope_ceiling=payload.scope_ceiling,
        mandatory=payload.mandatory,
        enabled=payload.enabled,
        actor_user_id=owner.id,
    )
    return await _read_one(session, row.id)


@router.get("/{registration_id}", response_model=AppServiceRegistrationRead)
async def read_app_service(
    registration_id: int,
    session: SystemSessionDep,
    _owner: AppsManageDep,
) -> AppServiceRegistrationRead:
    return await _read_one(session, registration_id)


@router.patch("/{registration_id}", response_model=AppServiceRegistrationRead)
async def update_app_service(
    registration_id: int,
    payload: AppServiceRegistrationUpdate,
    session: SystemSessionDep,
    owner: AppsManageDep,
) -> AppServiceRegistrationRead:
    """Enable/disable, change the listing, repoint either address, replace the
    keys, or change the powers conferred."""
    row = await registrations_service.update_registration(
        session,
        registration_id,
        listing_uid=payload.listing_uid,
        base_url=payload.base_url,
        embed_origin=payload.embed_origin,
        allowed_origins=payload.allowed_origins,
        grants=payload.grants,
        jwks=payload.jwks,
        jwks_uri=payload.jwks_uri,
        scope_ceiling=payload.scope_ceiling,
        mandatory=payload.mandatory,
        enabled=payload.enabled,
        actor_user_id=owner.id,
    )
    return await _read_one(session, row.id)


@router.delete("/{registration_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_app_service(
    registration_id: int,
    session: SystemSessionDep,
    owner: AppsManageDep,
) -> None:
    """Remove the registration. Every channel it backed stops with the row."""
    await registrations_service.delete_registration(
        session, registration_id, actor_user_id=owner.id
    )


# --- publishers ---------------------------------------------------------------


def _publisher_read(row: Publisher) -> AppPublisherRead:
    return AppPublisherRead(
        id=row.id,
        prefix=row.prefix,
        display_name=row.display_name,
        verified=row.verified,
        enabled=row.enabled,
        created_at=row.created_at,
    )


@publishers_router.get("/", response_model=List[AppPublisherRead])
async def list_app_publishers(
    session: SystemSessionDep,
    _owner: AppsManageDep,
) -> List[AppPublisherRead]:
    """Every publisher of app services on this deployment (``apps.manage``)."""
    rows = await publishers_service.list_publishers(session)
    return [_publisher_read(row) for row in rows]


@publishers_router.post(
    "/", response_model=AppPublisherRead, status_code=status.HTTP_201_CREATED
)
async def create_app_publisher(
    payload: AppPublisherCreate,
    session: SystemSessionDep,
    owner: AppsManageDep,
) -> AppPublisherRead:
    """Add a publisher for a prefix, such as a private app's. It starts
    unverified."""
    row = await publishers_service.create_publisher(
        session,
        prefix=payload.prefix,
        display_name=payload.display_name,
        enabled=payload.enabled,
        actor_user_id=owner.id,
    )
    return _publisher_read(row)


@publishers_router.patch("/{publisher_id}", response_model=AppPublisherRead)
async def update_app_publisher(
    publisher_id: int,
    payload: AppPublisherUpdate,
    session: SystemSessionDep,
    owner: AppsManageDep,
) -> AppPublisherRead:
    """Rename a publisher, or switch it on or off. Off makes every app under
    its prefix not live."""
    row = await publishers_service.update_publisher(
        session,
        publisher_id,
        display_name=payload.display_name,
        enabled=payload.enabled,
        actor_user_id=owner.id,
    )
    return _publisher_read(row)
