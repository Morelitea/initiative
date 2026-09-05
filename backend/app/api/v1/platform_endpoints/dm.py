"""Who may ask to message you, and who you will not hear from.

All of it on ``UserSessionDep`` — a platform-tier session, RLS enforced. Every
table here is own-row for the caller, and the one question that is not about
their own rows (may I reach that account) is answered by
``public.dm_apparent_permission``, which returns a decision rather than a row
and takes no caller id.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy import text

from app.api.deps import UserSessionDep, get_current_active_user
from app.core.messages import DirectMessageMessages
from app.models.platform.user import User
from app.models.platform.contact_grant import ContactGrantKind
from app.schemas.platform.dm import (
    ConnectionRequestCreate,
    ContactGrantRead,
    ContactGrantsResponse,
    DirectMessagePermissionRead,
    DirectMessageSettingsRead,
    DirectMessageSettingsUpdate,
    IgnoredAccountsResponse,
    MessageRequestCreate,
)
from app.services.platform import contact_grants as contact_grants_service
from app.services.platform import dm_settings as dm_settings_service
from app.services.platform import user_ignores as user_ignores_service

me_router = APIRouter()
user_router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_active_user)]
TargetUserId = Annotated[int, Path(ge=1)]


async def _require_visible_account(session, user_id: int) -> None:
    """That the id names an account this caller may be shown at all.

    Reads the published projection, not ``users``: what is public about an
    account is decided in the catalog, and this endpoint has no business
    knowing more.
    """
    exists = (
        await session.exec(
            text("SELECT 1 FROM public.user_profiles WHERE id = :id").bindparams(
                id=user_id
            )
        )
    ).first()
    if exists is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=DirectMessageMessages.USER_NOT_FOUND,
        )


@me_router.get("/dm-settings", response_model=DirectMessageSettingsRead)
async def read_dm_settings(
    session: UserSessionDep,
    current_user: CurrentUser,
) -> DirectMessageSettingsRead:
    """The policy this account picked, and one toggle per community it is in.

    The toggles come back whatever the policy is, so switching to *My
    communities* does not land on an empty screen.
    """
    return await dm_settings_service.read_settings(session, user=current_user)


@me_router.patch("/dm-settings", response_model=DirectMessageSettingsRead)
async def update_dm_settings(
    payload: DirectMessageSettingsUpdate,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> DirectMessageSettingsRead:
    """Change the policy, the toggles, or both.

    Anything above ``private`` needs the age question answered. That is asked
    for here rather than left to the community directory's own switches, so an
    account on a deployment running no directory is held to the same floor.
    """
    try:
        return await dm_settings_service.update_settings(
            session,
            user=current_user,
            dm_policy=payload.dm_policy,
            communities=payload.communities,
            send_receipts=payload.send_receipts,
        )
    except dm_settings_service.DirectMessageSettingsError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.code
        ) from exc


@me_router.get("/ignored", response_model=IgnoredAccountsResponse)
async def list_ignored_accounts(
    session: UserSessionDep,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> IgnoredAccountsResponse:
    """The caller's own list. Who has ignored *them* is not answerable here."""
    return await user_ignores_service.list_ignored(
        session, user_id=current_user.id, page=page, page_size=page_size
    )


