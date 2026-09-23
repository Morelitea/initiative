import logging
from datetime import date, datetime, timezone
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
from sqlalchemy import func
from sqlmodel import select

from app.api.deps import (
    FactorExemptAccountHolder,
    FactorExemptAccountHolderSessionDep,
    RLSSessionDep,
    SettingsContextDep,
    SettingsRLSSessionDep,
    SessionDep,
    UserSessionDep,
    get_current_active_user,
    get_guild_membership,
    GuildContext,
    require_guild_roles,
)
from app.api.v1.platform_endpoints.password_recheck import (
    require_password_or_recent_proof,
)
from app.api.v1.platform_endpoints.session_opening import replace_session
from app.core.password_policy import enforce_password_policy
from app.core.user_display import handle_of
from app.core import usernames
from app.core.capabilities import Capability
from app.core.usernames import UsernameError
from app.core.rate_limit import limiter
from app.core.security import (
    get_password_hash,
    has_usable_password,
)
from app.core.user_input_validators import (
    normalize_reminder_minutes,
    normalize_timezone,
    normalize_time_format,
    normalize_week_starts_on,
)
from app.db.session import get_admin_session, set_rls_context
from sqlmodel.ext.asyncio.session import AsyncSession
from app.models.platform.guild import (
    GUILD_ADMIN_ROLES,
    Guild,
    GuildMembership,
    GuildRole,
)
from app.models.platform.guild_image import GuildImageVariant
from app.models.tenant.initiative import InitiativeMember
from app.core.intake import IntakeStream
from app.models.platform.notification import Notification, NotificationType
from app.models.platform.user import Presence, User, UserStatus
from app.services.platform import intake as intake_service
from app.models.platform.user_cookie_consent import UserCookieConsent
from app.schemas.platform.guild import (
    CommunityGuildRead,
    GuildBannerRead,
    GuildCategory,
)
from app.schemas.platform.user import (
    AccountTimeOutRead,
    CookieConsentRead,
    CookieConsentUpdate,
    UserEmailCreate,
    UserEmailListResponse,
    UserEmailRead,
    AgeConfirmation,
    DecorationPack,
    DecorationPackListResponse,
    OwnedDecoration,
    OwnedDecorationsResponse,
    ProfileDecorations,
    UsernameClaim,
    UserGuildMember,
    UserGuildRead,
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
from app.core.encryption import SALT_EMAIL, decrypt_field
from app.core.messages import (
    AddressMessages,
    AuthMessages,
    GuildMessages,
    LegalMessages,
    UserMessages,
)
from app.services.auth import addresses

from app.core.audit_events import AuditEventType
from app.services import audit as audit_service
from app.services.auth.identity import has_federated_identity
from app.services.tenant import app_connections as app_connections_service
from app.services.tenant import app_delegations as app_delegations_service
from app.services.tenant import app_revocation as app_revocation_service
from app.services.tenant import initiatives as initiatives_service
from app.services.tenant import ownership as ownership_service
from app.services.platform import cookie_consent as cookie_consent_service
from app.services.platform import guilds as guilds_service
from app.services.platform import guild_images as images_service
from app.services.platform import legal as legal_service
from app.services.realtime import manager as realtime_manager
from app.services.platform import presence
from app.services.platform import usernames as username_service
from app.services.stream_authz import authority as stream_authority
from app.models.platform.user_avatar import AVATAR_MAX_BYTES
from app.models.platform.user_profile_view import (
    MemberProfile,
    user_profiles,
)
from app.services.platform import user_avatars as user_avatars_service
from app.services.platform import profile_decorations as profile_decorations_service
from app.services.platform import users as users_service
from app.services.platform import api_keys as api_keys_service
from app.services.platform import csv_export
from app.services.tenant import stats_service
from app.models.platform.user_token import UserTokenPurpose
from app.schemas.platform.auth import VerificationSendResponse
from app.services import email as email_service
from app.services.platform import app_settings as app_settings_service
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


@router.get("/me/time-out", response_model=AccountTimeOutRead)
async def read_my_time_out(
    session: FactorExemptAccountHolderSessionDep,
    current_user: FactorExemptAccountHolder,
) -> AccountTimeOutRead:
    """What a suspended account is told on its time-out screen: why, where a
    reason was given, and whom to contact.

    Answers for an active account too — nobody to contact, since there is
    nothing to lift — so the screen can ask without first knowing the status.
    """
    if current_user.status != UserStatus.suspended:
        return AccountTimeOutRead()
    # The reason travels on the notice the suspension wrote; the newest one is
    # this suspension's.
    notice = (
        await session.exec(
            select(Notification)
            .where(
                Notification.user_id == current_user.id,
                Notification.type == NotificationType.account_suspended,
            )
            .order_by(Notification.created_at.desc())
            .limit(1)
        )
    ).first()
    reason = (notice.data or {}).get("reason") if notice is not None else None
    return AccountTimeOutRead(
        contact_email=await intake_service.contact_for(
            session, IntakeStream.moderation
        ),
        since=current_user.status_changed_at,
        reason=reason.strip() if isinstance(reason, str) and reason.strip() else None,
    )


@router.get("/me", response_model=UserRead)
async def read_users_me(
    session: FactorExemptAccountHolderSessionDep,
    current_user: FactorExemptAccountHolder,
) -> UserRead:
    """Who you are. Reachable while the deployment's second-factor rule is
    unmet, because every screen that could answer it is drawn from this."""
    # No initiative_roles enrichment: initiative membership is guild-schema
    # content, which a platform-path request cannot (and must not) read.
    # Guild-scoped rosters (/g/{guild_id}/users/) still serve it; clients
    # derive per-guild manager state from guild-scoped initiative data.
    payload = await users_service.to_self_read(current_user)
    # Own-row read on the platform-tier session: whether any external identity
    # is linked (drives the "SSO account" affordances in the profile UI).
    payload.has_federated_identity = await has_federated_identity(
        session, user_id=current_user.id
    )
    payload.has_password = has_usable_password(current_user.hashed_password)
    # The hosted deployment's terms. Short-circuits on the deployment switch
    # for every self-hoster, and costs one indexed count everywhere else.
    payload.legal_acceptance_required = await legal_service.acceptance_outstanding(
        session, user=current_user
    )
    # Own-row read on the routed session. Null where this account has never
    # answered, which is what lets a browser tell "never asked" from "asked,
    # and allowed nothing".
    payload.cookie_consent = _cookie_consent_read(
        await cookie_consent_service.get_consent(session, user_id=current_user.id)
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
    session: SettingsRLSSessionDep,
    _current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: SettingsContextDep,
) -> List[UserGuildMember]:
    """The community's roster.

    On the configuration session rather than the content one: who is in a
    community is part of running it, which is what a settings grant reaches
    and what an administrator keeps while its content is closed.
    """
    stmt = (
        select(MemberProfile, GuildMembership.role, GuildMembership.oidc_provider_id)
        .join(GuildMembership, GuildMembership.user_id == MemberProfile.id)
        .where(
            GuildMembership.guild_id == guild_context.guild_id,
            users_service.visible_to_other_people(),
        )
        .order_by(MemberProfile.created_at.asc())
    )
    result = await session.exec(stmt)
    rows = result.all()
    users = [row[0] for row in rows]
    await initiatives_service.load_user_initiative_roles(session, users)

    # ``oidc_managed`` stays a yes/no on the wire: a roster wants to know that
    # SSO placed somebody, not which provider did.
    response = []
    for user, guild_role, oidc_provider_id in rows:
        member = UserGuildMember.model_validate(user)
        member.guild_role = guild_role.value
        member.oidc_managed = oidc_provider_id is not None
        # Copy initiative_roles from loaded user
        member.initiative_roles = getattr(user, "initiative_roles", [])
        response.append(member)
    return response


def _membership_standing(role: GuildRole | None) -> dict[str, object]:
    """The membership field a picker row carries: the rung, which is both what
    a row shows and what a surface asks the ladder about."""
    return {"guild_role": role.value if role is not None else None}


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
        select(MemberProfile)
        .join(GuildMembership, GuildMembership.user_id == MemberProfile.id)
        .where(
            GuildMembership.guild_id == guild_context.guild_id,
            users_service.visible_to_other_people(),
        )
    )
    #: Set while searching by name, and then what the page is ordered by.
    # Both calls take the guild's own setting: a name is searchable and
    # sortable only where the guild shows names, and a default here would
    # decide that for it.
    shows_names = bool(guild_context.guild.show_member_names)
    closest = None
    if search and (term := search.strip()):
        matches, closest = users_service.member_match(term, shows_names=shows_names)
        base = base.where(matches)
    if user_id:
        base = base.where(MemberProfile.id.in_(user_id))

    count_stmt = select(func.count()).select_from(base.subquery())
    data_stmt = base.order_by(
        *users_service.member_order(closest, shows_names=shows_names),
        MemberProfile.username.asc(),
        MemberProfile.discriminator.asc(),
        MemberProfile.id.asc(),
    )

    users, total_count, actual_page = await paginated_query(
        session, data_stmt, count_stmt, page=page, page_size=page_size
    )

    # One extra read for the page just fetched, bounded by ``page_size``: the
    # roster join above filters by guild rather than projecting from it, and
    # widening that projection would change what ``paginated_query`` returns.
    roles = (
        dict(
            (
                await session.exec(
                    select(GuildMembership.user_id, GuildMembership.role).where(
                        GuildMembership.guild_id == guild_context.guild_id,
                        GuildMembership.user_id.in_([user.id for user in users]),
                    )
                )
            ).all()
        )
        if users
        else {}
    )

    return UserSummaryListResponse(
        items=[
            UserSummary.model_validate(user).model_copy(
                update=_membership_standing(roles.get(user.id))
            )
            for user in users
        ],
        total_count=total_count,
        page=actual_page,
        page_size=page_size,
        has_next=page_has_next(actual_page, page_size, total_count),
        has_prev=actual_page > 1,
    )


