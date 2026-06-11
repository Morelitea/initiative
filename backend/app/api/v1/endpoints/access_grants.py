"""Privileged Access Management (PAM) endpoints.

Self-service, time-bound, per-guild access grants: a lower-privilege platform
user requests temporary access to a guild, an approver grants/denies it, and it
auto-expires. See ``app.services.access_grants``.

All routes use the admin (RLS-bypassing) session because access_grants is a
platform-scoped table managed cross-guild — authorization is enforced here via
capabilities + ownership, mirroring the ``/admin/*`` endpoints.
"""

from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.deps import get_current_active_user, require_capability
from app.core.capabilities import Capability, user_has_capability
from app.core.messages import AccessGrantMessages
from app.db.session import get_admin_session
from app.models.user import User
from app.schemas.access_grant import (
    AccessGrantApprove,
    AccessGrantCreate,
    AccessGrantRead,
)
from app.services import access_grants as service
from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter()

AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]
AccessRequestDep = Annotated[
    User, Depends(require_capability(Capability.ACCESS_REQUEST))
]
AccessApproveDep = Annotated[
    User, Depends(require_capability(Capability.ACCESS_APPROVE))
]

# Map service error codes to (status, detail). All details are machine-readable
# codes the frontend localizes via errors.json.
_ERROR_STATUS: dict[str, int] = {
    "GUILD_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "ALREADY_MEMBER": status.HTTP_400_BAD_REQUEST,
    "DURATION_TOO_LONG": status.HTTP_400_BAD_REQUEST,
    "OVERLAPPING_GRANT": status.HTTP_409_CONFLICT,
    "NOT_PENDING": status.HTTP_400_BAD_REQUEST,
    "NOT_ACTIVE": status.HTTP_400_BAD_REQUEST,
    "CANNOT_APPROVE_OWN": status.HTTP_400_BAD_REQUEST,
    "CANNOT_CANCEL_OTHERS": status.HTTP_403_FORBIDDEN,
}
_ERROR_DETAIL: dict[str, str] = {
    "GUILD_NOT_FOUND": AccessGrantMessages.GUILD_NOT_FOUND,
    "ALREADY_MEMBER": AccessGrantMessages.ALREADY_MEMBER,
    "DURATION_TOO_LONG": AccessGrantMessages.DURATION_TOO_LONG,
    "OVERLAPPING_GRANT": AccessGrantMessages.OVERLAPPING_GRANT,
    "NOT_PENDING": AccessGrantMessages.NOT_PENDING,
    "NOT_ACTIVE": AccessGrantMessages.NOT_ACTIVE,
    "CANNOT_APPROVE_OWN": AccessGrantMessages.CANNOT_APPROVE_OWN,
    "CANNOT_CANCEL_OTHERS": AccessGrantMessages.CANNOT_CANCEL_OTHERS,
}


def _raise(error: service.AccessGrantError) -> None:
    raise HTTPException(
        status_code=_ERROR_STATUS.get(error.code, status.HTTP_400_BAD_REQUEST),
        detail=_ERROR_DETAIL.get(error.code, error.code),
    )


async def _one(session: AsyncSession, grant) -> AccessGrantRead:
    reads = await service.to_read(session, [grant])
    return reads[0]


@router.post("/", response_model=AccessGrantRead, status_code=status.HTTP_201_CREATED)
async def create_access_request(
    payload: AccessGrantCreate,
    session: AdminSessionDep,
    current_user: AccessRequestDep,
) -> AccessGrantRead:
    """Request time-bound access to a guild (requires ``access.request``)."""
    try:
        grant = await service.request_grant(
            session, requester=current_user, payload=payload
        )
    except service.AccessGrantError as exc:
        _raise(exc)
    read = await _one(session, grant)
    await session.commit()
    return read