@me_router.put("/ignored/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def ignore_account(
    user_id: TargetUserId,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> Response:
    """Start ignoring an account. Idempotent, and nothing is deleted."""
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=DirectMessageMessages.CANNOT_IGNORE_SELF,
        )
    await _require_visible_account(session, user_id)
    await user_ignores_service.add(
        session, user_id=current_user.id, ignored_user_id=user_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@me_router.delete("/ignored/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def stop_ignoring_account(
    user_id: TargetUserId,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> Response:
    """Stop ignoring an account, restoring exactly what was there before."""
    await user_ignores_service.remove(
        session, user_id=current_user.id, ignored_user_id=user_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@user_router.get("/{user_id}/dm-permission", response_model=DirectMessagePermissionRead)
async def read_dm_permission(
    user_id: TargetUserId,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> DirectMessagePermissionRead:
    """What the caller may do about that account: ``open``, ``may_request`` or
    ``denied``.

    One value, with nothing beside it to tell the refusals apart. The answer is
    computed by ``public.dm_apparent_permission``, which reads the caller from
    the request context rather than taking one.
    """
    await _require_visible_account(session, user_id)
    if user_id == current_user.id:
        return DirectMessagePermissionRead(permission="denied", may_connect=False)
    permission = (
        await session.exec(
            text("SELECT public.dm_apparent_permission(:t)").bindparams(t=user_id)
        )
    ).scalar_one()
    # Asked separately because it is a separate rule. Both read the caller from
    # the request context rather than taking one.
    may_connect = (
        await session.exec(
            text("SELECT public.dm_may_connect(:t)").bindparams(t=user_id)
        )
    ).scalar_one()
    return DirectMessagePermissionRead(permission=permission, may_connect=may_connect)


def _grant_error(exc: contact_grants_service.ContactGrantError) -> HTTPException:
    """Every refusal is a 409 with its code and nothing else.

    A handle nobody holds, an account that cannot be reached and a request that
    will never be surfaced all answer the same way, so the endpoint is not a
    way to learn which it was.
    """
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.code)


@me_router.get("/connections", response_model=ContactGrantsResponse)
async def list_connections(
    session: UserSessionDep,
    current_user: CurrentUser,
) -> ContactGrantsResponse:
    """Accepted connections, plus what is pending in each direction."""
    grants = await contact_grants_service.list_for(
        session, user_id=current_user.id, kind=ContactGrantKind.connection
    )
    return await contact_grants_service.to_reads(
        session, user_id=current_user.id, grants=grants
    )


@me_router.post(
    "/connections",
    response_model=ContactGrantRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_connection(
    payload: ConnectionRequestCreate,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> ContactGrantRead:
    """Ask an account to connect, by its exact handle.

    A handle rather than an id, whatever the target's policy: it is the one
    shape that works for an account on ``private``, which is never offered from
    a roster or a picker.
    """
    try:
        target_id = await contact_grants_service.resolve_handle(
            session,
            username=payload.username,
            discriminator=payload.discriminator,
        )
        grant = await contact_grants_service.request(
            session,
            actor_id=current_user.id,
            target_id=target_id,
            kind=ContactGrantKind.connection,
        )
    except contact_grants_service.ContactGrantError as exc:
        raise _grant_error(exc) from exc
    return await _single_read(session, current_user.id, grant)


@me_router.post("/connections/{user_id}/accept", response_model=ContactGrantRead)
async def accept_connection(
    user_id: TargetUserId,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> ContactGrantRead:
    """Accept a connection, which also opens the pair's message channel."""
    try:
        grant = await contact_grants_service.accept(
            session,
            actor_id=current_user.id,
            other_id=user_id,
            kind=ContactGrantKind.connection,
        )
    except contact_grants_service.ContactGrantError as exc:
        raise _grant_error(exc) from exc
    return await _single_read(session, current_user.id, grant)


@me_router.delete("/connections/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_connection(
    user_id: TargetUserId,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> Response:
    """Decline, cancel or disconnect — one verb.

    The pair's message grant is re-tested rather than dropped: two co-members
    who un-connect can still ask each other, so they keep talking.
    """
    await contact_grants_service.remove(
        session,
        actor_id=current_user.id,
        other_id=user_id,
        kind=ContactGrantKind.connection,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@me_router.get("/message-requests", response_model=ContactGrantsResponse)
async def list_message_requests(
    session: UserSessionDep,
    current_user: CurrentUser,
) -> ContactGrantsResponse:
    """Open channels, plus what is pending in each direction."""
    grants = await contact_grants_service.list_for(
        session, user_id=current_user.id, kind=ContactGrantKind.message
    )
    return await contact_grants_service.to_reads(
        session, user_id=current_user.id, grants=grants
    )


@me_router.post(
    "/message-requests",
    response_model=ContactGrantRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_message(
    payload: MessageRequestCreate,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> ContactGrantRead:
    """Ask permission to message an account.

    Comes back already accepted when the pair is connected: a connection has
    answered this question, and asking twice is a consent step with no decision
    in it.
    """
    try:
        grant = await contact_grants_service.request(
            session,
            actor_id=current_user.id,
            target_id=payload.user_id,
            kind=ContactGrantKind.message,
        )
    except contact_grants_service.ContactGrantError as exc:
        raise _grant_error(exc) from exc
    return await _single_read(session, current_user.id, grant)


@me_router.post("/message-requests/{user_id}/accept", response_model=ContactGrantRead)
async def accept_message_request(
    user_id: TargetUserId,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> ContactGrantRead:
    try:
        grant = await contact_grants_service.accept(
            session,
            actor_id=current_user.id,
            other_id=user_id,
            kind=ContactGrantKind.message,
        )
    except contact_grants_service.ContactGrantError as exc:
        raise _grant_error(exc) from exc
    return await _single_read(session, current_user.id, grant)


@me_router.delete("/message-requests/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_message_request(
    user_id: TargetUserId,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> Response:
    """Decline, cancel or close a channel."""
    await contact_grants_service.remove(
        session,
        actor_id=current_user.id,
        other_id=user_id,
        kind=ContactGrantKind.message,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _single_read(session, user_id: int, grant) -> ContactGrantRead:
    grouped = await contact_grants_service.to_reads(
        session, user_id=user_id, grants=[grant]
    )
    for bucket in (grouped.accepted, grouped.incoming, grouped.outgoing):
        if bucket:
            return bucket[0]
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=DirectMessageMessages.USER_NOT_FOUND,
    )
