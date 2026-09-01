import logging
from datetime import datetime, timezone
from typing import Annotated, List, Optional, Sequence

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import String, cast, func, or_
from sqlmodel import select

from app.api.deps import (
    RLSSessionDep,
    SessionDep,
    UserSessionDep,
    get_current_active_user,
    get_guild_membership,
    GuildContext,
    require_guild_roles,
)
from app.api.v1.platform_endpoints.session_cookies import (
    clear_refresh_cookie,
    set_refresh_cookie,
    set_session_cookie,
)
from app.core.config import settings
from app.core.password_policy import enforce_password_policy
from app.core import usernames
from app.core.user_display import handle_of
from app.core.usernames import UsernameError
from app.core.rate_limit import get_inet_client_ip
from app.core.security import (
    create_access_token,
    get_password_hash,
    mint_access_token,
    verify_password,
)
from app.core.user_input_validators import (
    normalize_notification_time,
    normalize_reminder_minutes,
    normalize_timezone,
    normalize_week_starts_on,
)
from app.db.session import get_admin_session, set_rls_context
from sqlmodel.ext.asyncio.session import AsyncSession
from app.models.platform.guild import GuildRole, GuildMembership
from app.models.tenant.initiative import InitiativeMember
from app.models.platform.user import User, UserStatus
from app.models.tenant.reaction_digest import ReactionDigestItem
from app.models.tenant.task_assignment_digest import TaskAssignmentDigestItem
from app.schemas.platform.user import (
    UsernameClaim,
    UserGuildMember,
    UserProfile,
    UserRead,
    UserSelfUpdate,
    UserSummary,
    UserSummaryListResponse,
    AccountDeletionRequest,
    AccountDeletionResponse,
    DeletionEligibilityResponse,
    UserPublic,
)
from app.schemas.platform.api_key import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyListResponse,
)
from app.schemas.tenant.ownership import (
    OwnedContentItem,
    OwnedContentResponse,
    OwnershipTransferRequest,
    OwnershipTransferResponse,
)
from app.schemas.tenant.stats import UserStatsResponse
from app.core.messages import AuthMessages, UserMessages
from app.services import notifications as notifications_service
from app.services.auth import sessions as session_service
from app.services.auth.identity import has_federated_identity
from app.services.tenant import app_connections as app_connections_service
from app.services.tenant import app_delegations as app_delegations_service
from app.services.tenant import app_revocation as app_revocation_service
from app.services.tenant import initiatives as initiatives_service
from app.services.tenant import ownership as ownership_service
from app.services.platform import guilds as guilds_service
from app.services.platform import usernames as username_service
from app.services.platform.guilds import adopt_guild_name_display
from app.services.realtime import manager as realtime_manager
from app.services.stream_authz import authority as stream_authority
from app.models.platform.user_avatar import AVATAR_MAX_BYTES
from app.services.platform import user_avatars as user_avatars_service
from app.services.platform import users as users_service
from app.services.platform import api_keys as api_keys_service
from app.services.platform import csv_export
from app.services.tenant import stats_service
from app.services.platform import user_tokens as user_tokens_service
from app.services.tenant import recent_views as recent_views_service
from app.db.query import MAX_ID_FILTER_VALUES, page_has_next, paginated_query

# Allowed values for the optional "task completion visual feedback" effect.
# Mirrored on the frontend in src/lib/taskCompletionVisualFeedback.ts; keep
# the two lists in sync if you add a new effect.
TASK_COMPLETION_VISUAL_FEEDBACK_VALUES: frozenset[str] = frozenset(
    {"none", "confetti", "heart", "d20", "gold_coin", "random"}
)

logger = logging.getLogger(__name__)

router = APIRouter()
# Cross-guild "my" aggregate (user stats). Mounted under /api/v1/me; user-scoped
# (no guild context), with an optional guild_id filter.
me_router = APIRouter()
# Guild-scoped member management (guild-admin lists/creates/approves/removes
# members of one guild). Mounted under /g/{guild_id}/users — the /me/* and
# platform user endpoints stay on ``router`` (top-level /users).
guild_router = APIRouter()

AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]
GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]
GuildAdminContext = Annotated[
    GuildContext, Depends(require_guild_roles(GuildRole.admin))
]