@router.get("/me/decorations", response_model=OwnedDecorationsResponse)
async def list_my_decorations(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> OwnedDecorationsResponse:
    """Everything the caller may dress their profile in.

    What ships with the app plus what this account acquired, which is what the
    pickers on Settings > Profile offer and exactly what the write path
    accepts. Own-row: ``public.user_decorations`` is readable only by the
    account whose library it is.
    """
    return OwnedDecorationsResponse(
        items=await profile_decorations_service.owned_decorations(
            session, current_user.id
        )
    )


async def _pack_or_404(
    session: AsyncSession, uid: str
) -> profile_decorations_service.Pack:
    pack = await profile_decorations_service.pack_by_uid(session, uid)
    if pack is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=UserMessages.DECORATION_PACK_NOT_FOUND,
        )
    return pack


def _pack_entry(
    pack: profile_decorations_service.Pack, *, installed: bool
) -> DecorationPack:
    listing = pack.listing
    return DecorationPack(
        uid=listing.uid,
        public_id=listing.public_id,
        name=listing.name,
        publisher=listing.publisher,
        description=listing.description,
        avatar_url=listing.avatar_url,
        contents=[
            OwnedDecoration(id=decoration_id, kind=kind, name=None, source=listing.uid)
            for decoration_id, kind in pack.decorations.items()
        ],
        installed=installed,
    )


