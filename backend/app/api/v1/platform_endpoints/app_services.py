"""Operator CRUD for the app service registry (``app_service_registrations``).

A listing declares what an app is; a registration is this deployment's separate
statement that the app is wired up — its URL, the shared secret, and the powers
(``grants``) and reach (``mandatory``) an operator confers on it. Nothing here
can be claimed by a manifest, which is why the whole surface is gated on
``apps.manage`` (owner tier) rather than on anything a publisher supplies.

Every route runs on the system engine: the table carries no request-path write
grant, and its secret column is deliberately unreachable from a routed session.
The CRUD logic lives in ``app.services.marketplace.registrations``; this router
gates, translates, and delegates.
"""

from typing import Annotated, List

from fastapi import APIRouter, Depends, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import require_capability
from app.core.capabilities import Capability
from app.db.session import get_admin_session
from app.models.platform.app_service_registration import AppServiceRegistration
from app.models.platform.user import User
from app.schemas.platform.app_service import (
    AppServiceRegistrationCreate,
    AppServiceRegistrationRead,
    AppServiceRegistrationUpdate,
    AppServiceVerifyRequest,
)
from app.services.marketplace import registrations as registrations_service

router = APIRouter()

AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]
#: Wiring app services is deployment configuration — owner tier, like the rest
#: of the platform settings wall.
AppsManageDep = Annotated[User, Depends(require_capability(Capability.APPS_MANAGE))]


def _to_read(row: AppServiceRegistration) -> AppServiceRegistrationRead:
    """Project a row onto the wire shape. The secret becomes a boolean here and
    nowhere else, so no route can serialize it by omission."""
    return AppServiceRegistrationRead(
        id=row.id,
        public_id=row.public_id,
        listing_uid=row.listing_uid,
        base_url=row.base_url,
        embed_origin=row.embed_origin,
        allowed_origins=list(row.allowed_origins or []),
        has_secret=bool(row.secret_encrypted),
        manifest_hash=row.manifest_hash,
        protocol_version=row.protocol_version,
        grants=list(row.grants or []),
        mandatory=row.mandatory,
        enabled=row.enabled,
        status=row.status,
        last_verified_at=row.last_verified_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/", response_model=List[AppServiceRegistrationRead])
async def list_app_services(
    session: AdminSessionDep,
    _admin: AppsManageDep,
) -> List[AppServiceRegistrationRead]:
    """Every app service this deployment has wired up (``apps.manage``)."""
    rows = await registrations_service.list_registrations(session)
    return [_to_read(row) for row in rows]


@router.post(
    "/",
    response_model=AppServiceRegistrationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_app_service(
    payload: AppServiceRegistrationCreate,
    session: AdminSessionDep,
    _admin: AppsManageDep,
) -> AppServiceRegistrationRead:
    """Register an app service, running the handshake on the way in.

    A service that answers names itself; one that does not yet answer can still
    be registered when the operator supplies ``public_id``, and carries the
    reason it is unverified until it does.
    """
    row = await registrations_service.create_registration(
        session,
        base_url=payload.base_url,
        secret=payload.secret,
        public_id=payload.public_id,
        embed_origin=payload.embed_origin,
        allowed_origins=payload.allowed_origins,
        grants=payload.grants,
        mandatory=payload.mandatory,
        enabled=payload.enabled,
    )
    return _to_read(row)


@router.get("/{registration_id}", response_model=AppServiceRegistrationRead)
async def read_app_service(
    registration_id: int,
    session: AdminSessionDep,
    _admin: AppsManageDep,
) -> AppServiceRegistrationRead:
    row = await registrations_service.get_registration(session, registration_id)
    return _to_read(row)


@router.patch("/{registration_id}", response_model=AppServiceRegistrationRead)
async def update_app_service(
    registration_id: int,
    payload: AppServiceRegistrationUpdate,
    session: AdminSessionDep,
    _admin: AppsManageDep,
) -> AppServiceRegistrationRead:
    """Enable/disable, rotate the secret, repoint either address, or change the
    powers conferred. Rotating the secret or repointing ``base_url`` clears the
    recorded verification; moving the browser address alone does not."""
    row = await registrations_service.update_registration(
        session,
        registration_id,
        base_url=payload.base_url,
        secret=payload.secret,
        embed_origin=payload.embed_origin,
        allowed_origins=payload.allowed_origins,
        grants=payload.grants,
        mandatory=payload.mandatory,
        enabled=payload.enabled,
    )
    return _to_read(row)


@router.delete("/{registration_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_app_service(
    registration_id: int,
    session: AdminSessionDep,
    _admin: AppsManageDep,
) -> None:
    """Remove the registration. Every channel it backed stops with the row."""
    await registrations_service.delete_registration(session, registration_id)


@router.post("/{registration_id}/verify", response_model=AppServiceRegistrationRead)
async def verify_app_service(
    registration_id: int,
    session: AdminSessionDep,
    _admin: AppsManageDep,
    payload: AppServiceVerifyRequest | None = None,
) -> AppServiceRegistrationRead:
    """Re-run the handshake and record the outcome on the row."""
    row = await registrations_service.verify_registration(
        session,
        registration_id,
        accept_manifest_change=bool(payload and payload.accept_manifest_change),
    )
    return _to_read(row)
