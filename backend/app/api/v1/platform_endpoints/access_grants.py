"""Privileged Access Management (PAM) endpoints.

Self-service, time-bound, per-guild access grants: a lower-privilege platform
user requests temporary access to a guild, an approver grants/denies it, and it
auto-expires. See ``app.services.access_grants``.

The reads run on the caller's platform tier (``UserSessionDep``): a grantee
reads their own grants, and an ``access.approve`` holder reads the queue, each
through its own policy on ``access_grants``. Every write — requesting, breaking
glass, deciding, revoking, withdrawing — runs on the system engine, which alone
writes the table; authorization for those is enforced here via capabilities +
ownership, mirroring the ``/operator/*`` endpoints.
"""

from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from webauthn.helpers import bytes_to_base64url

from app.api.deps import UserSessionDep, get_current_active_user, require_capability
from app.core.capabilities import Capability, user_has_capability
from app.core.audit_events import AuditEventType
from app.core.messages import AccessGrantMessages, AuthMessages
from app.db.session import get_system_session
from app.models.platform.user import User
from app.models.platform.access_grant import (
    AccessGrantPurpose,
    AccessLevel,
    SettingsLevel,
)
from app.schemas.platform.access_grant import (
    AccessGrantApprove,
    AccessGrantCreate,
    AccessGrantLimits,
    AccessGrantRead,
    BreakGlassCreate,
    SecondFactorAnswer,
    BreakGlassRequirements,
)
from app.schemas.platform.passkey import PasskeyAuthenticationOptions
from app.services import audit as audit_service
from app.services.auth import challenges as challenge_service
from app.services.auth import passkeys as passkey_service
from app.services.auth import totp as totp_service
from app.services.platform import access_grants as service
from app.services.content_sockets import sockets as content_sockets
from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter()

SystemSessionDep = Annotated[AsyncSession, Depends(get_system_session)]
AccessRequestDep = Annotated[
    User, Depends(require_capability(Capability.ACCESS_REQUEST))
]
AccessApproveDep = Annotated[
    User, Depends(require_capability(Capability.ACCESS_APPROVE))
]
# Break-glass is gated on data.bypass — the repurposed capability that lets an
# operator/owner self-issue an audited, time-bound grant instead of holding a
# standing all-guild bypass.
BreakGlassDep = Annotated[User, Depends(require_capability(Capability.DATA_BYPASS))]

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
    "ALREADY_LIVE": status.HTTP_409_CONFLICT,
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
    "ALREADY_LIVE": AccessGrantMessages.ALREADY_LIVE,
}


def _raise(error: service.AccessGrantError) -> None:
    raise HTTPException(
        status_code=_ERROR_STATUS.get(error.code, status.HTTP_400_BAD_REQUEST),
        detail=_ERROR_DETAIL.get(error.code, error.code),
    )


async def _one(grant, *, system_session: AsyncSession | None = None) -> AccessGrantRead:
    reads = await service.to_read([grant], system_session=system_session)
    return reads[0]


@router.post("/", response_model=AccessGrantRead, status_code=status.HTTP_201_CREATED)
async def create_access_request(
    payload: AccessGrantCreate,
    session: SystemSessionDep,
    current_user: AccessRequestDep,
) -> AccessGrantRead:
    """Request time-bound access to a guild (requires ``access.request``).

    A body may ask for content, settings, or both; each becomes its own pending
    grant so an approver decides about them separately and the log keeps them
    apart. The content one is returned, being the one a caller routes in under.
    """
    try:
        asked = await service.request_grants(
            session,
            requester=current_user,
            payload=payload,
            asks=payload.wanted,
        )
    except service.AccessGrantError as exc:
        _raise(exc)
    grant = asked[0]
    for requested in asked:
        await audit_service.record(
            session,
            event_type=AuditEventType.ACCESS_GRANT_REQUESTED,
            actor_user_id=current_user.id,
            guild_id=requested.guild_id,
            target_type="access_grant",
            target_id=requested.id,
            detail={
                "purpose": requested.purpose,
                "level": requested.access_level,
            },
        )
    read = await _one(grant, system_session=session)
    await session.commit()
    return read


_BREAK_GLASS_PURPOSES = (challenge_service.ChallengePurpose.break_glass,)


async def _answers_with_a_passkey(
    session: AsyncSession, *, actor: User, credential: dict
) -> bool:
    """Whether the assertion in this request answers for this account.

    The challenge it is held against was issued to the account by the begin
    route below and is spent here, so what it proves belongs to this request
    rather than to the session the request was made on — the same rule the
    code follows.
    """
    presented = await passkey_service.present_against_challenge(
        session,
        user_id=actor.id,
        credential=credential,
        purposes=_BREAK_GLASS_PURPOSES,
    )
    if isinstance(presented, passkey_service.PresentationRefused):
        if not presented.keep:
            await session.rollback()
        return False
    return True


