import logging
from typing import Annotated, Literal, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status, Response
from sqlalchemy import case, func
from sqlmodel import select

from app.api.deps import UserSessionDep, require_capability, SystemSessionDep
from app.db.query import build_paginated_response, paginated_query
from app.core.audit_events import AuditEventType
from app.core.user_display import handle_of
from app.core.usernames import UsernameError
from app.core.capabilities import (
    Capability,
    capabilities_for,
    can_assign_role,
    role_rank,
)
from app.models.platform.user import User, UserStatus
from app.models.platform.user_token import UserTokenPurpose
from app.schemas.platform.user import (
    OperatorUserListResponse,
    OperatorUserRead,
    AccountDeletionResponse,
)
from app.schemas.platform.auth import VerificationSendResponse
from app.schemas.platform.operator import (
    OperatorSuspensionUpdate,
    OperatorUsernameUpdate,
    PlatformRoleUpdate,
    OperatorUserDeleteRequest,
    OperatorDeletionEligibilityResponse,
    GuildBlockerInfo,
)
from app.core.messages import (
    OperatorMessages,
    AuthMessages,
    SettingsMessages,
    UserMessages,
)
from app.services.platform import account_stream
from app.services.platform import user_tokens
from app.services.platform import csv_export
from app.services import email as email_service
from app.services.auth import challenges as challenge_service
from app.services.auth import sessions as session_service
from app.services.auth import sign_in_locks
from app.services.auth import totp as totp_service
from app.services.content_sockets import sockets as content_sockets
from app.services import notifications as notifications_service
from app.services.platform import user_avatars as user_avatars_service
from app.services import audit as audit_service
from app.services.platform import usernames as username_service
from app.services.platform import guilds as guilds_service
from app.services.platform import users as users_service

logger = logging.getLogger(__name__)

router = APIRouter()

# Per-capability guards. Each operator endpoint is gated on the specific
# capability it needs rather than a platform role name, so the privilege
# ladder (member → support → moderator → operator → owner) maps cleanly onto
# what each operation actually requires.
UsersReadDep = Annotated[User, Depends(require_capability(Capability.USERS_READ))]
UsersAgeUnblockDep = Annotated[
    User, Depends(require_capability(Capability.USERS_AGE_UNBLOCK))
]
UsersManageDep = Annotated[User, Depends(require_capability(Capability.USERS_MANAGE))]
ContentModerateDep = Annotated[
    User, Depends(require_capability(Capability.CONTENT_MODERATE))
]
UsersDeleteDep = Annotated[User, Depends(require_capability(Capability.USERS_DELETE))]
GuildsManageDep = Annotated[User, Depends(require_capability(Capability.GUILDS_MANAGE))]
RolesAssignDep = Annotated[User, Depends(require_capability(Capability.ROLES_ASSIGN))]
# App-wide configuration (OIDC, SMTP, branding, role labels, platform AI).
# Owner-only — imported by settings.py / ai_settings.py.
ConfigManageDep = Annotated[User, Depends(require_capability(Capability.CONFIG_MANAGE))]


#: Accounts ordered by how much of the app is left to them, so sorting on
#: status brings the ones needing attention together at one end.
_STATUS_RANK = {
    UserStatus.active: 0,
    UserStatus.suspended: 1,
    UserStatus.deactivated: 2,
    UserStatus.deleted: 3,
    UserStatus.anonymized: 4,
}

_USER_SORT_FIELDS = {
    "id": User.id,
    "username": User.username,
    "status": case(_STATUS_RANK, value=User.status, else_=len(_STATUS_RANK)),
}