@router.get("/me", response_model=UserRead)
async def read_users_me(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserRead:
    # No initiative_roles enrichment: initiative membership is guild-schema
    # content, which a platform-path request cannot (and must not) read.
    # Guild-scoped rosters (/g/{guild_id}/users/) still serve it; clients
    # derive per-guild manager state from guild-scoped initiative data.
    payload = UserRead.model_validate(current_user)
    # Own-row read on the platform-tier session: whether any external identity
    # is linked (drives the "SSO account" affordances in the profile UI).
    payload.has_federated_identity = await has_federated_identity(
        session, user_id=current_user.id
    )
    return payload


@me_router.get("/stats", response_model=UserStatsResponse)
async def get_user_stats(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_id: Optional[int] = Query(
        default=None, description="Optional guild ID to filter stats"
    ),
    days: int = Query(
        default=90, ge=1, le=365, description="Number of days to analyze"
    ),
) -> UserStatsResponse:
    """Get comprehensive statistics for the current user."""
    stats = await stats_service.get_user_stats(
        session,
        user=current_user,
        guild_id=guild_id,
        days=days,
    )
    return stats


@guild_router.get("/", response_model=List[UserGuildMember])
async def list_users(
    session: RLSSessionDep,
    _current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[UserGuildMember]:
    stmt = (
        select(User, GuildMembership.role, GuildMembership.oidc_managed)
        .join(GuildMembership, GuildMembership.user_id == User.id)
        .where(
            GuildMembership.guild_id == guild_context.guild_id,
            users_service.visible_to_other_people(),
        )
        .order_by(User.created_at.asc())
    )
    result = await session.exec(stmt)
    rows = result.all()
    users = [row[0] for row in rows]
    await initiatives_service.load_user_initiative_roles(session, users)

    # Build response with guild_role and oidc_managed
    response = []
    for user, guild_role, oidc_managed in rows:
        member = UserGuildMember.model_validate(user)
        member.guild_role = guild_role.value
        member.oidc_managed = oidc_managed
        # Copy initiative_roles from loaded user
        member.initiative_roles = getattr(user, "initiative_roles", [])
        response.append(member)
    return response


@guild_router.get("/search", response_model=UserSummaryListResponse)
async def search_users(
    session: RLSSessionDep,
    _current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    search: Optional[str] = Query(
        default=None,
        description=(
            "Matches the handle's name part. Type the whole handle "
            "(`foobar#1234`) to pin one member; a partial number after `#` is a "
            "prefix of the four digits as rendered. Real names are matched only "
            "in a guild that shows them."
        ),
    ),
    user_id: Annotated[list[int] | None, Query(max_length=MAX_ID_FILTER_VALUES)] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=0, le=100),
) -> UserSummaryListResponse:
    """Slim, searchable, paginated roster for typeahead/pickers.

    Same authorization as the full member list (``RLSSessionDep`` +
    ``GuildContextDep``, membership re-validated per request): the params
    are additive filters on an already-RLS-gated query, so they only ever
    narrow the row set. Returns :class:`UserSummary` (no email, roles, or
    ``initiative_roles`` enrichment) instead of the heavy ``UserGuildMember``.

    Pass ``user_id`` one or more times to resolve a known selection (a picker
    rehydrating stored ids into names/avatars) rather than searching.
    """
    base = (
        select(User)
        .join(GuildMembership, GuildMembership.user_id == User.id)
        .where(
            GuildMembership.guild_id == guild_context.guild_id,
            users_service.visible_to_other_people(),
        )
    )
    shows_names = bool(guild_context.guild.show_member_names)
    #: Set while searching by name, and then what the page is ordered by.
    closest = None
    if search and (term := search.strip()):
        name_part, number = usernames.parse_handle(term)
        if number is not None:
            # The whole handle was typed: this member, not a family of them.
            base = base.where(
                func.lower(User.username) == name_part.lower(),
                func.lpad(cast(User.discriminator, String), 4, "0").like(f"{number}%"),
            )
        else:
            matches = User.username.ilike(f"%{name_part}%")
            if shows_names:
                # A name is searchable exactly where it is showable.
                matches = or_(matches, User.full_name.ilike(f"%{name_part}%"))
            # ...and a name typed nearly right still finds the person. Reading
            # a roster is how you learn a colleague's spelling, so requiring it
            # first is the wrong way round.
            closest = users_service.name_closeness(name_part, shows_names=shows_names)
            matches = or_(matches, closest >= users_service.MEMBER_MATCH_THRESHOLD)
            base = base.where(matches)
    if user_id:
        base = base.where(User.id.in_(user_id))

    count_stmt = select(func.count()).select_from(base.subquery())
    # Nearest first while searching; alphabetical when reading the roster.
    if closest is not None:
        order = (closest.desc(),)
    elif shows_names:
        order = (User.full_name.asc(),)
    else:
        order = ()
    data_stmt = base.order_by(
        *order, User.username.asc(), User.discriminator.asc(), User.id.asc()
    )

    users, total_count, actual_page = await paginated_query(
        session, data_stmt, count_stmt, page=page, page_size=page_size
    )

    return UserSummaryListResponse(
        items=[UserSummary.model_validate(user) for user in users],
        total_count=total_count,
        page=actual_page,
        page_size=page_size,
        has_next=page_has_next(actual_page, page_size, total_count),
        has_prev=actual_page > 1,
    )


@guild_router.get("/{user_id}/profile", response_model=UserProfile)
async def read_member_profile(
    user_id: int,
    session: RLSSessionDep,
    _current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> UserProfile:
    """One member's profile, as the rest of their guild sees it.

    Guild-scoped, like the roster it is reached from: the membership join is
    what says a profile exists to the caller, so someone the caller shares no
    guild with is a 404 rather than a page. It is also what makes the answer
    correct — a real name renders only where the guild shows names, and
    "online" means "has this guild open".

    Nothing here is a guild's to write. The account row is the person's own
    (``users`` UPDATE is own-row on the request path); this reads it.
    """
    stmt = (
        select(User, GuildMembership.joined_at)
        .join(GuildMembership, GuildMembership.user_id == User.id)
        .where(
            User.id == user_id,
            GuildMembership.guild_id == guild_context.guild_id,
            users_service.visible_to_other_people(),
        )
    )
    row = (await session.exec(stmt)).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=UserMessages.NOT_IN_GUILD,
        )
    user, joined_at = row
    return UserProfile(
        id=user.id,
        username=user.username,
        discriminator=user.discriminator,
        full_name=user.full_name,
        avatar_url=user.avatar_url,
        status=user.status,
        custom_status_emoji=user.custom_status_emoji,
        custom_status_text=user.custom_status_text,
        profile_decorations=user.profile_decorations or {},
        online=realtime_manager.is_present(guild_context.guild_id, user.id),
        joined_at=joined_at,
    )


_GUILD_CSV_HEADERS = [
    "user_id",
    "handle",
    "full_name",
    "guild_role",
    "platform_role",
    "oidc_managed",
    "status",
    "email_verified",
    "created_at",
    "initiative_roles",
]


@guild_router.get("/export.csv")
async def export_users_csv(
    session: RLSSessionDep,
    guild_context: GuildAdminContext,
    user_id: Annotated[list[int] | None, Query()] = None,
) -> Response:
    """Export guild members as a CSV file. Pass `user_id` one or more times to
    restrict the export to a subset. Without `user_id`, all visible members are
    included. Guild-admin only."""
    stmt = (
        select(User, GuildMembership.role, GuildMembership.oidc_managed)
        .join(GuildMembership, GuildMembership.user_id == User.id)
        .where(GuildMembership.guild_id == guild_context.guild_id)
        .order_by(User.created_at.asc())
    )
    if user_id:
        stmt = stmt.where(User.id.in_(user_id))
    result = await session.exec(stmt)
    rows = result.all()

    if user_id and not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )

    users = [row[0] for row in rows]
    await initiatives_service.load_user_initiative_roles(session, users)

    shows_names = bool(guild_context.guild.show_member_names)
    csv_rows = []
    for user, guild_role, oidc_managed in rows:
        csv_rows.append(
            [
                user.id,
                handle_of(user),
                (user.full_name or "") if shows_names else "",
                guild_role.value,
                user.role.value if hasattr(user.role, "value") else user.role,
                oidc_managed,
                user.status.value if hasattr(user.status, "value") else user.status,
                user.email_verified,
                user.created_at.isoformat() if user.created_at else "",
                csv_export.format_initiative_roles(user),
            ]
        )

    csv_bytes = csv_export.build_csv(_GUILD_CSV_HEADERS, csv_rows)

    if len(rows) == 1 and user_id:
        single_user = rows[0][0]
        filename = (
            f"user-{single_user.id}-"
            f"{csv_export.safe_filename_component(single_user.username)}.csv"
        )
    else:
        guild_slug = csv_export.safe_filename_component(
            guild_context.guild.name or "guild"
        )
        datestamp = datetime.now(timezone.utc).date().isoformat()
        filename = f"{guild_slug}-users-{datestamp}.csv"

    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