@router.get("/me/decoration-packs", response_model=DecorationPackListResponse)
async def list_decoration_packs(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> DecorationPackListResponse:
    """The store: every profile pack this deployment offers, and which you have.

    The shelf is the marketplace catalog, so a pack that ships with the build
    and one published to it read the same here.
    """
    installed = await profile_decorations_service.installed_pack_ids(
        session, current_user.id
    )
    packs = await profile_decorations_service.available_packs(session)
    return DecorationPackListResponse(
        items=[_pack_entry(pack, installed=pack.uid in installed) for pack in packs]
    )


@router.post("/me/decoration-packs/{uid}", response_model=DecorationPack)
async def install_decoration_pack(
    uid: str,
    session: UserSessionDep,
    admin_session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> DecorationPack:
    """Take a pack, putting its decorations in your library.

    The catalog is read on the request path; the grant is written on the system
    engine, because a grant is issued rather than self-served — the request path
    holds no write verb on ``public.user_decorations``. What makes it the
    caller's own is that the only account it ever names is theirs.
    """
    pack = await _pack_or_404(session, uid)
    conflicting = await profile_decorations_service.install_pack(
        admin_session, user_id=current_user.id, pack=pack
    )
    if conflicting:
        # Another pack already gave this library one of these ids. A decoration
        # id names one thing, so the row belongs to whoever granted it first
        # and this install would have been a partial one reported as whole.
        await admin_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=UserMessages.DECORATION_ALREADY_GRANTED,
        )
    await admin_session.commit()
    return _pack_entry(pack, installed=True)


@router.delete("/me/decoration-packs/{uid}", response_model=DecorationPack)
async def remove_decoration_pack(
    uid: str,
    session: UserSessionDep,
    admin_session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> DecorationPack:
    """Give a pack back, taking its decorations out of your library.

    Anything from it that was being worn comes off in the same transaction —
    a profile must not be left wearing what the account no longer has, and
    two commits would leave a window where it was.
    """
    pack = await _pack_or_404(session, uid)
    await profile_decorations_service.remove_pack(
        admin_session, user_id=current_user.id, pack=pack
    )
    await admin_session.commit()
    return _pack_entry(pack, installed=False)


@router.get("/{handle}/profile", response_model=UserProfile)
async def read_user_profile(
    handle: str,
    session: UserSessionDep,
    _current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserProfile:
    """One person's profile, addressed by their handle.

    ``jordan1234`` — the name and the number it is always written with, run
    together. ``#`` never survives a URL, and the number's four digits are
    fixed width, so the two come apart again exactly.

    A profile is public and has no guild in it: it carries the handle, the
    face, the status, the look and how they appear, and it is the same page
    whoever opens it. That is why it is not reached through a guild — no
    part of the answer depends on one.

    Read from ``public.user_profiles``, the view that *is* the public
    projection: which columns are public is decided by the view and the column
    grant behind it (migration 0214), not here. An ordinary platform-tier
    session, RLS enforced. A suspended account has no profile.
    """
    parsed = usernames.parse_url_handle(handle)
    if parsed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AuthMessages.USER_NOT_FOUND,
        )
    name, discriminator = parsed
    # Named one by one rather than as the whole view: a single-entity select
    # comes back scalarized to its first column.
    stmt = select(
        user_profiles.c.id,
        user_profiles.c.username,
        user_profiles.c.discriminator,
        user_profiles.c.avatar_url,
        user_profiles.c.status,
        user_profiles.c.custom_status,
        user_profiles.c.profile_decorations,
        user_profiles.c.created_at,
    ).where(
        func.lower(user_profiles.c.username) == name,
        user_profiles.c.discriminator == discriminator,
        users_service.visible_to_other_people(user_profiles.c.status),
    )
    row = (await session.exec(stmt)).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AuthMessages.USER_NOT_FOUND,
        )
    return UserProfile(
        id=row.id,
        username=row.username,
        discriminator=row.discriminator,
        avatar_url=row.avatar_url,
        status=row.status,
        custom_status=row.custom_status or {},
        profile_decorations=row.profile_decorations or {},
        presence=presence.online.presence_of(row.id),
        joined_at=row.created_at,
    )


@router.get("/{handle}/communities", response_model=List[CommunityGuildRead])
async def read_user_communities(
    handle: str,
    admin_session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> List[CommunityGuildRead]:
    """The listed communities one person belongs to.

    A separate read from the profile on purpose: the profile is the public
    projection of ``public.users`` and this is not about that row at all. It
    also cannot run on the same session — ``guild_memberships`` is scoped to
    the caller's own rows on the request path, and the question is about
    somebody else — so it takes the system engine, exactly as the directory
    does, with the same service-side filters deciding what may appear.

    Only guilds that opted into the directory. One someone is in that did not
    is nobody else's business, and does not appear here for anyone.
    """
    parsed = usernames.parse_url_handle(handle)
    if parsed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AuthMessages.USER_NOT_FOUND,
        )
    name, discriminator = parsed
    subject = (
        await admin_session.exec(
            select(User).where(
                func.lower(User.username) == name,
                User.discriminator == discriminator,
                users_service.visible_to_other_people(User.status),
            )
        )
    ).first()
    if subject is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AuthMessages.USER_NOT_FOUND,
        )

    guilds = await guilds_service.list_profile_communities(
        admin_session, user_id=subject.id
    )
    mine = {
        row.guild_id
        for row in (
            await admin_session.exec(
                select(GuildMembership).where(
                    GuildMembership.user_id == current_user.id
                )
            )
        ).all()
    }
    online = realtime_manager.present_counts(guild.id for guild in guilds)
    # How many people are in each, which the card names and this read has to
    # ask for: nothing about a guild row carries it.
    members = await guilds_service.count_members_by_guild(
        admin_session, guild_ids=[guild.id for guild in guilds]
    )
    # Digests only, in one query: a card names its pictures, never carries them.
    images = await images_service.image_urls(
        admin_session,
        [guild.id for guild in guilds],
        GuildImageVariant.icon,
        GuildImageVariant.card,
    )
    return [
        CommunityGuildRead(
            id=guild.id,
            name=guild.name,
            description=guild.description,
            icon_url=images.get(guild.id, {}).get(GuildImageVariant.icon),
            banner=GuildBannerRead(
                image_url=images.get(guild.id, {}).get(GuildImageVariant.card),
                **guild.banner,
            ),
            categories=[GuildCategory(value) for value in guild.categories],
            member_count=members.get(guild.id, 0),
            online_count=online.get(guild.id, 0),
            already_member=guild.id in mine,
        )
        for guild in guilds
    ]