@router.get("/users", response_model=OperatorUserListResponse)
async def list_all_users(
    session: UserSessionDep,
    _current_user: UsersReadDep,
    search: Optional[str] = Query(
        default=None,
        description=(
            "Matches the handle's name part; a whole handle (`foobar#1234`) "
            "pins one account."
        ),
    ),
    sort_by: Optional[Literal["id", "username", "status"]] = None,
    sort_dir: Literal["asc", "desc"] = "asc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> OperatorUserListResponse:
    """One page of the platform's accounts (``users.read``).

    Platform-scoped: runs on the role-scoped session (``platform_<tier>``), so the
    cross-user read is authorized by RLS (``users_platform_read``, support+) rather
    than the system engine. Initiative roles are guild-scoped and
    deliberately NOT loaded here — a platform user view exposes platform data only.

    Ordered by ``sort_by`` when given; otherwise nearest match first while
    searching, and oldest account first while not.
    """
    base = select(User)
    closest = None
    if search and (term := search.strip()):
        matches, closest = users_service.member_match(
            term, shows_names=False, profile=User
        )
        base = base.where(matches)

    if sort_by is not None:
        order = _USER_SORT_FIELDS[sort_by]
        data_stmt = base.order_by(
            order.desc() if sort_dir == "desc" else order.asc(), User.id.asc()
        )
    elif closest is not None:
        data_stmt = base.order_by(closest.desc(), User.id.asc())
    else:
        data_stmt = base.order_by(User.id.asc())

    users, total_count, actual_page = await paginated_query(
        session,
        data_stmt,
        select(func.count()).select_from(base.subquery()),
        page=page,
        page_size=page_size,
    )
    return OperatorUserListResponse(
        **build_paginated_response(
            await users_service.to_operator_read(users),
            total_count,
            actual_page,
            page_size,
        )
    )


#: ``email`` is masked here exactly as it is in the roster this exports, so
#: the two agree. The column stays because matching a row to an address you
#: were given is what it is read for.
_PLATFORM_CSV_HEADERS = [
    "user_id",
    "email",
    "full_name",
    "platform_role",
    "status",
    "email_verified",
    "created_at",
    "updated_at",
    "timezone",
    "locale",
]


@router.get("/users/export.csv")
async def export_platform_users_csv(
    session: UserSessionDep,
    current_user: UsersReadDep,
    user_id: Annotated[list[int] | None, Query()] = None,
) -> Response:
    """Export platform users as a CSV file. Pass `user_id` one or more times to
    restrict the export to a subset. Without `user_id`, every user is included.
    Support and above (``users.read``)."""
    stmt = select(User).order_by(User.created_at.asc())
    if user_id:
        stmt = stmt.where(User.id.in_(user_id))
    result = await session.exec(stmt)
    users = list(result.all())

    if user_id and not users:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )

    # Through the same shape the roster returns, so the export cannot be the one
    # place that forgets to mask an address.
    records = await users_service.to_operator_read(users)

    rows = []
    for record in records:
        rows.append(
            [
                record.id,
                record.email,
                record.full_name or "",
                record.role.value if hasattr(record.role, "value") else record.role,
                record.status.value
                if hasattr(record.status, "value")
                else record.status,
                record.email_verified,
                record.created_at.isoformat() if record.created_at else "",
                record.updated_at.isoformat() if record.updated_at else "",
                record.timezone or "",
                record.locale or "",
            ]
        )

    csv_bytes = csv_export.build_csv(_PLATFORM_CSV_HEADERS, rows)

    if len(users) == 1 and user_id:
        single_user = users[0]
        # Named by handle rather than address: a filename outlives the
        # download, appearing in directory listings and wherever it is sent on.
        filename = (
            f"user-{single_user.id}-"
            f"{csv_export.safe_filename_component(single_user.username)}.csv"
        )
    else:
        datestamp = datetime.now(timezone.utc).date().isoformat()
        filename = f"platform-users-{datestamp}.csv"

    # Nothing changed, so the endpoint has no commit of its own to ride: the
    # record is the whole write.
    await audit_service.record(
        session,
        event_type=AuditEventType.PLATFORM_USERS_EXPORTED,
        actor_user_id=current_user.id,
        detail={"count": len(users), "subset": bool(user_id)},
    )
    await session.commit()

    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/users/{user_id}/second-factor", status_code=status.HTTP_204_NO_CONTENT)