#: The digest queues a preference update can empty: the two channel fields
#: that feed each one, and the table it drains. One entry per digest, so a new
#: digest is cleaned up on opt-out by being listed here.
_DIGEST_QUEUES: tuple[tuple[str, str, type], ...] = (
    ("email_task_assignment", "push_task_assignment", TaskAssignmentDigestItem),
    ("email_comment_reactions", "push_comment_reactions", ReactionDigestItem),
)


def _emptied_digest_queues(user: User, update_data: dict) -> list[type]:
    """The queue tables this update leaves nobody wanting.

    Email and push share one queue per digest, so it is discarded only on the
    transition to BOTH being off — never when just one channel is switched off.
    """

    def _next(field: str) -> bool | None:
        value = update_data.get(field)
        return getattr(user, field) if value is None else value

    emptied: list[type] = []
    for email_field, push_field, model in _DIGEST_QUEUES:
        was_on = notifications_service.wants_digest(
            getattr(user, email_field), getattr(user, push_field)
        )
        now_on = notifications_service.wants_digest(
            _next(email_field), _next(push_field)
        )
        if was_on and not now_on:
            emptied.append(model)
    return emptied


@router.patch("/me/username", response_model=UserRead)
async def claim_my_username(
    payload: UsernameClaim,
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserRead:
    """Pick the handle for an account that was assigned one.

    Every account created without a form — provisioned from SSO claims, or
    carried over from before handles existed — starts with one it did not
    choose, and picks its own here. Once picked, a handle changes only through
    a moderator.
    """
    if current_user.username_chosen:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=UserMessages.USERNAME_ALREADY_CHOSEN,
        )

    try:
        await username_service.claim_for_user(
            session, user=current_user, name=payload.username
        )
    except UsernameError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.code
        ) from exc

    current_user.updated_at = datetime.now(timezone.utc)
    session.add(current_user)
    await session.commit()
    await session.refresh(current_user)
    return UserRead.model_validate(current_user)