#: A guild exports what it knows about its own members. An account's platform
#: tier and whether it has confirmed its address are the platform's business,
#: not a guild's, so neither is a column here.
_GUILD_CSV_HEADERS = [
    "user_id",
    "handle",
    "full_name",
    "guild_role",
    "oidc_managed",
    "status",
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
        select(MemberProfile, GuildMembership.role, GuildMembership.oidc_provider_id)
        .join(GuildMembership, GuildMembership.user_id == MemberProfile.id)
        .where(GuildMembership.guild_id == guild_context.guild_id)
        .order_by(MemberProfile.created_at.asc())
    )
    if user_id:
        stmt = stmt.where(MemberProfile.id.in_(user_id))
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
    for user, guild_role, oidc_provider_id in rows:
        csv_rows.append(
            [
                user.id,
                handle_of(user),
                (user.full_name or "") if shows_names else "",
                guild_role.value,
                oidc_provider_id is not None,
                user.status.value if hasattr(user.status, "value") else user.status,
                user.created_at.isoformat() if user.created_at else "",
                csv_export.format_initiative_roles(user),
            ]
        )

    csv_bytes = csv_export.build_csv(_GUILD_CSV_HEADERS, csv_rows)

    # Nothing changed, so the endpoint has no commit of its own to ride: the
    # record is the whole write.
    await audit_service.record(
        session,
        event_type=AuditEventType.GUILD_MEMBERS_EXPORTED,
        actor_user_id=guild_context.membership.user_id,
        guild_id=guild_context.guild_id,
        target_type="guild",
        target_id=guild_context.guild_id,
        detail={"count": len(rows)},
    )
    await session.commit()

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
    return await users_service.to_self_read(current_user)


#: The age below which somebody may not take part in the parts of the platform
#: that are open to people they have not met.
MINIMUM_AGE_YEARS = 16

#: A bound on what counts as a date somebody could have been born on. Not a
#: judgement about anyone — it is what separates a real answer from a typo.
MAX_PLAUSIBLE_AGE_YEARS = 120


def _years_since(birthdate: date, today: date) -> int:
    """Whole years between two dates — an age, counted the way people count it.

    A birthday that has not come round yet this year does not count, which is
    the whole of the arithmetic.
    """
    had_birthday = (today.month, today.day) >= (birthdate.month, birthdate.day)
    return today.year - birthdate.year - (0 if had_birthday else 1)