@router.get("/", response_model=List[AccessGrantRead])
async def list_access_grants(
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    mine: bool = Query(True, description="List only your own requests."),
    grant_status: Optional[str] = Query(None, alias="status"),
    live: bool = Query(False, description="Keep only grants that haven't expired yet."),
    limit: Optional[int] = Query(
        None,
        ge=1,
        le=200,
        description="Page size — the number of most-recent grants returned.",
    ),
    offset: int = Query(0, ge=0, description="Number of grants to skip (for paging)."),
) -> List[AccessGrantRead]:
    """List access grants.

    Defaults to your own requests. ``mine=false`` returns the full queue and
    requires ``access.read`` (approvers). Grants are ordered newest-first;
    ``limit``/``offset`` page the result so it can't grow unbounded, and
    ``live=true`` narrows to grants that are still within their window.
    """
    if mine:
        grants = await service.list_grants(
            session,
            user_id=current_user.id,
            statuses=[grant_status] if grant_status else None,
            live_only=live,
            limit=limit,
            offset=offset,
        )
    else:
        if not user_has_capability(current_user, Capability.ACCESS_READ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="INSUFFICIENT_PRIVILEGES"
            )
        grants = await service.list_grants(
            session,
            statuses=[grant_status] if grant_status else None,
            live_only=live,
            limit=limit,
            offset=offset,
        )
    return await service.to_read(session, grants)


@router.get("/{grant_id}", response_model=AccessGrantRead)
async def get_access_grant(
    grant_id: int,
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> AccessGrantRead:
    grant = await service.get_grant(session, grant_id)
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AccessGrantMessages.NOT_FOUND
        )
    # Owners of the request, or approvers, may view it.
    if grant.user_id != current_user.id and not user_has_capability(
        current_user, Capability.ACCESS_READ
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="INSUFFICIENT_PRIVILEGES"
        )
    return await _one(session, grant)


@router.post("/{grant_id}/approve", response_model=AccessGrantRead)
async def approve_access_grant(
    grant_id: int,
    payload: AccessGrantApprove,
    session: AdminSessionDep,
    current_user: AccessApproveDep,
) -> AccessGrantRead:
    grant = await service.get_grant(session, grant_id)
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AccessGrantMessages.NOT_FOUND
        )
    try:
        grant = await service.approve(
            session,
            grant=grant,
            approver=current_user,
            duration_minutes=payload.duration_minutes,
        )
    except service.AccessGrantError as exc:
        _raise(exc)
    read = await _one(session, grant)
    await session.commit()
    return read


@router.post("/{grant_id}/deny", response_model=AccessGrantRead)
async def deny_access_grant(
    grant_id: int,
    session: AdminSessionDep,
    current_user: AccessApproveDep,
) -> AccessGrantRead:
    grant = await service.get_grant(session, grant_id)
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AccessGrantMessages.NOT_FOUND
        )
    try:
        grant = await service.deny(session, grant=grant, approver=current_user)
    except service.AccessGrantError as exc:
        _raise(exc)
    read = await _one(session, grant)
    await session.commit()
    return read


@router.post("/{grant_id}/revoke", response_model=AccessGrantRead)
async def revoke_access_grant(
    grant_id: int,
    session: AdminSessionDep,
    current_user: AccessApproveDep,
) -> AccessGrantRead:
    grant = await service.get_grant(session, grant_id)
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AccessGrantMessages.NOT_FOUND
        )
    try:
        grant = await service.revoke(session, grant=grant, revoker=current_user)
    except service.AccessGrantError as exc:
        _raise(exc)
    read = await _one(session, grant)
    await session.commit()
    return read


@router.delete(
    "/{grant_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
async def cancel_access_request(
    grant_id: int,
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    """Withdraw your own still-pending request."""
    grant = await service.get_grant(session, grant_id)
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AccessGrantMessages.NOT_FOUND
        )
    try:
        await service.cancel_own_pending(session, grant=grant, user=current_user)
    except service.AccessGrantError as exc:
        _raise(exc)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