async def clear_second_factor(
    user_id: int,
    session: SystemSessionDep,
    current_user: UsersManageDep,
) -> None:
    """Remove somebody's second factor for them.

    The lost-phone path: the person cannot present the factor and cannot reach
    the recovery codes either, so somebody with the run of platform accounts
    takes it off and they enrol again.

    A clear, never a read — nothing here hands back the seed or the codes, to
    this caller or any other. Their sessions and any part-way sign-in go with
    it, and the account is told.
    """
    user = (await session.exec(select(User).where(User.id == user_id))).one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )
    if not await totp_service.is_enrolled(session, user_id=user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.TOTP_NOT_ENROLLED,
        )

    await totp_service.disable(session, user_id=user_id)
    await challenge_service.revoke_for_user(session, user_id=user_id)
    await session_service.revoke_all_for_user(session, user_id=user_id)
    await audit_service.record(
        session,
        event_type=AuditEventType.AUTH_SECOND_FACTOR_RESET,
        actor_user_id=current_user.id,
        target_user_id=user_id,
        target_type="user",
        target_id=user_id,
    )
    await session.commit()
    # Connections opened on the ended sessions close now.
    await content_sockets.revoke_user_everywhere(user_id)
    await email_service.announce_second_factor_change(session, user, enabled=False)


@router.post("/users/{user_id}/reset-password", response_model=VerificationSendResponse)
async def trigger_password_reset(
    user_id: int,
    session: SystemSessionDep,
    _current_user: UsersManageDep,
) -> VerificationSendResponse:
    """Trigger a password reset email for a user (``users.manage``)."""
    stmt = select(User).where(User.id == user_id)
    result = await session.exec(stmt)
    user = result.one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )

    if user.status != UserStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=OperatorMessages.CANNOT_RESET_INACTIVE,
        )

    try:
        token = await user_tokens.create_token(
            session,
            user_id=user.id,
            purpose=UserTokenPurpose.password_reset,
            expires_minutes=60,
        )
        await email_service.send_password_reset_email(session, user, token)
    except email_service.EmailNotConfiguredError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=SettingsMessages.SMTP_INCOMPLETE,
        ) from None
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    return VerificationSendResponse(status="sent")


@router.post("/users/{user_id}/reactivate", response_model=OperatorUserRead)
async def reactivate_user(
    user_id: int,
    session: SystemSessionDep,
    _current_user: UsersManageDep,
) -> OperatorUserRead:
    """Reactivate a deactivated user account (``users.manage``)."""
    stmt = select(User).where(User.id == user_id)
    result = await session.exec(stmt)
    user = result.one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )

    if user.status == UserStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=OperatorMessages.USER_ALREADY_ACTIVE,
        )

    if user.status == UserStatus.anonymized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.CANNOT_REACTIVATE_ANONYMIZED,
        )

    user.status = UserStatus.active
    user.updated_at = datetime.now(timezone.utc)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    # Platform user management stays platform-table-only: initiative
    # membership is guild-schema content this path cannot read.
    return await users_service.to_operator_read_one(user)


@router.post("/users/{user_id}/restore", response_model=OperatorUserRead)
async def restore_deleted_user(
    user_id: int,
    session: SystemSessionDep,
    current_user: UsersManageDep,
) -> OperatorUserRead:
    """Call off a pending erasure from the users table (``users.manage``).

    The account's holder can do this themselves simply by signing in, which is
    the ordinary way it happens. This is for when they cannot — the address is
    gone, the phone is gone, they asked somebody — and for an operator undoing
    a deletion they made on somebody's behalf.

    Nothing is restored as such: the account never lost anything. It kept its
    memberships, its initiative roles and the documents it owns for the whole
    window, so this puts it back exactly where it was.

    Separate from ``reactivate``, which is for a *deactivated* account and
    gives back an account with no communities — the memberships that one
    dropped are not coming back.
    """
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )
    if user.status != UserStatus.deleted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=OperatorMessages.USER_NOT_DELETED,
        )
    await users_service.cancel_account_deletion(
        session, user_id, actor_user_id=current_user.id, via="operator"
    )
    await session.commit()
    await session.refresh(user)
    return await users_service.to_operator_read_one(user)