@router.post("/me/age-confirmation", response_model=UserRead)
async def confirm_my_age(
    payload: AgeConfirmation,
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserRead:
    """Answer, once, whether this account is old enough for the open parts.

    Asked where somebody is about to join a community anyone on the deployment
    can find, and nowhere else. The answer lives on the account rather than per
    community: it is a fact about the person, and the second listed community
    they join asks nothing.

    **It gates the directory, not the deployment.** A community somebody was
    invited to is theirs and whoever runs it to answer for, so nothing here
    stands between them and it — an account that has never answered, or
    answered under age, keeps every private community it belongs to and
    everything in them.

    **The date is not kept.** It is read here, compared against the minimum, and
    goes out of scope with the request — there is no column for it, nothing logs
    it, and no audit record carries it. What is written is a timestamp saying
    the question was answered, which is what shows the deployment asked.

    The comparison is the server's because it is the one that decides. A client
    could work out the same answer, and a client's answer is not evidence.

    Saying it again is not an error and does not move the timestamp — the record
    is when they first answered.

    **An answer of "under age" also stands.** It is recorded — the fact, not the
    date — and the question is not asked again, because a question you can
    re-answer until it comes out right is not one. Putting it right takes
    somebody with ``users.age_unblock``, which is a support ticket rather than
    an appeal to the same form.
    """
    if current_user.age_below_minimum_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=UserMessages.AGE_ANSWER_STANDS,
        )

    today = datetime.now(timezone.utc).date()
    if payload.birthdate > today or payload.birthdate < today.replace(
        year=today.year - MAX_PLAUSIBLE_AGE_YEARS
    ):
        # Not a date anybody was born on. Refused separately from being too
        # young, so the reply says which it was.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=UserMessages.AGE_INVALID_BIRTHDATE,
        )
    if _years_since(payload.birthdate, today) < MINIMUM_AGE_YEARS:
        # Recorded before the refusal, so the answer holds: what is written is
        # that they answered under age, never the date they gave.
        current_user.age_below_minimum_at = datetime.now(timezone.utc)
        current_user.updated_at = datetime.now(timezone.utc)
        session.add(current_user)
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=UserMessages.AGE_BELOW_MINIMUM,
        )

    if current_user.age_confirmed_at is None:
        current_user.age_confirmed_at = datetime.now(timezone.utc)
        current_user.updated_at = datetime.now(timezone.utc)
        session.add(current_user)
        await session.commit()
        await session.refresh(current_user)

    return await users_service.to_self_read(current_user)


def _cookie_consent_read(row: UserCookieConsent | None) -> CookieConsentRead | None:
    return None if row is None else CookieConsentRead.model_validate(row)