@router.patch("/me", response_model=UserRead)
async def update_users_me(
    request: Request,
    user_in: UserSelfUpdate,
    session: UserSessionDep,
    admin_session: AdminSessionDep,
    response: Response,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserRead:
    update_data = user_in.model_dump(exclude_unset=True)
    # Fetched once: feeds both the password-gate exemption and the response
    # payload (identities can't change within this request).
    is_sso_account = await has_federated_identity(
        admin_session, user_id=current_user.id
    )
    if not update_data:
        payload = UserRead.model_validate(current_user)
        payload.has_federated_identity = is_sso_account
        return payload

    emptied_queues = _emptied_digest_queues(current_user, update_data)
    if emptied_queues:
        # A digest queue is guild-scoped, so it must be cleared inside each
        # of the user's guild schemas — before any mutation below, because the
        # fan-out expunges the identity map (per-schema ids collide). Restore
        # the platform context and re-fetch the user afterwards; the deletes
        # ride this request's transaction and commit with it.
        user_id = current_user.id
        await notifications_service.clear_digest_queue_across_guilds(
            session, user_id, emptied_queues
        )
        await set_rls_context(session, user_id=user_id)
        current_user = (
            await session.exec(select(User).where(User.id == user_id))
        ).one()

    new_full_name = update_data.get("full_name")
    if new_full_name is not None:
        current_user.full_name = new_full_name or None

    password = update_data.get("password")
    if password:
        # Re-authenticate with the current password before changing it.
        # SSO-only accounts have no local password to confirm and are exempt
        # (mirrors the delete-account flow's gate).
        if not is_sso_account:
            current_password = update_data.get("current_password")
            if not current_password:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=UserMessages.CURRENT_PASSWORD_REQUIRED,
                )
            if not verify_password(current_password, current_user.hashed_password):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=UserMessages.CURRENT_PASSWORD_INCORRECT,
                )
        await enforce_password_policy(password)
        current_user.hashed_password = get_password_hash(password)
        # Bump token_version and revoke device tokens + API keys + refresh
        # sessions so no stale credential can survive the password change.
        await user_tokens_service.revoke_user_sessions(
            session, user=current_user, admin_session=admin_session
        )
        # ...but keep THIS device signed in: the revocation above killed the
        # caller's own access token AND refresh chain, so open a fresh session
        # and re-issue both cookies — every *other* session/device still dies.
        # ``amr`` records what this request proved: the current password for
        # local accounts; nothing for the SSO-exempt path (no factor was
        # presented here).
        #
        # Fallback: a transient session-store failure must not fail the
        # password change — re-issue a legacy long-lived token instead (the
        # dual-verify window accepts both); that session just can't renew.
        try:
            issued = await session_service.create_session(
                admin_session,
                user_id=current_user.id,
                amr=[] if is_sso_account else ["pwd"],
                satisfied_providers=[],
                user_agent=request.headers.get("user-agent"),
                ip=get_inet_client_ip(request),
            )
            await admin_session.commit()
            refreshed_token, refreshed_max_age = mint_access_token(
                user_id=current_user.id,
                token_version=current_user.token_version,
                session_id=issued.session.id,
                amr=issued.session.amr,
                satisfied_providers=issued.session.satisfied_providers,
            )
            set_session_cookie(response, refreshed_token, max_age=refreshed_max_age)
            set_refresh_cookie(response, issued.refresh_token)
        except Exception:
            await admin_session.rollback()
            logger.exception(
                "Failed to establish refresh session for user %s after password "
                "change; falling back to a legacy access token",
                current_user.id,
            )
            refreshed_token = create_access_token(
                subject=str(current_user.id),
                token_version=current_user.token_version,
            )
            set_session_cookie(
                response,
                refreshed_token,
                max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            )
            # The browser still holds the refresh cookie whose chain was just
            # revoked above — clear it so the SPA doesn't resend a dead token
            # on its next silent renewal.
            clear_refresh_cookie(response)

    if "avatar_url" in update_data:
        url_value = update_data["avatar_url"]
        if url_value:
            # Read payloads carry the path this API serves the picture from, so
            # one handed straight back would be stored as though it named an
            # image somewhere else. Uploads come through PUT /users/me/avatar.
            if user_avatars_service.is_avatar_url(url_value):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=UserMessages.AVATAR_URL_NOT_EXTERNAL,
                )
            # A linked picture and an uploaded one are alternatives; taking one
            # drops the other.
            await user_avatars_service.delete_avatar(session, user_id=current_user.id)
            current_user.avatar_url = url_value
        else:
            await user_avatars_service.delete_avatar(session, user_id=current_user.id)
            current_user.avatar_url = None
    if "week_starts_on" in update_data:
        normalized_week_start = normalize_week_starts_on(update_data["week_starts_on"])
        if normalized_week_start is not None:
            current_user.week_starts_on = normalized_week_start
    if "recent_tabs_limit" in update_data:
        current_user.recent_tabs_limit = recent_views_service.clamp_recent_limit(
            update_data["recent_tabs_limit"]
        )
    if "timezone" in update_data:
        normalized_timezone = normalize_timezone(update_data["timezone"])
        if normalized_timezone:
            current_user.timezone = normalized_timezone
    if "overdue_notification_time" in update_data:
        normalized_time = normalize_notification_time(
            update_data["overdue_notification_time"]
        )
        if normalized_time:
            current_user.overdue_notification_time = normalized_time
    if "event_reminder_minutes_before" in update_data:
        # ``None`` is a valid value here (reminders off), so assign directly.
        current_user.event_reminder_minutes_before = normalize_reminder_minutes(
            update_data["event_reminder_minutes_before"]
        )
    for field in [
        "email_initiative_addition",
        "email_task_assignment",
        "email_project_added",
        "email_overdue_tasks",
        "email_mentions",
        "email_events",
        "email_event_reminders",
        "push_initiative_addition",
        "push_task_assignment",
        "push_project_added",
        "push_overdue_tasks",
        "push_mentions",
        "push_events",
        "push_event_reminders",
    ]:
        if field in update_data:
            # email_task_assignment=False also cleared the guild-scoped digest
            # queue — done up-front (before any mutation) via the cross-guild
            # fan-out at the top of this handler.
            setattr(current_user, field, bool(update_data[field]))
    if "color_theme" in update_data:
        current_user.color_theme = update_data["color_theme"]
    if "task_completion_visual_feedback" in update_data:
        candidate = update_data["task_completion_visual_feedback"]
        if candidate not in TASK_COMPLETION_VISUAL_FEEDBACK_VALUES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=UserMessages.INVALID_TASK_COMPLETION_VISUAL_FEEDBACK,
            )
        current_user.task_completion_visual_feedback = candidate
    if "task_completion_audio_feedback" in update_data:
        current_user.task_completion_audio_feedback = bool(
            update_data["task_completion_audio_feedback"]
        )
    if "task_completion_haptic_feedback" in update_data:
        current_user.task_completion_haptic_feedback = bool(
            update_data["task_completion_haptic_feedback"]
        )
    if "locale" in update_data:
        current_user.locale = update_data["locale"]
    for field in ("custom_status_emoji", "custom_status_text"):
        if field in update_data:
            # Already held to shape by ``UserSelfUpdate``; ``None`` means the
            # person took it off.
            setattr(current_user, field, update_data[field])
    if "profile_decorations" in update_data:
        # The payload validated it into ``ProfileDecorations``, so what lands
        # in the column is a known set of keys holding catalog ids and nothing
        # else. ``None`` is the bare profile.
        decorations = update_data["profile_decorations"]
        current_user.profile_decorations = decorations or {}

    current_user.updated_at = datetime.now(timezone.utc)
    session.add(current_user)
    await session.commit()
    await session.refresh(current_user)
    # Platform path — no initiative_roles enrichment (see read_users_me).
    # The SPA replaces its auth state with this response, so carry the same
    # linked-identity signal /users/me serves.
    payload = UserRead.model_validate(current_user)
    payload.has_federated_identity = is_sso_account
    return payload