@router.delete("/users/{user_id}/avatar", status_code=status.HTTP_204_NO_CONTENT)
async def remove_user_avatar(
    user_id: int,
    session: SystemSessionDep,
    current_user: ContentModerateDep,
) -> Response:
    """Take down a user's profile picture.

    People occasionally upload images that breach the terms of use, so removal
    cannot wait for the uploader to do it. Gated on ``content.moderate``, which
    is a platform capability — a guild admin is a tenancy role and has no part
    in this, so a guild's administrator cannot reach a member's profile image.

    Removal only. There is deliberately no path by which one account sets
    another account's picture.

    The bytes are destroyed rather than hidden. Runs on the system engine
    because the row policies scope every request-path write to the caller's own
    avatar, so nothing in the schema grants this — the capability check above
    is the whole authorization.
    """
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )

    # An externally hosted picture is the same surface by another route, so a
    # takedown that left it in place would not be one: both go.
    had_picture = bool(user.avatar_url)
    removed = await user_avatars_service.delete_avatar(
        session, user_id=user_id, user=user
    )
    if user.avatar_url:
        user.avatar_url = None
        session.add(user)

    if removed or had_picture:
        # Queued before the commit, not after it: silent removal reads as a
        # bug, so the picture going and the person being told are one write.
        await notifications_service.queue_avatar_removed(session, user=user)
        # Recorded in the same transaction, for the same reason: the takedown
        # and the record of who did it commit together or not at all.
        await audit_service.record(
            session,
            event_type=AuditEventType.USER_AVATAR_REMOVED,
            actor_user_id=current_user.id,
            target_user_id=user_id,
            target_type="user",
            target_id=user_id,
        )

    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/users/{user_id}/username", response_model=OperatorUserRead)
async def set_user_username(
    user_id: int,
    payload: OperatorUsernameUpdate,
    session: SystemSessionDep,
    current_user: ContentModerateDep,
) -> OperatorUserRead:
    """Change someone's username.

    People occasionally pick a handle that breaches the terms of use, and it is
    the one part of an account everyone else sees, so changing it cannot wait
    for its owner. Gated on ``content.moderate`` — a platform capability, like
    the picture takedown beside it; a guild's administrator has no part in this.

    The name part is validated exactly as registration validates it. The number
    is not the moderator's to choose either: the existing one is kept, and a
    new one drawn only if that pair is already held.

    This also marks the handle as chosen, so its owner cannot immediately spend
    a pick on undoing a moderation decision.
    """
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )

    previous_handle = handle_of(user)
    try:
        await username_service.set_for_user(
            session, user=user, name=payload.username, keep_discriminator=True
        )
    except UsernameError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.code
        ) from exc

    user.updated_at = datetime.now(timezone.utc)
    session.add(user)
    await notifications_service.queue_username_changed(
        session, user=user, previous_handle=previous_handle
    )
    await audit_service.record(
        session,
        event_type=AuditEventType.USER_USERNAME_CHANGED,
        actor_user_id=current_user.id,
        target_user_id=user_id,
        target_type="user",
        target_id=user_id,
        detail={"from": previous_handle, "to": handle_of(user)},
    )
    await session.commit()
    await session.refresh(user)
    return await users_service.to_operator_read_one(user)