@router.put("/me/cookie-consent", response_model=CookieConsentRead)
async def set_cookie_consent(
    payload: CookieConsentUpdate,
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CookieConsentRead:
    """Record what this account allows to be kept in a browser.

    The browser it was answered in keeps its own copy — a visitor who has not
    signed in has no account to attach one to, and the answer is about that
    browser either way. This is what carries it to a browser that has never
    been asked, and carries a change of mind back to one that has.

    Replaces rather than appends: the question is what applies now. Sending it
    again with the same answer is a no-op apart from the stamp, which is what
    two browsers compare to tell whose answer is the later one.
    """
    row = await cookie_consent_service.record_consent(
        session,
        user_id=current_user.id,
        granted=payload.granted,
        version=payload.version,
    )
    await session.commit()
    await session.refresh(row)
    return CookieConsentRead.model_validate(row)


@router.post("/me/legal-acceptance", response_model=UserRead)
async def accept_legal_documents(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserRead:
    """Agree to this deployment's terms and privacy policy.

    For an account that never met the signup form — one an identity provider
    provisioned on first sign-in. The form's own notice is the agreement for
    everybody else, recorded as the account is created.

    Saying it again appends: the table records acceptances, not a state, and
    agreeing to a newer revision is a real event rather than a correction to
    an old one. The screen only appears while something is outstanding, so in
    practice this is written once.

    A deployment with no terms of its own has nothing to accept, so this
    answers 404 rather than writing an empty record.
    """
    if not legal_service.legal_documents_enabled():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=LegalMessages.NOT_CONFIGURED,
        )
    if await legal_service.acceptance_outstanding(session, user=current_user):
        await legal_service.record_acceptance(session, user_id=current_user.id)
        await session.commit()
    payload = await users_service.to_self_read(current_user)
    payload.legal_acceptance_required = False
    return payload


def _address_read(row) -> UserEmailRead:
    """One stored address in the shape its owner reads."""
    return UserEmailRead(
        id=row.id,
        email=decrypt_field(row.email_encrypted, SALT_EMAIL),
        verified=row.verified_at is not None,
        is_primary=row.is_primary,
        source=row.source,
        created_at=row.created_at,
        last_login_at=row.last_login_at,
    )


@router.get("/me/emails", response_model=UserEmailListResponse)
async def list_my_addresses(
    admin_session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserEmailListResponse:
    """Every address this account holds.

    On the system engine: ``user_emails`` carries no request-path grants,
    because resolving an address happens before anybody is authenticated.
    """
    rows = await addresses.list_for_user(admin_session, user_id=current_user.id)
    return UserEmailListResponse(items=[_address_read(row) for row in rows])


@router.post(
    "/me/emails",
    response_model=VerificationSendResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit("5/15minutes")
async def add_my_address(
    request: Request,
    payload: UserEmailCreate,
    session: SessionDep,
    admin_session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> VerificationSendResponse:
    """Start holding another address, and write to it to prove it.

    The answer is the same whoever holds the address already. What differs is
    where the mail goes: a free address gets a link to confirm it, and one that
    is taken gets nothing.
    """
    # Whether this deployment can send at all is settled before the address is
    # looked at, so the refusal is about the server rather than about who holds
    # what. Everything after this point answers identically.
    app_settings = await app_settings_service.get_app_settings(session)
    if not (app_settings.smtp_host and app_settings.smtp_from_address):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.SMTP_NOT_CONFIGURED,
        )

    try:
        added = await addresses.add_for_user(
            admin_session, user_id=current_user.id, email=payload.email
        )
    except addresses.AddressError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code
        ) from exc
    # ``added`` is the new claim, or the one this account already had — asking
    # again is how a letter that did not arrive is sent again. ``None`` means
    # somebody has proven the address, and nothing is written.
    if added is not None:
        await admin_session.commit()
        await admin_session.refresh(added)
        token = await user_tokens_service.create_token(
            admin_session,
            user_id=current_user.id,
            purpose=UserTokenPurpose.email_verification,
            user_email_id=added.id,
        )
        try:
            await email_service.send_address_verification_email(
                session, current_user, address=payload.email, token=token
            )
        except Exception:
            # The address is held and unproven either way; a send that failed
            # is retried by adding it again.
            logger.exception(
                "verification mail for a new address could not be sent (user %s)",
                current_user.id,
            )
    return VerificationSendResponse(status="sent")


@router.delete("/me/emails/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_my_address(
    address_id: int,
    admin_session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    try:
        await addresses.remove_for_user(
            admin_session, user_id=current_user.id, address_id=address_id
        )
    except addresses.AddressError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
                if exc.code == AddressMessages.ADDRESS_NOT_FOUND
                else status.HTTP_400_BAD_REQUEST
            ),
            detail=exc.code,
        ) from exc
    await admin_session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/me/emails/{address_id}/primary", response_model=UserEmailRead)
async def make_my_address_primary(
    address_id: int,
    admin_session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserEmailRead:
    """Move where account mail goes."""
    try:
        row = await addresses.set_primary_for_user(
            admin_session, user_id=current_user.id, address_id=address_id
        )
    except addresses.AddressError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
                if exc.code == AddressMessages.ADDRESS_NOT_FOUND
                else status.HTTP_400_BAD_REQUEST
            ),
            detail=exc.code,
        ) from exc
    await admin_session.commit()
    await admin_session.refresh(row)
    return _address_read(row)


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
        payload = await users_service.to_self_read(current_user)
        payload.has_federated_identity = is_sso_account
        payload.has_password = has_usable_password(current_user.hashed_password)
        return payload

    new_full_name = update_data.get("full_name")
    if new_full_name is not None:
        current_user.full_name = new_full_name or None

    password = update_data.get("password")
    if password:
        # Read before the hash below replaces it: what the account held going
        # in is what the re-check asks about and what the replacement session
        # may claim was proved here.
        held_password = has_usable_password(current_user.hashed_password)
        # Re-authenticate with the current password before changing it. An
        # account that holds none answers with a recent sign-in instead.
        await require_password_or_recent_proof(
            request,
            admin_session,
            current_user,
            update_data.get("current_password"),
        )
        await enforce_password_policy(password)
        current_user.hashed_password = get_password_hash(password)
        current_user.password_set_at = datetime.now(timezone.utc)
        # Bump token_version and revoke device tokens + API keys + refresh
        # sessions so no stale credential can survive the password change.
        #
        # Staged, not committed: the replacement session below joins them in
        # one transaction, so the account keeps what it had if that fails.
        await user_tokens_service.revoke_user_sessions(
            admin_session, user=current_user, commit=False
        )
        # ...but keep THIS device signed in: the revocation above took the
        # caller's own access token AND refresh chain, so a fresh session is
        # opened and both cookies re-issued — every *other* session/device
        # still dies. ``amr`` records what this request proved: the current
        # password where the account held one; nothing where it did not, since
        # no factor was presented here.
        await replace_session(
            request,
            response,
            admin_session,
            user=current_user,
            amr=["pwd"] if held_password else [],
            satisfied_providers=[],
        )

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
    if "time_format" in update_data:
        normalized_time_format = normalize_time_format(update_data["time_format"])
        if normalized_time_format is not None:
            current_user.time_format = normalized_time_format
    if "recent_tabs_limit" in update_data:
        current_user.recent_tabs_limit = recent_views_service.clamp_recent_limit(
            update_data["recent_tabs_limit"]
        )
    if "timezone" in update_data:
        normalized_timezone = normalize_timezone(update_data["timezone"])
        if normalized_timezone:
            current_user.timezone = normalized_timezone
    if "event_reminder_minutes_before" in update_data:
        # ``None`` is a valid value here (reminders off), so assign directly.
        current_user.event_reminder_minutes_before = normalize_reminder_minutes(
            update_data["event_reminder_minutes_before"]
        )
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
    if "custom_status" in update_data:
        # Already held to shape by ``CustomStatus``; ``None`` is the status
        # taken off, which is the empty object rather than a null column.
        current_user.custom_status = update_data["custom_status"] or {}
    if "presence" in update_data:
        # The column is the standing preference. The roll is told separately
        # below, once the write is safely down.
        current_user.presence = Presence(update_data["presence"])
    if "profile_decorations" in update_data:
        # The payload validated it into ``ProfileDecorations``, so what lands
        # in the column is a known set of keys holding catalog ids and nothing
        # else. ``None`` is the bare profile.
        decorations = user_in.profile_decorations or ProfileDecorations()
        worn = decorations.worn()
        if worn:
            # The same row lock giving a pack back takes, and taken before the
            # library is read: the check and the write then sit in one
            # serialized window, so the two orderings are the only ones —
            # either this look is saved and the pack is given back after
            # (undressing it), or the pack goes first and this is refused.
            await session.exec(
                select(User.id).where(User.id == current_user.id).with_for_update()
            )
            # You wear what you have. The library is the authority for both
            # halves of that — whether the account has the decoration at all,
            # and whether it has it for the slot it is being put in.
            owned = await profile_decorations_service.owned_kinds(
                session, current_user.id
            )
            if profile_decorations_service.unwearable(worn, owned):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=UserMessages.DECORATION_NOT_OWNED,
                )
        current_user.profile_decorations = decorations.model_dump()

    current_user.updated_at = datetime.now(timezone.utc)
    session.add(current_user)
    if password:
        # In the same transaction as the password itself, so the change and
        # the record of it land together or not at all.
        await audit_service.record(
            session,
            event_type=AuditEventType.AUTH_PASSWORD_CHANGED,
            actor_user_id=current_user.id,
            detail={"via": "self_service"},
        )
    await session.commit()
    await session.refresh(current_user)
    if "presence" in update_data:
        # A change made from an open tab takes effect for readers immediately,
        # rather than at the next reconnect. Told after the commit, so nothing
        # is shown on the strength of a write that did not land.
        presence.online.chose(current_user.id, current_user.presence)
    # Platform path — no initiative_roles enrichment (see read_users_me).
    # The SPA replaces its auth state with this response, so carry the same
    # linked-identity signal /users/me serves.
    payload = await users_service.to_self_read(current_user)
    payload.has_federated_identity = is_sso_account
    payload.has_password = has_usable_password(current_user.hashed_password)
    return payload