@guild_router.post("/{user_id}/approve", response_model=UserRead)
async def approve_user(
    user_id: int,
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildAdminContext,
) -> User:
    """Let a pending member of this guild sign in.

    Runs on the system engine: the row is another account's, and an account is
    not a guild's to write. ``GuildAdminContext`` plus the membership join
    below are the authorization — the guild admin may only reach someone who is
    already a member of the guild they administer.
    """
    stmt = (
        select(User)
        .join(GuildMembership, GuildMembership.user_id == User.id)
        .where(
            User.id == user_id,
            GuildMembership.guild_id == guild_context.guild_id,
        )
    )
    result = await session.exec(stmt)
    user = result.one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )

    if user.status == UserStatus.anonymized:
        # Anonymized rows are permanently empty husks — no PII to restore,
        # no login to reactivate. Refuse rather than misleadingly succeed.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.CANNOT_REACTIVATE_ANONYMIZED,
        )

    if user.status != UserStatus.active:
        user.status = UserStatus.active
        user.updated_at = datetime.now(timezone.utc)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    # Initiative roles live in the guild schema; SET ROLE into it for the read.
    await set_rls_context(
        session,
        user_id=current_user.id,
        guild_id=guild_context.guild_id,
        guild_role="admin",
    )
    await initiatives_service.load_user_initiative_roles(session, [user])
    return user