@router.post("/users/{user_id}/suspension", response_model=OperatorUserRead)
async def set_user_suspension(
    user_id: int,
    payload: OperatorSuspensionUpdate,
    session: SystemSessionDep,
    current_user: UsersManageDep,
) -> OperatorUserRead:
    """Freeze an account, or let it go.

    Suspension takes nothing away: memberships, grants, assignments and
    everything the account authored stay exactly where they are, so lifting it
    restores the account whole. What it does is close every guild — the holder
    still signs in and reaches their own account, which is how they can be told
    why.

    Gated on ``users.manage`` (moderator and above). No PAM grant is involved:
    this is a platform action about an account, not access to a guild's
    content.
    """
    if user_id == current_user.id:
        # Suspending yourself would take your own guilds away and leave the
        # lifting of it to someone else.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=OperatorMessages.CANNOT_SUSPEND_SELF,
        )

    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )

    # A closed or erased account is not a live one to freeze, and thawing it
    # would quietly reopen an account its owner closed.
    if user.status not in (UserStatus.active, UserStatus.suspended):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=OperatorMessages.CANNOT_SUSPEND_INACTIVE,
        )

    # The same bound as a role change: nobody acts on an account that outranks
    # them, in either direction. An owner is therefore suspended only by another
    # owner, who stays behind holding config-management.
    if role_rank(user.role) > role_rank(current_user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=OperatorMessages.CANNOT_SUSPEND_HIGHER_ROLE,
        )

    already = user.status == UserStatus.suspended
    if already == payload.suspended:
        return await users_service.to_operator_read_one(user)

    user.status = UserStatus.suspended if payload.suspended else UserStatus.active
    user.updated_at = datetime.now(timezone.utc)
    user.status_changed_at = user.updated_at
    session.add(user)

    if payload.suspended:
        await notifications_service.queue_account_suspended(
            session, user=user, reason=payload.reason
        )
    else:
        await notifications_service.queue_account_unsuspended(session, user=user)

    await audit_service.record(
        session,
        event_type=(
            AuditEventType.USER_SUSPENDED
            if payload.suspended
            else AuditEventType.USER_UNSUSPENDED
        ),
        actor_user_id=current_user.id,
        target_user_id=user_id,
        target_type="user",
        target_id=user_id,
        detail={"reason": payload.reason} if payload.reason else {},
    )
    await session.commit()
    await session.refresh(user)

    if payload.suspended:
        # Sockets opened before this carry the account as it was when they
        # joined, so they are re-checked now rather than at the next sweep.
        # Everywhere at once: this is a change to the account, which has no one
        # guild to name.
        await content_sockets.revoke_user_everywhere(user_id)

    return await users_service.to_operator_read_one(user)


@router.delete("/users/{user_id}/sign-in-lock", response_model=OperatorUserRead)
async def lift_sign_in_lock(
    user_id: int,
    session: SystemSessionDep,
    current_user: UsersManageDep,
) -> OperatorUserRead:
    """Turn an account's password and code sign-in back on.

    Wrong passwords or codes turn them off: for fifteen minutes at a time, and
    until somebody lifts it once the locks add up. This lifts either, and
    starts the count over.

    Gated on ``users.manage`` (moderator and above), like a suspension.
    """
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )
    if not await sign_in_locks.lift(session, user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.SIGN_IN_NOT_LOCKED,
        )

    await audit_service.record(
        session,
        event_type=AuditEventType.USER_SIGN_IN_LOCK_LIFTED,
        actor_user_id=current_user.id,
        target_user_id=user_id,
        target_type="user",
        target_id=user_id,
        detail={},
    )
    await session.commit()
    return await users_service.to_operator_read_one(user)


@router.delete("/users/{user_id}/age-block", response_model=OperatorUserRead)
async def clear_age_block(
    user_id: int,
    session: SystemSessionDep,
    current_user: UsersAgeUnblockDep,
) -> OperatorUserRead:
    """Let an account answer the age question again.

    An account that answered as under age keeps that answer, and the question
    is not re-asked — otherwise it is not a question. This is the way back for
    the case that is nearly all of them: a mistyped year. It clears the record
    of the answer and nothing else; the account answers again from scratch, and
    the deployment has no more idea of anybody's birthday than it did before.

    Gated on ``users.age_unblock``, which the support tier holds — the lowest
    rung, because getting somebody back into their account after a typo is
    support work rather than a moderation decision. Recorded either way: it is
    one person restoring another's access, which is exactly the kind of thing
    a log is for.
    """
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )
    if user.age_below_minimum_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.AGE_NOT_BLOCKED,
        )

    user.age_below_minimum_at = None
    user.updated_at = datetime.now(timezone.utc)
    session.add(user)

    await audit_service.record(
        session,
        event_type=AuditEventType.USER_AGE_BLOCK_CLEARED,
        actor_user_id=current_user.id,
        target_user_id=user_id,
        target_type="user",
        target_id=user_id,
        detail={},
    )
    # The question is theirs to answer again, so their open tabs re-read the
    # account and meet the form rather than the wall.
    account_stream.queue_account_signal(session, user_id, "age")
    await session.commit()
    await session.refresh(user)
    return await users_service.to_operator_read_one(user)