async def check_second_factor(
    session: AsyncSession, *, actor: User, answer: SecondFactorAnswer, during: str
) -> None:
    """Take the account's own factor before a grant is self-issued.

    ``during`` names the errand in the audit line a refused answer writes.

    Asked for the way turning the factor off asks: against the request rather
    than against what the session remembers, so what answers is presented at
    the moment the grant is issued. Three things answer — a code from the
    authenticator, a recovery code, or one of the account's passkeys. The
    recovery code is there because an operator whose phone is gone is exactly
    who needs to reach a community; the passkey, because a holder who signs in
    with one has no reason to keep an authenticator app as well.
    """
    if not await service.demands_second_factor(session):
        return

    # Read once: a refused assertion may put the transaction back, and the row
    # this came from is not this function's to re-read afterwards.
    actor_id = actor.id

    if not (
        await totp_service.is_enrolled(session, user_id=actor_id)
        or await passkey_service.count_for_user(session, user_id=actor_id)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AccessGrantMessages.SECOND_FACTOR_ENROLMENT_REQUIRED,
        )

    if answer.passkey is not None:
        accepted = await _answers_with_a_passkey(
            session, actor=actor, credential=answer.passkey
        )
        method, refusal = "passkey", AccessGrantMessages.PASSKEY_INVALID
    elif answer.recovery_code:
        accepted = await totp_service.consume_recovery_code(
            session, user_id=actor_id, code=answer.recovery_code
        )
        method, refusal = "recovery_code", AuthMessages.RECOVERY_CODE_INVALID
    elif answer.code:
        accepted = await totp_service.verify_code(
            session, user_id=actor_id, code=answer.code
        )
        method, refusal = "totp", AuthMessages.TOTP_INVALID
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AccessGrantMessages.SECOND_FACTOR_REQUIRED,
        )

    if not accepted:
        await audit_service.record(
            session,
            event_type=AuditEventType.AUTH_SECOND_FACTOR_FAILED,
            actor_user_id=actor_id,
            detail={"method": method, "during": during},
        )
        await session.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=refusal)


@router.get("/break-glass", response_model=BreakGlassRequirements)
async def break_glass_requirements(
    session: SystemSessionDep,
    current_user: BreakGlassDep,
) -> BreakGlassRequirements:
    """What a break-glass request will be asked for.

    The form reads this to know whether to offer a code field, whether the
    caller has a factor to answer with, and the longest window it may ask for.
    """
    required = await service.demands_second_factor(session)
    return BreakGlassRequirements(
        second_factor_required=required,
        max_duration_minutes=service.break_glass_max_minutes(current_user.role),
        totp_enrolled=await totp_service.is_enrolled(session, user_id=current_user.id),
        passkey_enrolled=bool(
            await passkey_service.count_for_user(session, user_id=current_user.id)
        ),
    )


@router.post("/break-glass/passkey", response_model=PasskeyAuthenticationOptions)
async def begin_break_glass_passkey(
    session: SystemSessionDep,
    current_user: BreakGlassDep,
) -> PasskeyAuthenticationOptions:
    """Options for answering a break-glass request with one of this account's
    passkeys.

    The challenge is bound to the account and to this purpose, and the request
    that carries the assertion spends it. Presenting a key here adds nothing to
    the session it was made on: what it answers for is the grant.
    """
    credentials = await passkey_service.list_for_user(session, user_id=current_user.id)
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.PASSKEY_NOT_FOUND,
        )

    ceremony = passkey_service.begin_authentication(credentials=credentials)
    await challenge_service.create(
        session,
        user_id=current_user.id,
        purpose=challenge_service.ChallengePurpose.break_glass,
        value=bytes_to_base64url(ceremony.challenge),
    )
    await session.commit()
    return PasskeyAuthenticationOptions(options=ceremony.options)


@router.post(
    "/break-glass", response_model=AccessGrantRead, status_code=status.HTTP_201_CREATED
)
async def break_glass_access(
    payload: BreakGlassCreate,
    session: SystemSessionDep,
    current_user: BreakGlassDep,
) -> AccessGrantRead:
    """Self-issue a time-bound break-glass grant to a guild (requires
    ``data.bypass``).

    Repurposes the old standing all-guild bypass: instead of ambient god-mode,
    the holder records scoped, expiring, self-approved PAM grants in one step.
    The grants are the audit trail; the holder then routes into the guild via
    the normal PAM path until they expire.

    **Two grants, not one.** Write access to the community's content, and its
    settings at ``superadmin``. They are separate rows with separate purposes,
    so the log says which authority was exercised — and so that asking for one
    of them, rather than both, is what the ordinary request flow is for. The
    content grant is returned, being the one the caller routes in under; both
    are in the list.
    """
    await check_second_factor(
        session, actor=current_user, answer=payload, during="break_glass"
    )
    try:
        replaced = await service.reconcile_break_glass_pair(
            session, actor=current_user, payload=payload
        )
        grant = await service.break_glass(
            session,
            actor=current_user,
            payload=payload,
            level=AccessLevel.read_write.value,
        )
        settings_grant = await service.break_glass(
            session,
            actor=current_user,
            payload=payload,
            purpose=AccessGrantPurpose.settings,
            level=SettingsLevel.superadmin.value,
        )
        for prior in replaced:
            await audit_service.record(
                session,
                event_type=AuditEventType.ACCESS_GRANT_DECIDED,
                actor_user_id=current_user.id,
                guild_id=prior.guild_id,
                target_type="access_grant",
                target_id=prior.id,
                detail={
                    "purpose": prior.purpose,
                    "level": prior.access_level,
                    "decision": prior.status,
                    "replacement": "break_glass",
                },
            )
        # One line per grant, each naming its purpose and its rung, so the log
        # says what was taken and not merely that glass was broken.
        for issued in (grant, settings_grant):
            await audit_service.record(
                session,
                event_type=AuditEventType.ACCESS_GRANT_SELF_ISSUED,
                actor_user_id=current_user.id,
                guild_id=issued.guild_id,
                target_type="access_grant",
                target_id=issued.id,
                detail={
                    "purpose": issued.purpose,
                    "level": issued.access_level,
                    "self_approved": True,
                },
            )
    except service.AccessGrantError as exc:
        _raise(exc)
    read = await _one(grant, system_session=session)
    await session.commit()
    return read