@guild_router.post("/{user_id}/approve", response_model=UserGuildRead)
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

    Answers with ``UserGuildRead`` — the account as the guild reads it, which
    is the standing that just changed and the handle it belongs to. The row
    loaded here is the whole ``User``, because the write needs it; what leaves
    is the guild's read of it.
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
    # Platform management, on the system engine, which the policies admit by
    # the connection's own login rather than by anything this call says.
    await set_rls_context(session, guild_id=guild_context.guild_id)
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

    return DeletionEligibilityResponse(
        can_delete=can_delete,
        blockers=blockers,
        sole_superadmin_guilds=await users_service.is_last_guild_superadmin(
            session, current_user.id
        ),
    )


@router.get("/me/initiative-members/{initiative_id}", response_model=List[UserPublic])
async def get_my_initiative_members(
    initiative_id: int,
    guild_id: Annotated[int, Query()],
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Sequence[MemberProfile]:
    """List members of an initiative the current user belongs to.

    Used by the account-deletion transfer-target picker. ``guild_id`` is
    required: the initiative lives in that guild's schema (ids repeat across
    guild schemas), and the caller has it from the blocker record. We route in
    into the guild schema so the member list is read from the live data (the
    intentional cross-guild visibility the picker needs), not the frozen
    ``public`` backup.
    """
    await set_rls_context(session, guild_id=guild_id)

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
        select(MemberProfile)
        .join(InitiativeMember, InitiativeMember.user_id == MemberProfile.id)
        .where(
            InitiativeMember.initiative_id == initiative_id,
            MemberProfile.status == UserStatus.active,
        )
        .order_by(MemberProfile.full_name, MemberProfile.id)
    )
    result = await session.exec(stmt)
    return result.all()