@router.patch("/users/{user_id}/platform-role", response_model=OperatorUserRead)
async def update_platform_role(
    user_id: int,
    payload: PlatformRoleUpdate,
    session: SystemSessionDep,
    current_user: RolesAssignDep,
) -> OperatorUserRead:
    """Update a user's platform role (``roles.assign``).

    Restrictions:
    - Cannot change your own role
    - Cannot demote the last owner
    """
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=OperatorMessages.CANNOT_CHANGE_OWN_ROLE,
        )

    stmt = select(User).where(User.id == user_id).with_for_update()
    result = await session.exec(stmt)
    user = result.one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )

    # Refuse role changes on non-active accounts. A deactivated row's role
    # change is meaningless until the user is reactivated, and an
    # anonymized row should never gain or lose elevated privileges (the
    # account is permanently gone). The last-owner check counts active
    # holders only, so promoting a husk would also confuse it.
    if user.status != UserStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=OperatorMessages.CANNOT_CHANGE_ROLE_INACTIVE,
        )

    # Bounded delegation: you may only assign a role whose capabilities are a
    # subset of your own, and you may not modify a user who already outranks
    # you (an operator can't touch an owner, in either direction).
    if not can_assign_role(current_user, payload.role) or not can_assign_role(
        current_user, user.role
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=OperatorMessages.CANNOT_ASSIGN_HIGHER_ROLE,
        )

    # Don't strip config-management from the last user who has it — that would
    # lock the platform out of its own configuration. (FOR UPDATE acquired above.)
    losing_config = Capability.CONFIG_MANAGE in capabilities_for(
        user.role
    ) and Capability.CONFIG_MANAGE not in capabilities_for(payload.role)
    if losing_config:
        if await users_service.is_last_capability_holder(
            session, user_id, Capability.CONFIG_MANAGE, for_update=True
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=OperatorMessages.CANNOT_DEMOTE_LAST_OWNER,
            )

    previous_role = user.role
    user.role = payload.role
    user.updated_at = datetime.now(timezone.utc)
    session.add(user)
    await audit_service.record(
        session,
        event_type=AuditEventType.USER_PLATFORM_ROLE_CHANGED,
        actor_user_id=current_user.id,
        target_user_id=user_id,
        target_type="user",
        target_id=user_id,
        detail={"from": previous_role.value, "to": payload.role.value},
    )
    # What this account may do just changed, and it was not their doing. Their
    # open tabs re-read it rather than showing a rung they no longer hold.
    account_stream.queue_account_signal(session, user_id, "role")
    await session.commit()
    await session.refresh(user)
    # Platform user management stays platform-table-only (see reactivate).
    return await users_service.to_operator_read_one(user)


@router.get(
    "/users/{user_id}/deletion-eligibility",
    response_model=OperatorDeletionEligibilityResponse,
)
async def check_user_deletion_eligibility(
    user_id: int,
    session: SystemSessionDep,
    current_user: UsersDeleteDep,
) -> OperatorDeletionEligibilityResponse:
    """Check if a user can be deleted (``users.delete``).

    Returns the blockers: the communities the user holds the only superadmin
    seat of. That is the only one: owning content does not stop a deletion,
    because ownership is released on the way out and the content is left
    unowned for a guild admin to claim.
    """
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=OperatorMessages.USE_SELF_DELETION,
        )

    stmt = select(User).where(User.id == user_id)
    result = await session.exec(stmt)
    user = result.one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )

    can_delete, blockers = await users_service.check_deletion_eligibility(
        session, user_id, operator_context=True
    )

    # Check if target is the last platform owner (last config manager)
    if Capability.CONFIG_MANAGE in capabilities_for(user.role):
        if await users_service.is_last_capability_holder(
            session, user_id, Capability.CONFIG_MANAGE
        ):
            blockers.append(
                "User is the last platform owner. Promote another user first."
            )
            can_delete = False

    return OperatorDeletionEligibilityResponse(
        can_delete=can_delete,
        blockers=blockers,
        guild_blockers=[
            GuildBlockerInfo(guild_id=guild_id, guild_name=guild_name)
            for guild_id, guild_name in await guilds_service.stranded_seats(
                session, user_id=user_id
            )
        ],
    )