@router.get("/", response_model=List[AccessGrantRead])
async def list_access_grants(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
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
    """List your own access grants.

    Ordered newest-first; ``limit``/``offset`` page the result so it can't grow
    unbounded, and ``live=true`` narrows to grants that are still within their
    window. The full queue is ``GET /access-grants/queue``.
    """
    grants = await service.list_grants(
        session,
        user_id=current_user.id,
        statuses=[grant_status] if grant_status else None,
        live_only=live,
        limit=limit,
        offset=offset,
    )
    return await service.to_read(grants)


@router.get("/queue", response_model=List[AccessGrantRead])
async def list_access_grant_queue(
    session: UserSessionDep,
    _approver: AccessApproveDep,
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
    """Every grant on the platform, for approvers (``access.approve``).

    Newest-first and paged like the caller's own list; ``live=true`` keeps only
    grants still within their window.
    """
    grants = await service.list_grants(
        session,
        statuses=[grant_status] if grant_status else None,
        live_only=live,
        limit=limit,
        offset=offset,
    )
    return await service.to_read(grants)


@router.get("/limits", response_model=AccessGrantLimits)
async def read_access_grant_limits(
    current_user: AccessRequestDep,
) -> AccessGrantLimits:
    """The longest grant the caller may ask for, as this deployment sets it."""
    return AccessGrantLimits(
        max_duration_minutes=service.max_minutes_for_role(current_user.role),
    )


@router.get("/{grant_id}", response_model=AccessGrantRead)
async def get_access_grant(
    grant_id: int,
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> AccessGrantRead:
    grant = await service.get_grant(session, grant_id)
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AccessGrantMessages.NOT_FOUND
        )
    # Owners of the request, or approvers, may view it.
    if grant.user_id != current_user.id and not user_has_capability(
        current_user, Capability.ACCESS_APPROVE
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AuthMessages.INSUFFICIENT_PRIVILEGES,
        )
    return await _one(grant)


@router.post("/{grant_id}/approve", response_model=AccessGrantRead)
async def approve_access_grant(
    grant_id: int,
    payload: AccessGrantApprove,
    session: SystemSessionDep,
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
    await audit_service.record(
        session,
        event_type=AuditEventType.ACCESS_GRANT_DECIDED,
        actor_user_id=current_user.id,
        guild_id=grant.guild_id,
        target_type="access_grant",
        target_id=grant.id,
        detail={
            "purpose": grant.purpose,
            "level": grant.access_level,
            "decision": "approved",
        },
    )
    read = await _one(grant, system_session=session)
    await session.commit()
    return read


@router.post("/{grant_id}/deny", response_model=AccessGrantRead)
async def deny_access_grant(
    grant_id: int,
    session: SystemSessionDep,
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
    await audit_service.record(
        session,
        event_type=AuditEventType.ACCESS_GRANT_DECIDED,
        actor_user_id=current_user.id,
        guild_id=grant.guild_id,
        target_type="access_grant",
        target_id=grant.id,
        detail={
            "purpose": grant.purpose,
            "level": grant.access_level,
            "decision": "denied",
        },
    )
    read = await _one(grant, system_session=session)
    await session.commit()
    return read


@router.post("/{grant_id}/revoke", response_model=AccessGrantRead)
async def revoke_access_grant(
    grant_id: int,
    session: SystemSessionDep,
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
    await audit_service.record(
        session,
        event_type=AuditEventType.ACCESS_GRANT_DECIDED,
        actor_user_id=current_user.id,
        guild_id=grant.guild_id,
        target_type="access_grant",
        target_id=grant.id,
        detail={
            "purpose": grant.purpose,
            "level": grant.access_level,
            "decision": "revoked",
        },
    )
    read = await _one(grant, system_session=session)
    await session.commit()
    # PAM access revoked — drop the grantee's live content streams in that guild
    # immediately, don't wait for the bounded re-auth tick.
    await content_sockets.revoke_user(grant.guild_id, grant.user_id)
    return read


@router.delete(
    "/{grant_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
async def cancel_access_request(
    grant_id: int,
    session: SystemSessionDep,
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