@router.post("/me/delete-account", response_model=AccountDeletionResponse)
async def delete_own_account(
    http_request: Request,
    request: AccountDeletionRequest,
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> AccountDeletionResponse:
    """Delete or deactivate the current user's account."""
    # Keep at least one owner, who is the only rung that can manage platform
    # configuration (FOR UPDATE to prevent a race).
    if await users_service.is_last_capability_holder(
        session, current_user.id, Capability.CONFIG_MANAGE, for_update=True
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=UserMessages.CANNOT_DELETE_LAST_OWNER,
        )

    # Re-check the password, where the account holds one to re-check. An
    # account that signs in another way — a passkey, an identity provider —
    # has none to supply, and answers with a recent sign-in and the
    # confirmation phrase.
    #
    # 400 (not 401): the user IS authenticated — they passed
    # ``get_current_active_user`` to reach this endpoint. The global axios
    # interceptor treats every 401 as a session expiry and force-logs-out the
    # SPA, so a wrong-password response on this form would knock the user out
    # of the session they were trying to confirm into. 400 keeps the error
    # scoped to the form's onError handler.
    await require_password_or_recent_proof(
        http_request,
        session,
        current_user,
        request.password,
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
        await users_service.deactivate_user(
            session, current_user.id, actor_user_id=current_user.id
        )
        return AccountDeletionResponse(
            success=True,
            action="deactivate",
            message="Your account has been deactivated. Contact an administrator to reactivate.",
        )

    # action == "soft_delete"
    #
    # Nothing is erased here. The account moves to ``deleted`` and keeps
    # everything — memberships, initiative roles, the documents it owns — so
    # that coming back restores it whole. It stops existing for everybody
    # else immediately, and ``account_purge`` erases it when the deployment's
    # window runs out. Signing in before then calls the whole thing off.
    await users_service.request_account_deletion(
        session, current_user.id, actor_user_id=current_user.id
    )
    return AccountDeletionResponse(
        success=True,
        action="soft_delete",
        message="Your account has been deleted.",
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
        # And the guild has to accept the credential at all. Asked here as well
        # as at the gate so a key that could never be used is never handed over.
        guild = await session.get(Guild, payload.guild_id)
        if guild is not None and not guild.allow_api_keys:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=GuildMessages.GUILD_API_KEYS_REFUSED,
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

    The caller has routed into the guild's schema, so the roster comes from
    ``MemberProfile`` — the view a guild session reads people through.
    """
    recipient = (
        await session.exec(
            select(MemberProfile.id)
            .join(GuildMembership, GuildMembership.user_id == MemberProfile.id)
            .where(
                MemberProfile.id == new_owner_id,
                MemberProfile.status == UserStatus.active,
                GuildMembership.guild_id == guild_id,
                GuildMembership.role.in_(GUILD_ADMIN_ROLES),
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
    await _require_receiving_admin(
        session, guild_id=guild_context.guild_id, new_owner_id=payload.new_owner_id
    )
    counts = await ownership_service.claim_unowned_content(
        session,
        guild_id=guild_context.guild_id,
        to_user_id=payload.new_owner_id,
        actor_user_id=current_admin.id,
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
    await _require_receiving_admin(
        session, guild_id=guild_context.guild_id, new_owner_id=payload.new_owner_id
    )
    counts = await ownership_service.transfer_content_ownership(
        session,
        from_user_id=user_id,
        to_user_id=payload.new_owner_id,
        guild_id=guild_context.guild_id,
        actor_user_id=current_admin.id,
    )
    await session.commit()
    return _transfer_payload(counts)


@guild_router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    session: SessionDep,
    admin_session: AdminSessionDep,
    current_admin: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildAdminContext,
) -> None:
    """Remove a member from this guild.

    Ends their memberships and the access those carried. It does not move
    ownership: content they own stays recorded as theirs and stops being
    reachable by them, until an admin re-homes it through
    ``POST /{user_id}/transfer-ownership``.
    """

    # A platform question — whether the platform would be left with no config
    # manager — so it is asked on the system engine rather than through the
    # guild role this request has assumed. FOR UPDATE to prevent a race with a
    # concurrent platform-role change.
    if await users_service.is_last_capability_holder(
        admin_session, user_id, Capability.CONFIG_MANAGE, for_update=True
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.CANNOT_REMOVE_LAST_OWNER,
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

    # Removing the seat-holder ends the seat exactly as demoting them does, so
    # it answers to the same authority: only the seat passes the seat on.
    if (
        membership.role == GuildRole.superadmin
        and guild_context.role != GuildRole.superadmin
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.GUILD_ROLE_NOT_ASSIGNABLE,
        )
    await guilds_service.lock_guild_seats(admin_session, guild_context.guild_id)
    # And the seat stays filled for as long as the guild requires a sign-in:
    # the requirement is lifted from the surface the seat holds.
    if await guilds_service.must_keep_superadmin(
        admin_session, guild_id=guild_context.guild_id, user_id=user_id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.CANNOT_VACATE_LAST_SUPERADMIN,
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

    removed_role = membership.role
    await session.delete(membership)
    await audit_service.record(
        session,
        event_type=AuditEventType.GUILD_MEMBER_REMOVED,
        actor_user_id=current_admin.id,
        target_user_id=user_id,
        guild_id=guild_context.guild_id,
        target_type="guild",
        target_id=guild_context.guild_id,
        detail={"role": removed_role.value, "via": "admin"},
    )
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
            detail=GuildMessages.IMAGE_NOT_FOUND,
        )
    avatar = await user_avatars_service.get_avatar(session, user_id=user_id)
    if avatar is None or avatar.sha256 != digest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildMessages.IMAGE_NOT_FOUND,
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
) -> UserRead:
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
    return await users_service.to_self_read(current_user)


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