@router.get("/me/deletion-eligibility", response_model=DeletionEligibilityResponse)
async def check_deletion_eligibility(
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> DeletionEligibilityResponse:
    """Check if the current user can be deleted and what blockers exist."""
    can_delete, blockers = await users_service.check_deletion_eligibility(
        session, current_user.id
    )

    last_admin_guilds = await users_service.is_last_guild_admin(
        session, current_user.id
    )

    return DeletionEligibilityResponse(
        can_delete=can_delete,
        blockers=blockers,
        last_admin_guilds=last_admin_guilds,
    )


@router.get("/me/initiative-members/{initiative_id}", response_model=List[UserPublic])
async def get_my_initiative_members(
    initiative_id: int,
    guild_id: Annotated[int, Query()],
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Sequence[User]:
    """List members of an initiative the current user belongs to.

    Used by the account-deletion transfer-target picker. ``guild_id`` is
    required: the initiative lives in that guild's schema (ids repeat across
    guild schemas), and the caller has it from the blocker record. We route in
    into the guild schema so the member list is read from the live data (the
    intentional cross-guild visibility the picker needs), not the frozen
    ``public`` backup.
    """
    await set_rls_context(session, guild_id=guild_id)
    await adopt_guild_name_display(session, guild_id=guild_id)

    # Verify the current user is a member of this initiative
    membership = await initiatives_service.get_initiative_membership(
        session,
        initiative_id=initiative_id,
        user_id=current_user.id,
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    # Exclude anonymized rows — they're empty husks of departed users and
    # must not be selectable as project-transfer targets, otherwise a
    # self-deleting user could hand a live project to a non-person.
    # Deactivated users are also excluded: their account is locked and
    # they can't act as an owner until reactivated.
    stmt = (
        select(User)
        .join(InitiativeMember, InitiativeMember.user_id == User.id)
        .where(
            InitiativeMember.initiative_id == initiative_id,
            User.status == UserStatus.active,
        )
        .order_by(User.full_name, User.id)
    )
    result = await session.exec(stmt)
    return result.all()


@router.post("/me/delete-account", response_model=AccountDeletionResponse)
async def delete_own_account(
    request: AccountDeletionRequest,
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> AccountDeletionResponse:
    """Delete or deactivate the current user's account."""
    # Prevent last platform admin deletion (use FOR UPDATE to prevent race condition)
    if await users_service.is_last_platform_admin(
        session, current_user.id, for_update=True
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=UserMessages.CANNOT_DELETE_LAST_ADMIN,
        )

    # Verify password — skipped for SSO-only users, who have no password
    # (NULL ``hashed_password``; identity provisioning flow). Without this
    # exemption an SSO-only account would have no way to satisfy the gate
    # and could only be removed by an admin.
    if not await has_federated_identity(session, user_id=current_user.id):
        if not verify_password(request.password, current_user.hashed_password):
            # 400 (not 401): the user IS authenticated — they passed
            # ``get_current_active_user`` to reach this endpoint. The
            # global axios interceptor treats every 401 as a session
            # expiry and force-logs-out the SPA, so a wrong-password
            # response on this form would knock the user out of the
            # session they were trying to confirm into. 400 keeps the
            # error scoped to the form's onError handler.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=UserMessages.INVALID_PASSWORD,
            )

    # The confirmation phrase is action-specific so the user can't accidentally
    # anonymize when they meant to deactivate, or vice versa.
    expected_phrase = (
        "DEACTIVATE MY ACCOUNT"
        if request.action == "deactivate"
        else "DELETE MY ACCOUNT"
    )
    if request.confirmation_text != expected_phrase:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.CONFIRMATION_MISMATCH,
        )

    # Being the last admin of a guild is the only blocker. Content the user owns
    # is released on the way out and left unowned for a guild admin to claim, so
    # there is nothing to hand over first.
    can_delete, blockers = await users_service.check_deletion_eligibility(
        session, current_user.id
    )

    if not can_delete:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete account: {'; '.join(blockers)}",
        )

    if request.action == "deactivate":
        await users_service.deactivate_user(session, current_user.id)
        return AccountDeletionResponse(
            success=True,
            action="deactivate",
            message="Your account has been deactivated. Contact an administrator to reactivate.",
        )

    # action == "soft_delete"
    await users_service.soft_delete_user(session, current_user.id)
    return AccountDeletionResponse(
        success=True,
        action="soft_delete",
        message="Your account has been anonymized.",
    )


@router.get("/me/api-keys", response_model=ApiKeyListResponse)
async def list_my_api_keys(
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ApiKeyListResponse:
    """List all API keys for the current user."""
    # user_api_keys is a system-engine-only table (no request-path grant, no
    # own-row policy), so key management runs on AdminSessionDep; the explicit
    # user_id filter in the service is the ownership scope.
    keys = await api_keys_service.list_api_keys(session, user=current_user)
    return ApiKeyListResponse(keys=keys)


@router.post(
    "/me/api-keys",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_my_api_key(
    payload: ApiKeyCreateRequest,
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ApiKeyCreateResponse:
    """Create a new API key for the current user."""
    # Runs on the system engine (user_api_keys has no request-path grant, see
    # list_my_api_keys); the current_user scoping below and in the service is
    # the ownership boundary.
    if payload.guild_id is not None:
        # A guild-bound key must target a guild the caller belongs to. Membership
        # is in the public guild_memberships table (readable on the system
        # engine); the explicit user_id filter is the scope. Validating here also
        # turns an unknown guild into a 403 instead of a 500 (FK violation).
        membership = await guilds_service.get_membership(
            session, guild_id=payload.guild_id, user_id=current_user.id
        )
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=UserMessages.API_KEY_GUILD_FORBIDDEN,
            )
    secret, api_key = await api_keys_service.create_api_key(
        session,
        user=current_user,
        name=payload.name,
        expires_at=payload.expires_at,
        read_only=payload.read_only,
        guild_id=payload.guild_id,
    )
    return ApiKeyCreateResponse(api_key=api_key, secret=secret)


@router.delete("/me/api-keys/{api_key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_api_key(
    api_key_id: int,
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> None:
    """Delete an API key for the current user."""
    # System-engine session (see list_my_api_keys); the service's user_id filter
    # scopes the delete to the caller's own keys.
    deleted = await api_keys_service.delete_api_key(
        session, user=current_user, api_key_id=api_key_id
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=UserMessages.API_KEY_NOT_FOUND
        )


async def _require_receiving_admin(
    session: AsyncSession, *, guild_id: int, new_owner_id: int
) -> None:
    """Ownership may only be handed to an active admin of this guild.

    That restriction is what makes the action safe to expose: a guild admin
    already reads and writes every part of their guild, so an owner grant can
    never widen anyone's reach. An ordinary member could end up nominal owner of
    content in an initiative they are not in, which RLS would then hide from
    them.
    """
    recipient = (
        await session.exec(
            select(User)
            .join(GuildMembership, GuildMembership.user_id == User.id)
            .where(
                User.id == new_owner_id,
                User.status == UserStatus.active,
                GuildMembership.guild_id == guild_id,
                GuildMembership.role == GuildRole.admin,
            )
        )
    ).one_or_none()
    if recipient is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.OWNER_MUST_BE_GUILD_ADMIN,
        )


def _ownership_payload(items: list) -> OwnedContentResponse:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.tool.value] = counts.get(item.tool.value, 0) + 1
    return OwnedContentResponse(
        items=[
            OwnedContentItem(tool=item.tool, id=item.id, name=item.name)
            for item in items
        ],
        counts=counts,
        total=len(items),
    )


def _transfer_payload(counts: dict) -> OwnershipTransferResponse:
    by_value = {tool.value: n for tool, n in counts.items()}
    return OwnershipTransferResponse(counts=by_value, total=sum(by_value.values()))


@guild_router.get("/unowned-content", response_model=OwnedContentResponse)
async def list_unowned_content(
    session: SessionDep,
    current_admin: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildAdminContext,
) -> OwnedContentResponse:
    """Everything in this guild that no current member owns.

    Both the content released when someone left and anything orphaned before
    that — either way nobody who can act on it owns it.
    """
    await set_rls_context(
        session,
        user_id=current_admin.id,
        guild_id=guild_context.guild_id,
        guild_role="admin",
    )
    return _ownership_payload(
        await ownership_service.summarize_unowned_content(
            session, guild_id=guild_context.guild_id
        )
    )


@guild_router.post("/unowned-content/claim", response_model=OwnershipTransferResponse)
async def claim_unowned_content(
    payload: OwnershipTransferRequest,
    session: SessionDep,
    current_admin: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildAdminContext,
) -> OwnershipTransferResponse:
    """Give everything nobody owns to one guild admin."""
    await set_rls_context(
        session,
        user_id=current_admin.id,
        guild_id=guild_context.guild_id,
        guild_role="admin",
    )
    await _require_receiving_admin(
        session, guild_id=guild_context.guild_id, new_owner_id=payload.new_owner_id
    )
    counts = await ownership_service.claim_unowned_content(
        session, guild_id=guild_context.guild_id, to_user_id=payload.new_owner_id
    )
    await session.commit()
    return _transfer_payload(counts)


@guild_router.get("/{user_id}/owned-content", response_model=OwnedContentResponse)
async def list_owned_content(
    user_id: int,
    session: SessionDep,
    current_admin: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildAdminContext,
) -> OwnedContentResponse:
    """What this user owns in this guild, for the transfer dialog to list.

    Works for anyone the grants still name, member or not — accounts get
    abandoned as often as they get closed.
    """
    await set_rls_context(
        session,
        user_id=current_admin.id,
        guild_id=guild_context.guild_id,
        guild_role="admin",
    )
    return _ownership_payload(
        await ownership_service.summarize_owned_content(session, user_id)
    )


@guild_router.post(
    "/{user_id}/transfer-ownership", response_model=OwnershipTransferResponse
)
async def transfer_ownership(
    user_id: int,
    payload: OwnershipTransferRequest,
    session: SessionDep,
    current_admin: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildAdminContext,
) -> OwnershipTransferResponse:
    """Move everything ``user_id`` owns in this guild to a guild admin.

    The only place ownership is moved by hand, and guild-admin only.
    """
    if user_id == payload.new_owner_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.OWNER_ALREADY_HOLDS_CONTENT,
        )
    await set_rls_context(
        session,
        user_id=current_admin.id,
        guild_id=guild_context.guild_id,
        guild_role="admin",
    )
    await _require_receiving_admin(
        session, guild_id=guild_context.guild_id, new_owner_id=payload.new_owner_id
    )
    counts = await ownership_service.transfer_content_ownership(
        session, from_user_id=user_id, to_user_id=payload.new_owner_id
    )
    await session.commit()
    return _transfer_payload(counts)


@guild_router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    session: SessionDep,
    current_admin: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildAdminContext,
) -> None:
    """Remove a member from this guild.

    Ends their memberships and the access those carried. It does not move
    ownership: content they own stays recorded as theirs and stops being
    reachable by them, until an admin re-homes it through
    ``POST /{user_id}/transfer-ownership``.
    """
    await set_rls_context(
        session,
        user_id=current_admin.id,
        guild_id=guild_context.guild_id,
        guild_role="admin",
    )

    # Use FOR UPDATE to prevent race condition when checking last admin
    if await users_service.is_last_platform_admin(session, user_id, for_update=True):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.CANNOT_REMOVE_LAST_ADMIN,
        )
    if user_id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.CANNOT_DELETE_SELF,
        )

    stmt = select(GuildMembership).where(
        GuildMembership.user_id == user_id,
        GuildMembership.guild_id == guild_context.guild_id,
    )
    result = await session.exec(stmt)
    membership = result.one_or_none()
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=UserMessages.NOT_IN_GUILD
        )

    await initiatives_service.remove_user_from_guild_initiatives(
        session,
        guild_id=guild_context.guild_id,
        user_id=user_id,
    )
    # Being removed ends what this guild's apps let this person reach at an
    # outside vendor, exactly as leaving voluntarily does.
    await app_connections_service.delete_member_connections(
        session, user_id=user_id, reason="removed_from_guild"
    )
    # And what they let this guild's apps do as them, for the same reason.
    await app_delegations_service.delete_member_delegations(session, user_id=user_id)

    await session.delete(membership)
    await session.commit()
    # Kicked from the guild — drop the user's live content streams immediately
    # (guild-level access change), consistent with the other removal paths.
    await stream_authority.revoke_user(guild_context.guild_id, user_id)
    await app_revocation_service.dispatch_revocations(
        app_revocation_service.drain_revocations(session)
    )