@router.delete("/users/{user_id}", response_model=AccountDeletionResponse)
async def delete_user(
    user_id: int,
    payload: OperatorUserDeleteRequest,
    session: SystemSessionDep,
    current_user: UsersDeleteDep,
) -> AccountDeletionResponse:
    """Delete, anonymize, or deactivate a user account (``users.delete``).

    `action` selects the path:
      - `deactivate` — reversible; flips status to deactivated, drops memberships.
      - `soft_delete` — anonymizes PII; keeps the row so historical FKs still resolve.
      - `hard_delete` — permanently removes the row and cascades cleanup.

    For both `soft_delete` and `hard_delete`, projects the user solely owns
    must be transferred — only owners hold certain permissions, and an
    anonymized owner row can't act on them.

    Restrictions:
    - Cannot delete yourself (use /users/me/delete-account)
    - Cannot delete the last owner
    """
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=OperatorMessages.CANNOT_DELETE_SELF,
        )

    stmt = select(User).where(User.id == user_id).with_for_update()
    result = await session.exec(stmt)
    user = result.one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )

    # Check if target is the last platform owner (last config manager)
    if Capability.CONFIG_MANAGE in capabilities_for(user.role):
        if await users_service.is_last_capability_holder(
            session, user_id, Capability.CONFIG_MANAGE, for_update=True
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=OperatorMessages.CANNOT_DELETE_LAST_OWNER,
            )

    # Holding a guild's only superadmin seat is the only blocker. Content the
    # user owns is released as their memberships go and left unowned for a guild
    # admin to claim, so there is nothing for this endpoint to collect first.
    can_delete, blockers = await users_service.check_deletion_eligibility(
        session, user_id, operator_context=True
    )
    if not can_delete:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=blockers[0] if blockers else OperatorMessages.USER_CANNOT_BE_DELETED,
        )

    # An already-anonymized row is a permanently empty husk; the only
    # valid follow-up is hard delete. Refuse deactivate / soft_delete
    # explicitly — without this guard, deactivate would flip
    # ``anonymized`` → ``deactivated``, which then satisfies the
    # ``reactivate`` endpoint's anonymized check and lets an operator
    # accidentally resurrect the husk as an active loginable account.
    if user.status == UserStatus.anonymized and payload.action != "hard_delete":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=OperatorMessages.ALREADY_ANONYMIZED,
        )

    if payload.action == "deactivate":
        await users_service.deactivate_user(
            session, user_id, actor_user_id=current_user.id
        )
        return AccountDeletionResponse(
            success=True,
            action="deactivate",
            message=f"User {user.username} has been deactivated",
        )

    if payload.action == "soft_delete":
        # The same windowed deletion the account holder gets from their own
        # danger zone. One meaning for the word on both surfaces, and the
        # reversible action is the one that is easy to reach — ``hard_delete``
        # below is the one that is not.
        await users_service.request_account_deletion(
            session, user_id, actor_user_id=current_user.id
        )
        return AccountDeletionResponse(
            success=True,
            action="soft_delete",
            message=f"User {user.username} has been deleted",
        )

    # hard_delete: ownership is released as the memberships go, and the
    # authorship columns are re-pointed at the system user because the row they
    # named is about to stop existing.
    await users_service.hard_delete_user(
        session, user_id, actor_user_id=current_user.id
    )
    return AccountDeletionResponse(
        success=True,
        action="hard_delete",
        message=f"User {user.username} has been permanently deleted",
    )