# --- profile pictures --------------------------------------------------------


@router.get("/{user_id}/avatar/{digest}", include_in_schema=False)
async def read_user_avatar(user_id: int, digest: str, session: SessionDep) -> Response:
    """Serve one user's profile picture.

    No session required, and the same for everyone: a name and a face are
    public information in this product, so there is no membership check and no
    per-caller variation in the response — which is what lets it be cached by a
    shared proxy rather than only by the one browser that asked.

    Addressed by the digest of the bytes, so the content at a URL never
    changes. A digest that is not this user's current picture is a 404 rather
    than a redirect to whatever is current, because the response is cached
    under the URL that was asked for.
    """
    if not user_avatars_service.is_valid_digest(digest):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=UserMessages.AVATAR_NOT_FOUND,
        )
    avatar = await user_avatars_service.get_avatar(session, user_id=user_id)
    if avatar is None or avatar.sha256 != digest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=UserMessages.AVATAR_NOT_FOUND,
        )
    return Response(
        content=avatar.data,
        media_type=avatar.content_type,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.put("/me/avatar", response_model=UserRead)
async def upload_my_avatar(
    file: Annotated[UploadFile, File()],
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> User:
    """Replace the caller's profile picture.

    Multipart rather than a base64 field on ``PATCH /users/me``: sending the
    image inside JSON is the thing this endpoint exists to stop. The body is
    read under the cap so an oversized upload is refused rather than buffered
    whole, and the format and dimensions are read from the header — nothing
    here decodes the image.

    Runs on the request-path session, where the row policies allow the caller
    to write their own avatar and no other.
    """
    data = await file.read(AVATAR_MAX_BYTES + 1)
    try:
        validated = user_avatars_service.validate_avatar(data)
    except user_avatars_service.AvatarRejected as rejected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=rejected.code
        ) from rejected

    # Records the serving URL on the user row too, so every payload that
    # carries a person can name the picture without a second query.
    await user_avatars_service.store_avatar(
        session, user=current_user, avatar=validated
    )
    await session.commit()
    await session.refresh(current_user)
    return current_user


@router.delete("/me/avatar", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_avatar(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    """Remove the caller's profile picture."""
    await user_avatars_service.delete_avatar(
        session, user_id=current_user.id, user=current_user
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
