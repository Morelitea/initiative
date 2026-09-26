from __future__ import annotations

import logging
from contextlib import suppress
from typing import Annotated, List

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

from app.api.deps import (
    GuildContext,
    SeatSessionDep,
    SeatWriteSessionDep,
    SettingsAdminContextDep,
    SettingsAdminWriteContextDep,
    SettingsRLSSessionDep,
    SettingsSeatWriteContextDep,
    UploadUserDep,
    UserSessionDep,
    GuildAccessError,
    establish_guild_access,
    holds_guild_role,
    raise_for_guild_access,
    get_current_active_user,
)
from app.api.v1.platform_endpoints.password_recheck import (
    require_password_or_recent_proof,
)
from app.core import auth_context
from app.core.intake import IntakeStream
from app.core.auth_context import satisfied_provider_ids
from app.core.capabilities import Capability, user_has_capability
from app.core.config import settings
from app.core.login_methods import LoginMethod, SecondFactorRequirement
from app.core.messages import BillingMessages, GuildMessages
from app.core.rate_limit import get_user_or_ip_key, limiter
from app.core.security import (
    AUTH_POLICY_UNMET_HEADER,
    HandoffSigningNotConfiguredError,
    create_billing_portal_handoff_token,
)
from app.services.platform.identity_refs import billing_refs
from app.services.marketplace import app_refs
from app.db import cohorts
from app.db.schema_provisioning import deprovision_guild
from app.db.session import get_system_session
from app.core.audit_events import AuditEventType
from app.services import audit as audit_service
from app.services import email as email_service
from app.models.platform.guild import (
    assignable_roles,
    Guild,
    GuildCategory,
    GuildRole,
    GuildStatus,
    LIVE_STATUS_VALUES,
)
from app.models.platform.guild_administration import GuildAdministration
from app.models.platform.guild_image import (
    BANNER_VARIANTS,
    IMAGE_SPECS,
    GuildImageVariant,
)
from app.models.platform.user import User, UserStatus
from app.schemas.platform.billing import BillingPortalHandoffResponse
from app.schemas.platform.guild import (
    CommunityGuildPage,
    CommunityGuildRead,
    GuildBannerRead,
    GuildCan,
    GuildEntitlementsRead,
    GuildApiAccessRead,
    GuildApiAccessUpdate,
    GuildSecondFactorRead,
    GuildSecondFactorUpdate,
    GuildAuthSettingsRead,
    GuildAuthPolicyRead,
    GuildAuthPolicyUpdate,
    GuildCreate,
    GuildDeletionRequest,
    GuildMembershipUpdate,
    GuildRead,
    GuildInviteAcceptRequest,
    GuildInviteCreate,
    GuildInviteRead,
    GuildPaymentIssueRead,
    GuildInviteStatus,
    GuildOrderUpdate,
    GuildNotificationPolicyRead,
    GuildNotificationPolicyUpdate,
    GuildSessionLimitRead,
    GuildSessionLimitUpdate,
    GuildUpdate,
    LeaveGuildEligibilityResponse,
)
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.guild_auth_policy import GuildAuthPolicy
from app.services.auth import session_lifetime
from app.services.auth import (
    guild_provider_connections as guild_connections,
)
from app.services.auth.platform_provider import is_login_ready
from app.core.guild_auth_options import GuildAuthOption, effective_options
from app.services.auth.assurance import SECOND_FACTOR_AMR, carries_passkey
from app.services.platform import auth_posture
from app.services.platform import guild_entitlements
from app.services.platform import notification_policy
from app.services.platform import billing as billing_service
from app.services.platform import billing_claim
from app.services.platform import billing_ping
from app.services.platform import guild_images as images_service
from app.services.tenant.attachments import FileTooLargeError, read_upload_bounded
from app.services.platform import guilds as guilds_service
from app.services.platform import intake as intake_service
from app.services.content_sockets import sockets as content_sockets
from app.services.tenant import app_connections as app_connections_service
from app.services.tenant import app_revocation as app_revocation_service
from sqlmodel.ext.asyncio.session import AsyncSession

SystemSessionDep = Annotated[AsyncSession, Depends(get_system_session)]

router = APIRouter()
logger = logging.getLogger(__name__)


def _position_of(guild_context: GuildContext) -> int:
    """Where the caller keeps this community in their list; a grantee has no
    place in it."""
    membership = guild_context.membership
    return membership.position if membership is not None else 0


def _can_of(guild_context: GuildContext) -> GuildCan:
    """What the caller may do in the community, by the standing: each flag is
    what the guard on the routes that do the thing asks."""
    return GuildCan(
        # The seam admitted the request, which a community in time out refuses.
        enter=True,
        content=not guild_context.is_settings_only,
        administer=holds_guild_role(guild_context, GuildRole.admin, settings=True),
        configure=guild_context.writes_settings,
        administer_content=holds_guild_role(guild_context, GuildRole.admin),
        seat=guild_context.seat,
    )


def _can_of_membership(guild: Guild, role: GuildRole) -> GuildCan:
    """The same answers for a membership row read without a standing, as the
    caller's own list is: the row's rung asked of the ladder the standing's
    admin fact is rendered from, and the lifecycle status the seam admits a
    member by."""
    administers = role.reaches(GuildRole.admin)
    return GuildCan(
        enter=guild.status in LIVE_STATUS_VALUES,
        content=True,
        administer=administers,
        configure=administers,
        administer_content=administers,
        seat=role.reaches(GuildRole.superadmin),
    )


def _serialize_guild(
    guild: Guild,
    *,
    role: GuildRole,
    position: int,
    retention_days: int | None = None,
    member_count: int = 0,
    administration: GuildAdministration | None = None,
    images: dict[GuildImageVariant, str] | None = None,
    can: GuildCan | None = None,
    closed_contact: str | None = None,
) -> GuildRead:
    """Build one entry of the caller's own guild list.

    ``GuildRead`` carries two kinds of information and this is the single seam
    that decides who gets which:

    - **Everyone in the guild** — the guild's identity (name, description,
      icon), the caller's own membership (role, position), the roster size, and
      ``content_read_only`` so the UI can drop write affordances.
    - **Guild admins only** — the administration fields: the operator-set caps
      and plan label, the trash retention window, the lifecycle status, and the
      per-guild sign-in entitlement. Each backs an admin-only surface (the whole
      guild settings section is admin-gated, as is ``/c/{id}/storage/usage``,
      the panel's other half), so a regular member's payload leaves them
      ``None``.

    Most of the second group now arrives as ``administration`` — a separate row
    the caller may read but no request path may write. Callers serving a member
    pass ``None`` for it and never read the row at all.

    ``can`` is the caller's standing, where the caller has one
    (:func:`_can_of`); left out, the membership row answers.

    ``closed_contact`` is who a suspended guild's admins are told to contact;
    it reaches the payload only for that guild and that rung.
    """
    # The rung decides, not the caller: passing the row for a member still
    # serves a member's payload, so this stays the one place the split is made.
    is_admin = role.reaches(GuildRole.admin)
    admin_row = administration if is_admin else None
    return GuildRead(
        id=guild.id,
        name=guild.name,
        description=guild.description,
        created_at=guild.created_at,
        updated_at=guild.updated_at,
        role=role,
        can=_can_of_membership(guild, role) if can is None else can,
        position=position,
        # Trash retention window — set from the admin-only trash settings tab.
        retention_days=retention_days if is_admin else None,
        member_count=member_count,
        # Operator-set caps, shown against usage on the admin settings page.
        max_storage_bytes=admin_row.max_storage_bytes if admin_row else None,
        max_users=admin_row.max_users if admin_row else None,
        # Display-only plan label (never an enforcement input); the SPA shows
        # it only when a billing portal is configured.
        tier_name=admin_row.tier_name if admin_row else None,
        # Only guild admins learn the lifecycle status (for the closed entry
        # and the read-only notice); members get None so a moderation hold
        # isn't disclosed to them.
        status=GuildStatus(guild.status) if is_admin else None,
        # Every member learns the *effect* of a read_only hold (their writes
        # already fail at the DB role level) so the UI can drop write
        # affordances — without disclosing the status itself.
        content_read_only=(guild.status == GuildStatus.read_only.value),
        contact_email=(
            closed_contact
            if is_admin and guild.status == GuildStatus.suspended.value
            else None
        ),
        # Admins only: lets their settings UI show/hide the Authentication tab.
        # Derived, not stored — an option ticked under a master nobody granted
        # is not one this guild holds.
        auth_options=sorted(effective_options(admin_row.auth_options))
        if admin_row
        else None,
        # Admins only: the state of the API-access control on that tab.
        allow_api_keys=guild.allow_api_keys if is_admin else None,
        # Admins only: and of the session-limit control beside it.
        enforce_compliance_session=(
            guild.enforce_compliance_session if is_admin else None
        ),
        # Admins only: and of the second-factor control beside that.
        require_second_factor=(guild.require_second_factor if is_admin else None),
        # Guild identity, not administration: the directory publishes both to
        # strangers, so withholding them from the guild's own members would
        # only mean the settings page could not render its own state.
        is_community=guild.is_community,
        categories=[GuildCategory(value) for value in guild.categories],
        show_member_names=guild.show_member_names,
        has_adult_content=guild.has_adult_content,
        # Where the guild's pictures are, not the pictures. Callers that have
        # no reason to have looked them up pass nothing, which reads the same
        # as a guild without any. The rest of the banner is stored, so it needs
        # no such arrangement.
        icon_url=(images or {}).get(GuildImageVariant.icon),
        banner=GuildBannerRead(
            image_url=(images or {}).get(GuildImageVariant.full), **guild.banner
        ),
        # Read here rather than passed in, so every payload that names a guild
        # carries the same figure without each call site remembering to ask.
        # It costs no query — presence is a dict this process already holds.
        online_count=content_sockets.present_count(guild.id),
    )


_GUILD_PROFILE_FIELDS = (
    "name",
    "description",
    "banner",
    "is_community",
    "categories",
    "has_adult_content",
    "show_member_names",
)

#: What this community's notifications may leave the app carrying, for the
#: record.
_GUILD_NOTIFICATION_FIELDS = (
    "allow_push_notifications",
    "allow_email_notifications",
    "redact_notification_content",
)


async def _record_guild_settings_change(
    session: AsyncSession,
    *,
    guild_id: int,
    actor_user_id: int,
    area: str,
    before: dict[str, object],
    after: dict[str, object],
) -> None:
    """Record one area of a guild's settings, when that area moved."""
    changes = audit_service.changed_fields(before, after)
    if not changes["changed"]:
        return
    await audit_service.record(
        session,
        event_type=AuditEventType.GUILD_SETTINGS_CHANGED,
        actor_user_id=actor_user_id,
        guild_id=guild_id,
        target_type="guild",
        target_id=guild_id,
        detail={"area": area, **changes},
    )


@router.get("/", response_model=List[GuildRead])
async def list_guilds(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> List[GuildRead]:
    # A suspended account keeps every membership it had and reaches none of
    # them, so its guild list is empty — the same thing a suspended guild does
    # to its members' lists, and it keeps the app coherent rather than offering
    # doors that all refuse.
    if current_user.status == UserStatus.suspended:
        return []

    memberships = await guilds_service.list_memberships(
        session, user_id=current_user.id
    )
    # One query for the whole list, and only the digests — a guild list is
    # every guild the caller is in, and a banner is a third of a megabyte.
    images = await images_service.image_urls(
        session,
        [guild.id for guild, *_ in memberships],
        GuildImageVariant.icon,
        GuildImageVariant.full,
    )
    # Asked once, and only when a suspended guild is on the list — the only
    # entry that names who to contact.
    closed_contact = (
        await intake_service.contact_for(session, IntakeStream.moderation)
        if any(guild.status == GuildStatus.suspended.value for guild, *_ in memberships)
        else None
    )
    payloads: List[GuildRead] = []
    for guild, membership, retention_days, member_count, administration in memberships:
        payloads.append(
            _serialize_guild(
                guild,
                role=membership.role,
                position=membership.position,
                retention_days=retention_days,
                member_count=member_count,
                administration=administration,
                images=images.get(guild.id),
                closed_contact=closed_contact,
            )
        )
    return payloads


@router.put("/order", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def reorder_guilds(
    payload: GuildOrderUpdate,
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    await guilds_service.reorder_memberships(
        session,
        user_id=current_user.id,
        ordered_guild_ids=payload.guild_ids,
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


#: Directory pages are card grids; a bigger page buys scrolling, not answers.
MAX_COMMUNITY_PAGE_SIZE = 60


@router.get("/directory", response_model=CommunityGuildPage)
async def list_community_guilds(
    session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    q: str | None = Query(default=None, max_length=200),
    category: GuildCategory | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=MAX_COMMUNITY_PAGE_SIZE),
) -> CommunityGuildPage:
    """Browse the guilds that opted into the community directory.

    Runs on the system engine for the reason ``GET /invite/{code}`` does: the
    caller is a stranger to every guild here, so no guild-scoped role exists to
    read them under, and the RLS policy that scopes ``guilds`` to the caller's
    own memberships would return an empty directory. What that engine may see
    is not what this returns — the filters live in the service (listed AND
    active, always), and :class:`CommunityGuildRead` carries only what a guild
    published by opting in: no lifecycle status, no administration, no roster,
    and nothing at all from inside the guild's own schema. How many people have
    it open is a count of live connections, named to nobody.

    The directory is a deployment-level feature an owner switches on; where it
    is off there is nothing to browse and the request is refused rather than
    answered with an empty page.
    """
    try:
        rows, total = await guilds_service.list_community_guilds(
            session,
            user_id=current_user.id,
            query=q,
            category=category.value if category else None,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
    except guilds_service.CommunityDirectoryDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    # Who is present is live state held by the process, not a column, so it is
    # read here for the page being returned rather than joined in the query.
    online = content_sockets.present_counts(guild.id for guild, _, _ in rows)
    # Digests only, in one query: a card names its pictures, never carries them.
    images = await images_service.image_urls(
        session,
        [guild.id for guild, _, _ in rows],
        GuildImageVariant.icon,
        GuildImageVariant.card,
    )
    return CommunityGuildPage(
        items=[
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
                member_count=member_count,
                online_count=online.get(guild.id, 0),
                already_member=already_member,
            )
            for guild, member_count, already_member in rows
        ],
        total=total,
    )


@router.post("/directory/{guild_id}/join", response_model=GuildRead)
async def join_community_guild(
    guild_id: int,
    session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildRead:
    """Join a listed community guild. Its listing is the authorization.

    The system engine for the same reason ``accept_invite`` uses it — the user
    has no membership yet, so there is no guild role to write one under. Joining
    an already-joined guild is not an error; it returns the guild the caller is
    already in.
    """
    try:
        guild = await guilds_service.join_community_guild(
            session, guild_id=guild_id, user=current_user
        )
    except guilds_service.CommunityDirectoryDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except guilds_service.CommunityJoinError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except guilds_service.AgeConfirmationRequiredError as exc:
        # The one thing the caller can fix by answering, so it is its own code:
        # the SPA ticks the box and repeats the request.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except guilds_service.GuildCapacityError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    await session.commit()
    await cohorts.settle(session)
    membership = await guilds_service.get_membership(
        session, guild_id=guild.id, user_id=current_user.id
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=GuildMessages.GUILD_MEMBERSHIP_MISSING,
        )
    member_count = await guilds_service.count_members(session, guild_id=guild.id)
    return _serialize_guild(
        guild,
        role=membership.role,
        position=membership.position,
        member_count=member_count,
        # Joining is how the caller first earns the full-size banner they were
        # shown a card of.
        images=await images_service.image_urls_for(
            session, guild.id, GuildImageVariant.icon, GuildImageVariant.full
        ),
    )


@router.get("/invite/{code}", response_model=GuildInviteStatus)
async def get_invite_status(
    code: str,
    session: SystemSessionDep,
) -> GuildInviteStatus:
    invite, guild, is_valid, reason = await guilds_service.describe_invite_code(
        session, code=code
    )
    return GuildInviteStatus(
        code=code,
        guild_id=guild.id if guild else None,
        guild_name=guild.name if guild else None,
        is_valid=is_valid,
        reason=reason,
        expires_at=invite.expires_at if invite else None,
        max_uses=invite.max_uses if invite else None,
        uses=invite.uses if invite else None,
    )


async def _resolve_guild_owner(
    session: AsyncSession, guild_in: GuildCreate, current_user: User
) -> User:
    """Who the new guild's admin will be — the caller, unless a
    ``guilds.manage`` holder named someone else.

    Refused rather than ignored without that capability: creating the guild
    under the caller would answer 201 for a request that named another account.
    The named account must already exist and be active — this never creates
    one, and never hands a guild to an account that cannot sign in to run it.
    """
    requested = guild_in.owner_user_id
    if requested is None or requested == current_user.id:
        return current_user
    if not user_has_capability(current_user, Capability.GUILDS_MANAGE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.GUILD_OWNER_REQUIRES_CAPABILITY,
        )
    owner = await session.get(User, requested)
    if owner is None or owner.status is not UserStatus.active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildMessages.GUILD_OWNER_NOT_FOUND,
        )
    return owner


@router.post("/", response_model=GuildRead, status_code=status.HTTP_201_CREATED)
async def create_guild(
    guild_in: GuildCreate,
    session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildRead:
    """Create a new guild. Uses the system session because the guild doesn't exist
    yet — no guild context or membership exists for RLS to match against.

    The caller becomes the guild's admin, unless they hold ``guilds.manage``
    and name an ``owner_user_id``, which hands the guild to that account
    instead and leaves the caller holding nothing in it.
    """
    if settings.DISABLE_GUILD_CREATION and not user_has_capability(
        current_user, Capability.GUILDS_MANAGE
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.GUILD_CREATION_DISABLED,
        )
    name = guild_in.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.GUILD_NAME_REQUIRED,
        )

    owner = await _resolve_guild_owner(session, guild_in, current_user)

    if (
        billing_service.billing_inbound_enabled()
        and not user_has_capability(current_user, Capability.GUILDS_MANAGE)
        and await guilds_service.holds_a_free_guild(session, user_id=owner.id)
    ):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=GuildMessages.FREE_COMMUNITY_ALREADY_HELD,
        )

    # The guild's shared rows (guild + admin membership) live in public. Commit
    # them first so provisioning + the in-schema seed below run as a distinct,
    # compensatable step (on failure: deprovision + delete these committed rows).
    guild = await guilds_service.create_guild(
        session,
        name=name,
        description=guild_in.description,
        creator=current_user,
        owner=owner,
        actor_user_id=current_user.id,
    )
    await session.commit()
    if owner.id != current_user.id:
        # Both identities: created_by holds the first, the admin
        # membership the second.
        logger.info(
            "guild %s created by user %s on behalf of user %s",
            guild.id,
            current_user.id,
            owner.id,
        )
    try:
        # Provision the schema and create the guild-scoped seed rows (settings +
        # default initiative) *inside* it — so a new guild is schema-native from
        # birth, with private config (API keys, etc.) isolated in its schema.
        await guilds_service.seed_guild_content(
            session,
            guild_id=guild.id,
            owner=owner,
        )
    except Exception:
        logger.exception("Guild %s setup failed; rolling back", guild.id)
        with suppress(Exception):
            await deprovision_guild(guild.id)  # drops the schema + any partial content
        stale = await guilds_service.get_guild(session, guild_id=guild.id)
        if stale:
            stale_id = stale.id
            await guilds_service.delete_guild(
                session, stale, actor_user_id=current_user.id, via="provision_failed"
            )
            await session.commit()
            await app_refs.forget_guild(guild_id=stale_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=GuildMessages.GUILD_PROVISION_FAILED,
        )
    # Committed and seeded. Claimed for the owner — who holds the admin
    # membership — rather than the caller. Fire-and-forget.
    billing_claim.claim_new_guild(user_id=owner.id, guild_id=guild.id)

    # The owner's membership — the caller's own in the ordinary case. When the
    # guild was created for another account the caller holds none, so the
    # response describes the guild through its admin.
    membership = await guilds_service.get_membership(
        session, guild_id=guild.id, user_id=owner.id
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=GuildMessages.GUILD_MEMBERSHIP_CREATE_FAILED,
        )
    member_count = await guilds_service.count_members(session, guild_id=guild.id)
    # The creator is the new guild's admin, so their payload carries the
    # administration row — freshly created with the guild, all defaults.
    administration = await guilds_service.get_administration(session, guild_id=guild.id)
    return _serialize_guild(
        guild,
        role=membership.role,
        position=membership.position,
        member_count=member_count,
        administration=administration,
    )


@router.get("/{guild_id}/invites", response_model=List[GuildInviteRead])
async def list_guild_invites(
    guild_id: int,
    _guild_context: SettingsAdminContextDep,
    session: SettingsRLSSessionDep,
) -> List[GuildInviteRead]:
    invites = await guilds_service.list_guild_invites(session, guild_id=guild_id)
    return [GuildInviteRead.model_validate(invite) for invite in invites]


@router.get("/{guild_id}", response_model=GuildRead)
async def read_guild(
    guild_id: int,
    guild_context: SettingsAdminContextDep,
    session: SettingsRLSSessionDep,
) -> GuildRead:
    """The community as the caller's standing sees it — how a community
    reached by a settings grant, which has no entry in ``GET /communities/``, gets
    its entry and the answer to what the caller may change there.

    Without its pictures: a settings rung reads on the read-only floor, which
    holds no grant on the image digests.
    """
    guild = await guilds_service.get_guild(session, guild_id=guild_id)
    return _serialize_guild(
        guild,
        role=guild_context.rung,
        can=_can_of(guild_context),
        position=_position_of(guild_context),
        retention_days=await guilds_service.get_guild_retention_days(session),
        member_count=await guilds_service.count_members(session, guild_id=guild_id),
        administration=await guilds_service.get_administration(
            session, guild_id=guild_id
        ),
    )


@router.patch("/{guild_id}", response_model=GuildRead)
async def update_guild(
    guild_id: int,
    guild_context: SettingsAdminWriteContextDep,
    updates: GuildUpdate,
    session: SettingsRLSSessionDep,
    system_session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildRead:
    # Moving onto the shelf is measured against the roster the guild built
    # while it was private, and only on the way in — asked before the request
    # routes into its guild, because the answer lives in ``public.users``,
    # which a guild-scoped role does not read. A guild already listed is not
    # re-asked: the ways in keep it true from here, and failing an unrelated
    # edit over a member's answer would leave an admin nothing to do but
    # remove them.
    if updates.is_community:
        listed_before = (
            await guilds_service.get_guild(system_session, guild_id=guild_id)
        ).is_community
        if not listed_before:
            try:
                await guilds_service.assert_may_list_with_members(
                    system_session, guild_id=guild_id
                )
            except guilds_service.CommunityListingError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                ) from exc
    retention_days_provided = "retention_days" in updates.model_fields_set
    categories_provided = "categories" in updates.model_fields_set
    has_adult_content_provided = "has_adult_content" in updates.model_fields_set
    banner_provided = "banner" in updates.model_fields_set
    # The state this PATCH is measured against. Read before the write, since the
    # service edits the row in place.
    before_profile = audit_service.snapshot(
        await guilds_service.get_guild(session, guild_id=guild_id),
        _GUILD_PROFILE_FIELDS,
    )
    retention_before = (
        await guilds_service.get_guild_retention_days(session)
        if retention_days_provided
        else None
    )
    try:
        guild = await guilds_service.update_guild(
            session,
            guild_id=guild_id,
            name=updates.name,
            description=updates.description,
            retention_days=updates.retention_days,
            retention_days_provided=retention_days_provided,
            is_community=updates.is_community,
            categories=(
                [category.value for category in updates.categories]
                if updates.categories
                else []
            ),
            categories_provided=categories_provided,
            has_adult_content=updates.has_adult_content,
            has_adult_content_provided=has_adult_content_provided,
            banner=(updates.banner.model_dump(mode="json") if updates.banner else None),
            banner_provided=banner_provided,
            show_member_names=updates.show_member_names,
        )
    except guilds_service.CommunityDirectoryDisabledError as exc:
        # No directory on this deployment, so there is nothing to list in.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except guilds_service.BannerColorError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except guilds_service.CommunityListingError as exc:
        # The guild does not qualify to be listed. Named specifically (which
        # rule) rather than as a generic rejection, so the settings page can say
        # what to fix.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    await _record_guild_settings_change(
        session,
        guild_id=guild_id,
        actor_user_id=current_user.id,
        area="profile",
        before=before_profile,
        after=audit_service.snapshot(guild, _GUILD_PROFILE_FIELDS),
    )
    if retention_days_provided:
        await _record_guild_settings_change(
            session,
            guild_id=guild_id,
            actor_user_id=current_user.id,
            area="retention",
            before={"retention_days": retention_before},
            after={
                "retention_days": await guilds_service.get_guild_retention_days(session)
            },
        )
    await session.commit()
    retention_days = await guilds_service.get_guild_retention_days(session)
    member_count = await guilds_service.count_members(session, guild_id=guild_id)
    # Only a guild admin reaches this endpoint, so the caps belong in the reply.
    administration = await guilds_service.get_administration(session, guild_id=guild_id)
    return _serialize_guild(
        guild,
        role=guild_context.rung,
        can=_can_of(guild_context),
        position=_position_of(guild_context),
        retention_days=retention_days,
        member_count=member_count,
        administration=administration,
        images=await images_service.image_urls_for(
            session, guild_id, GuildImageVariant.icon, GuildImageVariant.full
        ),
    )


# --- icons and banners -------------------------------------------------------
#
# The pictures a guild is known by are the only guild media a stranger can be
# shown: a listed guild's icon and its banner's card rendition are what its
# community-directory card is made of. Which is why these routes are here on
# the platform router rather than under ``/c/{id}/…``, and why they run on the
# system engine — see ``guild_images.may_read_image`` for the rule and the
# reasoning.


@router.get("/{guild_id}/entitlements", response_model=GuildEntitlementsRead)
async def read_guild_entitlements(
    guild_id: int,
    _guild_context: SettingsAdminContextDep,
    session: SettingsRLSSessionDep,
) -> GuildEntitlementsRead:
    """What an operator has turned on for this guild, for its own admins.

    Its own read rather than fields on the guild payload: these are decisions
    made *about* a guild rather than by it, they live on the separate
    ``guild_administration`` row, and a member has no use for them. A guild
    admin does — it is how their settings page knows to offer the banner
    colour alone rather than an upload that would come back refused.
    """
    administration = await guilds_service.get_administration(session, guild_id=guild_id)
    return GuildEntitlementsRead(
        guild_id=guild_id,
        banner_image_enabled=(
            administration.banner_image_enabled if administration else True
        ),
    )


@router.get("/{guild_id}/image/{sha256}", include_in_schema=False)
@limiter.limit("600/minute")
async def read_guild_image(
    request: Request,
    guild_id: int,
    sha256: str,
    current_user: UploadUserDep,
    session: SystemSessionDep,
) -> Response:
    """Serve one of a guild's images.

    Authenticated like ``/uploads/*`` and for the same reason: this is an
    ``<img>`` src, so the credential is the HttpOnly session cookie on web and a
    short-lived uploads-scoped ``?token=`` in a native WebView.

    Everything that isn't served is a 404, whether the image does not exist,
    has since been replaced, or is not for this caller — a guild that has not
    published itself gives up nothing at all, its existence included.
    """
    image = await images_service.read_image(session, guild_id=guild_id, sha256=sha256)
    if image is None or not await images_service.may_read_image(
        session,
        guild_id=guild_id,
        user_id=current_user.id,
        variant=GuildImageVariant(image.variant),
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildMessages.IMAGE_NOT_FOUND,
        )
    return Response(
        content=image.data,
        media_type=image.content_type,
        headers={
            # The digest is in the path, so these bytes are these bytes
            # forever. ``private`` because who may have them is decided per
            # caller: a shared cache must never hand one viewer's copy on.
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def _store_guild_images(
    session: AsyncSession,
    *,
    guild_id: int,
    uploads: list[tuple[GuildImageVariant, UploadFile]],
) -> None:
    """Validate every part, then store them — never one and then the other.

    Each is checked on its own before anything is written: format read from the
    bytes rather than from the client's claim about them, weight, and shape.
    The system engine writes; no request-path role holds an INSERT here, and
    the caller's authority to be doing this at all was established against a
    real membership before this is reached.
    """
    renditions = []
    for variant, upload in uploads:
        try:
            data = await read_upload_bounded(upload, IMAGE_SPECS[variant].max_bytes)
        except FileTooLargeError:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=GuildMessages.IMAGE_TOO_LARGE,
            )
        try:
            renditions.append(
                images_service.validate_rendition(variant, data, upload.content_type)
            )
        except images_service.GuildImageError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

    await images_service.set_images(session, guild_id=guild_id, renditions=renditions)


@router.put("/{guild_id}/icon", response_model=GuildRead)
async def set_guild_icon(
    guild_id: int,
    guild_context: SettingsAdminWriteContextDep,
    session: SystemSessionDep,
    settings_session: SettingsRLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    icon: UploadFile = File(...),
) -> GuildRead:
    """Replace the guild's icon. One square picture, resized by the client."""
    await _store_guild_images(
        session,
        guild_id=guild_id,
        uploads=[(GuildImageVariant.icon, icon)],
    )
    await session.commit()
    return await _guild_payload_after_image_change(
        settings_session, guild_id=guild_id, guild_context=guild_context
    )


@router.delete("/{guild_id}/icon", response_model=GuildRead)
async def clear_guild_icon(
    guild_id: int,
    guild_context: SettingsAdminWriteContextDep,
    session: SystemSessionDep,
    settings_session: SettingsRLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildRead:
    """Remove the guild's icon. It falls back to its lettered avatar."""
    await images_service.clear_images(
        session, guild_id=guild_id, variants=[GuildImageVariant.icon]
    )
    await session.commit()
    return await _guild_payload_after_image_change(
        settings_session, guild_id=guild_id, guild_context=guild_context
    )


@router.put("/{guild_id}/banner", response_model=GuildRead)
async def set_guild_banner(
    guild_id: int,
    guild_context: SettingsAdminWriteContextDep,
    session: SystemSessionDep,
    settings_session: SettingsRLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    full: UploadFile = File(...),
    card: UploadFile = File(...),
) -> GuildRead:
    """Replace the guild's banner with the two renditions of one picture.

    The admin chooses a single image; the settings page resizes it to both
    renditions and sends them together, so a guild is never left showing a new
    card over an old front page.
    """
    administration = await guilds_service.get_administration(session, guild_id=guild_id)
    if administration is not None and not administration.banner_image_enabled:
        # Only uploading is gated. The banner surface stays, a banner the guild
        # already has keeps being served, and what a guild without artwork sets
        # instead is the colour on ``guilds.banner``, through PATCH.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.BANNER_IMAGE_NOT_ENTITLED,
        )
    await _store_guild_images(
        session,
        guild_id=guild_id,
        uploads=list(zip(BANNER_VARIANTS, (full, card))),
    )
    await session.commit()
    return await _guild_payload_after_image_change(
        settings_session, guild_id=guild_id, guild_context=guild_context
    )


@router.delete("/{guild_id}/banner", response_model=GuildRead)
async def clear_guild_banner(
    guild_id: int,
    guild_context: SettingsAdminWriteContextDep,
    session: SystemSessionDep,
    settings_session: SettingsRLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildRead:
    """Remove the guild's banner. Both surfaces fall back to their plain form."""
    await images_service.clear_images(
        session, guild_id=guild_id, variants=list(BANNER_VARIANTS)
    )
    await session.commit()
    return await _guild_payload_after_image_change(
        settings_session, guild_id=guild_id, guild_context=guild_context
    )


async def _guild_payload_after_image_change(
    session: AsyncSession,
    *,
    guild_id: int,
    guild_context: GuildContext,
) -> GuildRead:
    """The guild as its admin now sees it, so the SPA needs no follow-up read.

    Read on the route's own settings session, routed into the guild by the
    seam, once the image write on the system engine has committed. A
    ``GuildRead`` is not all public-schema: the trash retention window lives
    in the guild's own schema, and the routed session reads it, the roster
    size, the caps and the image digests as the admin the caller is.
    """
    guild = await guilds_service.get_guild(session, guild_id=guild_id)
    if guild is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=GuildMessages.GUILD_NOT_FOUND
        )
    return _serialize_guild(
        guild,
        role=guild_context.rung,
        can=_can_of(guild_context),
        position=_position_of(guild_context),
        retention_days=await guilds_service.get_guild_retention_days(session),
        member_count=await guilds_service.count_members(session, guild_id=guild_id),
        administration=await guilds_service.get_administration(
            session, guild_id=guild_id
        ),
        images=await images_service.image_urls_for(
            session, guild_id, GuildImageVariant.icon, GuildImageVariant.full
        ),
    )


@router.post(
    "/{guild_id}/billing/handoff",
    response_model=BillingPortalHandoffResponse,
)
async def create_guild_billing_handoff(
    guild_id: int,
    seat_session: SeatWriteSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> BillingPortalHandoffResponse:
    """Mint a billing-portal handoff. The guild's superadmin only.

    What a community pays for is the top seat's, like its sign-in: an ordinary
    admin runs the place without holding its card.
    """
    if not settings.BILLING_URL:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=BillingMessages.PORTAL_NOT_CONFIGURED,
        )

    guild = await seat_session.get(Guild, guild_id)

    try:
        user_ref, guild_ref = await billing_refs(
            user_id=current_user.id, guild_id=guild_id
        )
        token, expires_in_seconds = create_billing_portal_handoff_token(
            # The portal's own vocabulary, which is not this enum: it knows
            # "the person who may act for this guild", and only the seat
            # reaches here to say so.
            guild_role=GuildRole.admin.value,
            user_ref=user_ref,
            guild_ref=guild_ref,
            guild_name=guild.name if guild is not None else None,
        )
    except HandoffSigningNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=BillingMessages.PORTAL_SIGNING_NOT_CONFIGURED,
        ) from exc

    return BillingPortalHandoffResponse(
        handoff_token=token,
        expires_in_seconds=expires_in_seconds,
    )


@router.get(
    "/{guild_id}/billing/payment-issue",
    response_model=GuildPaymentIssueRead,
)
@limiter.limit("6/minute", key_func=get_user_or_ip_key)
async def read_guild_payment_issue(
    request: Request,
    guild_id: int,
    seat_session: SeatSessionDep,
) -> GuildPaymentIssueRead:
    guild = await seat_session.get(Guild, guild_id)
    if (
        guild is None
        or guild.status == GuildStatus.active.value
        or not settings.BILLING_URL
    ):
        return GuildPaymentIssueRead()
    return GuildPaymentIssueRead(
        payment_failed=await billing_ping.guild_payment_failed(guild_id)
    )


async def _require_guild_auth_option(
    system_session: AsyncSession, guild_id: int, option: GuildAuthOption
) -> None:
    """One operator-granted sign-in option, or 404.

    This bounds *management* only. Withdrawing an option closes the surface
    that sets it up; it never deletes providers, keeps existing members signing
    in through them, and leaves any requirement already set enforced.
    """
    if not await guild_entitlements.has_auth_option(system_session, guild_id, option):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildMessages.GUILD_AUTH_NOT_ENABLED,
        )


def _auth_policy_refusal(detail: str, unmet: str) -> HTTPException:
    """A refused requirement, naming the part of it that was refused."""
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=detail,
        headers={AUTH_POLICY_UNMET_HEADER: unmet},
    )


def _auth_policy_read(
    policy_row,
    provider_display_name: str | None = None,
    *,
    factor_required_by_platform: bool = False,
) -> GuildAuthPolicyRead:
    if policy_row is None or policy_row.policy == "open":
        return GuildAuthPolicyRead(
            policy="open", factor_required_by_platform=factor_required_by_platform
        )
    return GuildAuthPolicyRead(
        policy="required",
        provider_id=policy_row.provider_id,
        provider_slug=policy_row.provider_slug,
        provider_display_name=provider_display_name,
        require_methods=list(policy_row.require_methods or ()),
        factor_required_by_platform=factor_required_by_platform,
    )


async def _platform_asks_everyone(session) -> bool:
    """Whether the deployment already asks every account for a second factor.

    The one level that makes a community's own box redundant: asking the
    platform rungs leaves a community's members untouched, so that box stays.
    """
    level = await auth_posture.second_factor_requirement(session)
    return level is SecondFactorRequirement.everyone


@router.get("/{guild_id}/auth-settings", response_model=GuildAuthSettingsRead)
async def get_guild_auth_settings(
    guild_id: int,
    seat_session: SeatSessionDep,
) -> GuildAuthSettingsRead:
    """Read the controls held by this community's superadmin seat."""
    guild = await seat_session.get(Guild, guild_id)
    if guild is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=GuildMessages.GUILD_NOT_FOUND
        )
    administration = await guilds_service.get_administration(
        seat_session, guild_id=guild_id
    )
    return GuildAuthSettingsRead(
        auth_options=sorted(effective_options(administration.auth_options))
        if administration
        else [],
        allow_api_keys=guild.allow_api_keys,
        enforce_compliance_session=guild.enforce_compliance_session,
        require_second_factor=guild.require_second_factor,
        allow_push_notifications=guild.allow_push_notifications,
        allow_email_notifications=guild.allow_email_notifications,
        redact_notification_content=guild.redact_notification_content,
    )


def _notification_policy_read(
    guild: Guild, platform: notification_policy.NotificationPolicy
) -> GuildNotificationPolicyRead:
    """This community's three answers, beside the deployment's."""
    return GuildNotificationPolicyRead(
        allow_push_notifications=guild.allow_push_notifications,
        allow_email_notifications=guild.allow_email_notifications,
        redact_notification_content=guild.redact_notification_content,
        push_allowed_by_platform=platform.push,
        email_allowed_by_platform=platform.email,
        redacted_by_platform=platform.redact,
    )


@router.get(
    "/{guild_id}/notification-policy", response_model=GuildNotificationPolicyRead
)
async def get_guild_notification_policy(
    guild_id: int,
    seat_session: SeatSessionDep,
) -> GuildNotificationPolicyRead:
    """What this community's notifications may leave the app carrying."""
    await _require_guild_auth_option(
        seat_session, guild_id, GuildAuthOption.restrictions
    )
    guild = await seat_session.get(Guild, guild_id)
    if guild is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=GuildMessages.GUILD_NOT_FOUND
        )
    return _notification_policy_read(
        guild, await notification_policy.resolve(seat_session, None)
    )


@router.put(
    "/{guild_id}/notification-policy", response_model=GuildNotificationPolicyRead
)
async def set_guild_notification_policy(
    guild_id: int,
    payload: GuildNotificationPolicyUpdate,
    seat_session: SeatWriteSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildNotificationPolicyRead:
    """Decide what this community's notifications may leave the app carrying.

    Three answers: whether one may reach a phone, whether one may reach a
    mailbox, and whether what it says may name the thing it is about. Each is
    also asked of the deployment, and the stricter of the pair applies — so
    this surface only ever narrows, and a deployment that has already declined
    a channel leaves nothing here to decline.

    The same seat as the three beside it, and for the same reason: it says what
    is done on this community's behalf rather than how it is run. The bell
    inside the app is unaffected, and so is what an account is sent about
    itself — a sign-in code and a password reset are not notifications.
    """
    await _require_guild_auth_option(
        seat_session, guild_id, GuildAuthOption.restrictions
    )
    guild = await seat_session.get(Guild, guild_id)
    if guild is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=GuildMessages.GUILD_NOT_FOUND
        )
    before = audit_service.snapshot(guild, _GUILD_NOTIFICATION_FIELDS)
    guild.allow_push_notifications = payload.allow_push_notifications
    guild.allow_email_notifications = payload.allow_email_notifications
    guild.redact_notification_content = payload.redact_notification_content
    seat_session.add(guild)
    await _record_guild_settings_change(
        seat_session,
        guild_id=guild_id,
        actor_user_id=current_user.id,
        area="notifications",
        before=before,
        after=audit_service.snapshot(guild, _GUILD_NOTIFICATION_FIELDS),
    )
    await seat_session.commit()
    return _notification_policy_read(
        guild, await notification_policy.resolve(seat_session, None)
    )


@router.get("/{guild_id}/auth-policy", response_model=GuildAuthPolicyRead)
async def get_guild_auth_policy(
    guild_id: int,
    _guild_context: SettingsAdminContextDep,
    system_session: SystemSessionDep,
) -> GuildAuthPolicyRead:
    """The guild's sign-in requirement. Guild admin only (the settings UI);
    a blocked session learns the required provider from the step-up 401's
    header, not from here.

    Readable whatever the guild's entitlement, because a requirement stays
    enforced through changes to it (the gate in ``deps.py`` and
    ``public.guild_auth_satisfied()`` read the policy row and nothing else).
    An admin who cannot see what is set cannot clear it."""
    policy_row = await system_session.get(GuildAuthPolicy, guild_id)
    display_name = None
    if policy_row is not None and policy_row.provider_id is not None:
        provider = await system_session.get(AuthProvider, policy_row.provider_id)
        display_name = provider.display_name if provider else None
    return _auth_policy_read(
        policy_row,
        display_name,
        factor_required_by_platform=await _platform_asks_everyone(system_session),
    )


@router.put("/{guild_id}/auth-policy", response_model=GuildAuthPolicyRead)
async def set_guild_auth_policy(
    guild_id: int,
    payload: GuildAuthPolicyUpdate,
    session: SeatWriteSessionDep,
    system_session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildAuthPolicyRead:
    """Set the guild's sign-in requirement. Guild admin only.

    ``open`` deletes the stored row (no row IS open). ``required`` names one
    of the guild's own login-ready providers — and the calling admin's own
    session must already satisfy it, which both proves the provider works
    end-to-end and keeps an admin from locking their guild (and themselves)
    behind a sign-in they haven't completed.

    The two verbs are gated differently, and deliberately. Setting a
    requirement needs the guild's entitlement, as before. **Clearing one is
    always reachable**: enforcement reads the policy row alone, so a
    requirement outlives the entitlement and the way to lift one outlives it
    too. Lifting only ever admits more, so it carries none of the conditions
    imposing it does."""
    if payload.policy == "open":
        policy_row = await session.get(GuildAuthPolicy, guild_id)
        if policy_row is not None:
            await audit_service.record(
                session,
                event_type=AuditEventType.GUILD_AUTH_POLICY_CHANGED,
                actor_user_id=current_user.id,
                guild_id=guild_id,
                target_type="guild",
                target_id=guild_id,
                detail={
                    "from": policy_row.policy,
                    "to": "open",
                    "provider_id": None,
                    "require_methods": [],
                },
            )
            await session.delete(policy_row)
            await session.commit()
        return GuildAuthPolicyRead(
            policy="open",
            factor_required_by_platform=await _platform_asks_everyone(system_session),
        )

    await _require_guild_auth_option(
        system_session, guild_id, GuildAuthOption.providers
    )
    # Hold the settings row for the rest of this transaction. An operator
    # withdrawing single sign-on takes the same row exclusively, so the two
    # order rather than interleave: either they see this requirement and are
    # told, or this sees single sign-on already gone and its provider is no
    # longer login-ready.
    await auth_posture.hold_settings_for_read(system_session)
    # And order against the seat: a requirement must not commit while the only
    # member who could lift it is being demoted, removed, or leaving. Taken on
    # the session that performs the write, which is what the lock has to
    # outlive.
    await guilds_service.lock_guild_seats(session, guild_id)

    require_methods: list[str] = sorted({str(m) for m in payload.require_methods})
    if payload.provider_id is None and not require_methods:
        # ``required`` has to require something.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.GUILD_AUTH_POLICY_INVALID_PROVIDER,
        )

    provider = None
    if payload.provider_id is not None:
        # Read, not held. The write below carries a foreign key to this row,
        # and that is what keeps it still: the insert takes its own lock on the
        # provider through the key, so a delete racing it waits rather than
        # winning. An explicit lock here could not do that job any more — it
        # would be taken on the system engine while the write happens on the
        # request path, which is two connections contending for one row.
        provider = await system_session.get(AuthProvider, payload.provider_id)
        # Theirs because they connect to it. Every provider is the operator's,
        # so a connection is what makes one this community's to require.
        connection = (
            None
            if provider is None
            else await guild_connections.connection_for(
                system_session, guild_id=guild_id, provider_id=provider.id
            )
        )
        if provider is None or connection is None or not is_login_ready(provider):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=GuildMessages.GUILD_AUTH_POLICY_INVALID_PROVIDER,
            )
        if provider.id not in satisfied_provider_ids():
            raise _auth_policy_refusal(
                GuildMessages.GUILD_AUTH_POLICY_SELF_UNSATISFIED, "provider"
            )

    # The same rule the provider check makes, for "any of ours": the caller's
    # own session must have come in that way. Meeting it is also proof the
    # community has a provider that works, so there is nothing else to ask.
    # One check per method the list may hold; ``sso`` is the only one it can
    # hold today, and a method added to the vocabulary brings its own.
    if LoginMethod.sso in require_methods and not (
        await guild_connections.admits_this_session(system_session, guild_id=guild_id)
    ):
        raise _auth_policy_refusal(
            GuildMessages.GUILD_AUTH_POLICY_SELF_UNSATISFIED, LoginMethod.sso.value
        )

    # And the one a second factor brings. Two things before a community may ask
    # for it: the deployment offers it at all, and the person writing the rule
    # has presented one. The second is the same "prove it before it binds
    # anybody" the provider check makes, so a rule is only ever written by
    # somebody it already applies to.
    if LoginMethod.totp in require_methods:
        if not await auth_posture.login_method_allowed(
            system_session, LoginMethod.totp
        ):
            raise _auth_policy_refusal(
                GuildMessages.GUILD_AUTH_POLICY_METHOD_UNAVAILABLE,
                LoginMethod.totp.value,
            )
        if SECOND_FACTOR_AMR not in auth_context.session_amr():
            raise _auth_policy_refusal(
                GuildMessages.GUILD_AUTH_POLICY_SELF_UNSATISFIED, LoginMethod.totp.value
            )

    # And the one a passkey brings, on the same two conditions. Read from the
    # passkey markers rather than the factor's, so holding a second factor is
    # not taken for holding a key.
    if LoginMethod.passkey in require_methods:
        if not await auth_posture.login_method_allowed(
            system_session, LoginMethod.passkey
        ):
            raise _auth_policy_refusal(
                GuildMessages.GUILD_AUTH_POLICY_METHOD_UNAVAILABLE,
                LoginMethod.passkey.value,
            )
        if not carries_passkey(auth_context.session_amr()):
            raise _auth_policy_refusal(
                GuildMessages.GUILD_AUTH_POLICY_SELF_UNSATISFIED,
                LoginMethod.passkey.value,
            )

    policy_row = await session.get(GuildAuthPolicy, guild_id)
    # No row is "open", so a guild that had none is moving from there.
    was = (
        ("open", None, [])
        if policy_row is None
        else (
            policy_row.policy,
            policy_row.provider_id,
            list(policy_row.require_methods or ()),
        )
    )
    if policy_row is None:
        policy_row = GuildAuthPolicy(guild_id=guild_id, policy="required")
    policy_row.policy = "required"
    policy_row.provider_id = provider.id if provider else None
    policy_row.provider_slug = provider.slug if provider else None
    policy_row.require_methods = require_methods
    session.add(policy_row)
    if was != ("required", policy_row.provider_id, require_methods):
        await audit_service.record(
            session,
            event_type=AuditEventType.GUILD_AUTH_POLICY_CHANGED,
            actor_user_id=current_user.id,
            guild_id=guild_id,
            target_type="guild",
            target_id=guild_id,
            detail={
                "from": was[0],
                "to": "required",
                "provider_id": policy_row.provider_id,
                "require_methods": require_methods,
            },
        )
    await session.commit()
    return _auth_policy_read(
        policy_row,
        provider.display_name if provider else None,
        factor_required_by_platform=await _platform_asks_everyone(system_session),
    )


@router.put("/{guild_id}/api-access", response_model=GuildApiAccessRead)
async def set_guild_api_access(
    guild_id: int,
    payload: GuildApiAccessUpdate,
    seat_session: SeatWriteSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildApiAccessRead:
    """Decide whether this guild accepts personal API keys.

    The same seat as the sign-in requirement, and for the same reason: it says
    what may be used to reach the community, which is not the job of running
    one. Like everything else on that surface it needs the master entitlement,
    which most guilds never hold — a community that configures no part of its
    own sign-in is not asked about API keys either.

    Existing keys are left alone. What they may reach is decided when they are
    used, so switching this back on restores them rather than leaving somebody
    to mint replacements.
    """
    await _require_guild_auth_option(
        seat_session, guild_id, GuildAuthOption.restrictions
    )
    guild = await seat_session.get(Guild, guild_id)
    if guild is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=GuildMessages.GUILD_NOT_FOUND
        )
    before = {"allow_api_keys": guild.allow_api_keys}
    guild.allow_api_keys = payload.allow_api_keys
    seat_session.add(guild)
    await _record_guild_settings_change(
        seat_session,
        guild_id=guild_id,
        actor_user_id=current_user.id,
        area="api_access",
        before=before,
        after={"allow_api_keys": guild.allow_api_keys},
    )
    await seat_session.commit()
    return GuildApiAccessRead(allow_api_keys=guild.allow_api_keys)


@router.put("/{guild_id}/second-factor", response_model=GuildSecondFactorRead)
async def set_guild_second_factor(
    guild_id: int,
    payload: GuildSecondFactorUpdate,
    seat_session: SeatWriteSessionDep,
    system_session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildSecondFactorRead:
    """Ask for a second factor from everybody reaching this community.

    The same seat as the two beside it, and separate from the sign-in
    requirement on purpose: a community that lets its members arrive however
    they like may still ask them to hold a factor, and lifting the sign-in
    requirement does not lift this.

    Which kinds of factor exist is the deployment's answer, and so is which
    providers' own account of one counts. The community asks; it does not say
    how the question is answered.
    """
    await _require_guild_auth_option(
        seat_session, guild_id, GuildAuthOption.restrictions
    )
    guild = await seat_session.get(Guild, guild_id)
    if guild is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=GuildMessages.GUILD_NOT_FOUND
        )
    available = await auth_posture.second_factor_available(system_session)
    if payload.require_second_factor and not available:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.GUILD_AUTH_POLICY_METHOD_UNAVAILABLE,
        )
    # The seat answers its own requirement before raising it — the same
    # question the deployment's own setting asks, and the same answer: a
    # factor held, or one this session presented.
    if payload.require_second_factor and not await auth_posture.answers_the_rule(
        system_session, user=current_user
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.GUILD_AUTH_POLICY_SELF_UNSATISFIED,
            headers={AUTH_POLICY_UNMET_HEADER: LoginMethod.totp.value},
        )
    before = {"require_second_factor": guild.require_second_factor}
    guild.require_second_factor = payload.require_second_factor
    seat_session.add(guild)
    await _record_guild_settings_change(
        seat_session,
        guild_id=guild_id,
        actor_user_id=current_user.id,
        area="second_factor",
        before=before,
        after={"require_second_factor": guild.require_second_factor},
    )
    await seat_session.commit()
    return GuildSecondFactorRead(
        require_second_factor=guild.require_second_factor, available=available
    )


@router.put("/{guild_id}/session-limit", response_model=GuildSessionLimitRead)
async def set_guild_session_limit(
    guild_id: int,
    payload: GuildSessionLimitUpdate,
    seat_session: SeatWriteSessionDep,
    system_session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildSessionLimitRead:
    """Hold this guild's members to the twelve-hour session standard, or stop.

    The same seat as the sign-in requirement beside it: how often somebody
    signs in again is part of what the community asks of a session, not part of
    running it. One standard rather than a figure of the guild's own, so
    somebody in two communities that ask for it has an answer and not a
    comparison. It needs the master entitlement, like the rest of the surface.

    It reaches members' sessions at their next sign-in. Phones are the
    exception: a device token carries its deadline in its own expiry, so the
    ones already issued are brought under the standard here — which can sign a
    phone out at once, where it signed in longer ago than the standard allows.
    """
    await _require_guild_auth_option(
        seat_session, guild_id, GuildAuthOption.restrictions
    )
    guild = await seat_session.get(Guild, guild_id)
    if guild is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=GuildMessages.GUILD_NOT_FOUND
        )
    changed = guild.enforce_compliance_session != payload.enforce_compliance_session
    before = {"enforce_compliance_session": guild.enforce_compliance_session}
    guild.enforce_compliance_session = payload.enforce_compliance_session
    seat_session.add(guild)
    await _record_guild_settings_change(
        seat_session,
        guild_id=guild_id,
        actor_user_id=current_user.id,
        area="session_limit",
        before=before,
        after={"enforce_compliance_session": guild.enforce_compliance_session},
    )
    # Committed before the sweep below, which reads the standard back off the
    # guild row to find whose phones it applies to — and runs on the system
    # engine, because a device token belongs to an account rather than to this
    # community.
    await seat_session.commit()
    if changed:
        await session_lifetime.apply_to_device_tokens(system_session)
        await system_session.commit()
    return GuildSessionLimitRead(
        enforce_compliance_session=guild.enforce_compliance_session
    )


@router.delete(
    "/{guild_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
async def delete_guild(
    guild_id: int,
    _guild_context: SettingsSeatWriteContextDep,
    http_request: Request,
    request: GuildDeletionRequest,
    session: SettingsRLSSessionDep,
    system_session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    # The seat, not an ordinary admin. Deleting a community is the one action
    # an admin cannot undo and cannot be undone for them — only an operator
    # can, and only inside the retention window — so it sits with the seat
    # that is told about it and that a restore needs (``guild_has_seat``).
    guild = await guilds_service.get_guild(session, guild_id=guild_id)

    # Re-check the password, where the account holds one to re-check — the
    # same gate the account-deletion endpoint asks. An account that signs in
    # another way has none to supply, and answers with a recent sign-in and the
    # phrase. 400 not 401 so the SPA's axios interceptor doesn't treat a wrong
    # password as a session expiry and force-log-out the user
    # mid-confirmation.
    await require_password_or_recent_proof(
        http_request,
        system_session,
        current_user,
        request.password,
        detail=GuildMessages.INVALID_PASSWORD,
    )

    # The whole phrase is uppercased, including the name, so casing on
    # the guild name can't trip up the confirmation.
    expected = f"DELETE COMMUNITY {guild.name.upper()}"
    if request.confirmation_text != expected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.CONFIRMATION_MISMATCH,
        )

    # End the guild's app access. The guild has withdrawn its authorization, so
    # each app is told to let go now rather than at the end of the retention
    # window — a restored guild comes back with its apps disconnected, and an
    # admin reconnects them.
    #
    # On the REQUEST session, which is the one that can reach these rows: they
    # live in the guild's own schema, and the grants that read and write them
    # belong to the guild role as the request path assumes it. The system
    # engine cannot stand in for it here.
    #
    # That makes this a separate transaction from the status write below, which
    # the guild role in turn cannot do (``app_guild_base`` holds UPDATE on the
    # identity columns a guild admin edits, and deliberately not on ``status``).
    # The connections go first: a guild left live with its integrations ended
    # is a thing its admin can see and put back, and the revocations are not
    # dispatched until the deletion below has actually committed.
    await app_connections_service.delete_guild_connections(session)
    await session.commit()

    # Move the guild to ``deleted`` and keep everything: the shared rows, the
    # guild_<id> schema and the stored blobs all stay, so a platform operator
    # can put the community back inside the retention window. Nothing is
    # destroyed until guild_purge runs, which is when the shared row, the
    # schema and the blobs go — the sequence this endpoint used to run inline.
    #
    # From here the guild is gone as far as everybody in it is concerned:
    # absent from their guild lists and refused on every path, admins included.
    guild_row = await guilds_service.get_guild(system_session, guild_id=guild_id)
    notice = await guilds_service.soft_delete_guild(
        system_session, guild_row, actor_user_id=current_user.id, via="admin"
    )
    await system_session.commit()
    # The receipt, once the deletion is a fact. Never allowed to fail it.
    await email_service.announce_community_deleted(system_session, notice)
    # See soft_delete_guild: these live on another connection, so they go after
    # the commit that made the deletion real. Billing keeps its name for the
    # guild until the purge, and is told to go and read what happened to it.
    await app_refs.forget_guild(guild_id=guild_id, keep_billing=True)
    billing_ping.notify_lifecycle_changed(guild_id)
    await app_revocation_service.dispatch_revocations(
        app_revocation_service.drain_revocations(session)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{guild_id}/invites",
    response_model=GuildInviteRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_guild_invite(
    guild_id: int,
    _guild_context: SettingsAdminWriteContextDep,
    invite_in: GuildInviteCreate,
    session: SettingsRLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildInviteRead:
    try:
        invite = await guilds_service.create_guild_invite(
            session,
            guild_id=guild_id,
            created_by=current_user.id,
            expires_at=invite_in.expires_at,
            max_uses=invite_in.max_uses,
            invitee_email=invite_in.invitee_email,
            actor_user_id=current_user.id,
        )
    except guilds_service.GuildCapacityError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    await session.commit()
    return GuildInviteRead.model_validate(invite)


@router.delete(
    "/{guild_id}/invites/{invite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_guild_invite(
    guild_id: int,
    _guild_context: SettingsAdminWriteContextDep,
    invite_id: int,
    session: SettingsRLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    await guilds_service.delete_guild_invite(
        session,
        guild_id=guild_id,
        invite_id=invite_id,
        actor_user_id=current_user.id,
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/invite/accept", response_model=GuildRead)
async def accept_invite(
    payload: GuildInviteAcceptRequest,
    session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildRead:
    """Accept a guild invite. Uses the system session because the user doesn't
    belong to the guild yet — the invite code is the authorization."""
    try:
        guild = await guilds_service.redeem_invite_for_user(
            session, code=payload.code, user=current_user
        )
    except guilds_service.GuildInviteError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except guilds_service.GuildCapacityError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except guilds_service.AgeConfirmationRequiredError as exc:
        # The invite leads into a listed community, so the age question applies
        # to it. Same code the directory's Join returns, so the SPA answers it
        # the same way wherever the invite was opened.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    await session.commit()
    await cohorts.settle(session)
    membership = await guilds_service.get_membership(
        session, guild_id=guild.id, user_id=current_user.id
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=GuildMessages.GUILD_MEMBERSHIP_MISSING,
        )
    member_count = await guilds_service.count_members(session, guild_id=guild.id)
    return _serialize_guild(
        guild,
        role=membership.role,
        position=membership.position,
        member_count=member_count,
        # Joining is how the caller first earns the full-size banner they were
        # shown a card of.
        images=await images_service.image_urls_for(
            session, guild.id, GuildImageVariant.icon, GuildImageVariant.full
        ),
    )


@router.patch(
    "/{guild_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def update_guild_membership(
    guild_id: int,
    guild_context: SettingsAdminWriteContextDep,
    user_id: int,
    payload: GuildMembershipUpdate,
    session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    """Update a user's guild membership role. Guild admin only.

    Restrictions:
    - Cannot change your own role
    - Cannot demote the last guild admin
    """
    # Runs on the system engine (SystemSessionDep): the guild role holds no UPDATE
    # on guild_memberships, so a role change happens only here, after the
    # guild-admin check — never under a request-path role. See migration 0145.

    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.CANNOT_CHANGE_OWN_ROLE,
        )

    # 'support' is a synthesized PAM identity, never a stored membership role.
    if payload.role == GuildRole.support:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.GUILD_ROLE_NOT_ASSIGNABLE,
        )

    # The seat is passed on by whoever holds it, and by nobody below it. A
    # superadmin seats another — one by membership, or one holding the seat
    # through a settings grant, which is how a community whose only holder
    # cannot pass it on gets a new one. An ordinary admin may do neither,
    # which is the separation.
    if payload.role not in assignable_roles(guild_context.rung):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.GUILD_ROLE_NOT_ASSIGNABLE,
        )

    await guilds_service.lock_guild_seats(session, guild_id)
    target_membership = await guilds_service.get_membership(
        session, guild_id=guild_id, user_id=user_id, for_update=True
    )
    if target_membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildMessages.USER_NOT_FOUND_IN_GUILD,
        )

    # And taking the seat away is the same authority as giving it. Asked of the
    # *locked* row, so the role this decides on is the role as it stands now.
    if (
        target_membership.role == GuildRole.superadmin
        and guild_context.rung != GuildRole.superadmin
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.GUILD_ROLE_NOT_ASSIGNABLE,
        )

    # What a guild must keep is its seat. An ordinary admin is not counted:
    # every guild has a superadmin, and a superadmin is an admin, so "the last
    # admin" could only ever have been the seat — which the rule below holds.
    if (
        target_membership.role == GuildRole.superadmin
        and payload.role != GuildRole.superadmin
        and await guilds_service.must_keep_superadmin(
            session, guild_id=guild_id, user_id=user_id
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.CANNOT_VACATE_LAST_SUPERADMIN,
        )

    previous_role = target_membership.role
    target_membership.role = payload.role
    session.add(target_membership)
    if GuildRole.superadmin in (previous_role, payload.role):
        # The seat moving is its own event, apart from an ordinary role
        # change.
        await audit_service.record(
            session,
            event_type=AuditEventType.GUILD_SUPERADMIN_CHANGED,
            actor_user_id=current_user.id,
            target_user_id=user_id,
            guild_id=guild_id,
            target_type="guild",
            target_id=guild_id,
            detail={"from": previous_role.value, "to": payload.role.value},
        )
    elif previous_role != payload.role:
        await audit_service.record(
            session,
            event_type=AuditEventType.GUILD_MEMBER_ROLE_CHANGED,
            actor_user_id=current_user.id,
            target_user_id=user_id,
            guild_id=guild_id,
            target_type="guild",
            target_id=guild_id,
            detail={"from": previous_role.value, "to": payload.role.value},
        )
    # A promotion changes the guild role underneath initiative rows that already
    # exist; bring them up to the manager role an admin's row carries.
    guilds_service.align_admin_initiative_roles(
        session, guild_id=guild_id, user_id=user_id, role=payload.role
    )
    await session.commit()
    await cohorts.settle(session)
    # Guild-level access change (e.g. admin → member loses the guild-admin
    # bypass): re-check this user's live content streams now so the change takes
    # effect immediately, not on the next bounded re-auth tick.
    await content_sockets.revoke_user(guild_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{guild_id}/leave/eligibility", response_model=LeaveGuildEligibilityResponse
)
async def check_leave_eligibility(
    guild_id: int,
    session: UserSessionDep,
    system_session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> LeaveGuildEligibilityResponse:
    """Check if the current user can leave a guild.

    Holding its only superadmin seat is the one thing that stops them. Content
    they own is released on the way out and left unowned for a guild admin to
    claim, so there is nothing to hand over first.
    """
    membership = await guilds_service.get_membership(
        session, guild_id=guild_id, user_id=current_user.id
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=GuildMessages.NOT_GUILD_MEMBER
        )

    # Under the lock, so the answer still holds when the caller acts on it.
    # Counting a guild's seats is a question about the guild rather than about
    # the caller, so it is asked on the system engine.
    await guilds_service.lock_guild_seats(system_session, guild_id)
    is_last_superadmin = await guilds_service.would_strand_guild(
        system_session, guild_id=guild_id, user_id=current_user.id
    )

    return LeaveGuildEligibilityResponse(
        can_leave=not is_last_superadmin,
        is_last_superadmin=is_last_superadmin,
    )


@router.delete(
    "/{guild_id}/leave", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
async def leave_guild(
    guild_id: int,
    session: UserSessionDep,
    system_session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    """Leave a guild.

    Being the guild's last admin is the only restriction. Content the leaver
    owns is released — left unowned for a guild admin to claim — rather than
    handed to someone who did not ask for it.
    """
    membership = await guilds_service.get_membership(
        session, guild_id=guild_id, user_id=current_user.id
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=GuildMessages.NOT_GUILD_MEMBER
        )

    # ``UserSessionDep`` only sets the user_id; releasing the leaver's owner
    # grants below writes to guild-scoped tables whose RLS is evaluated against
    # the current guild context. Now that membership is confirmed, set the full
    # context so those writes aren't filtered to zero rows. Leaving is about
    # the membership row rather than the community's content, so it routes the
    # way its configuration surface does — and, like that surface, not while
    # the community is suspended: its membership stays as it was until then.
    try:
        await establish_guild_access(session, current_user, guild_id, for_settings=True)
    except GuildAccessError as exc:
        raise_for_guild_access(exc)

    # Ahead of the check below, so its answer is still true when the departure
    # is written. Counting a guild's seats is a question about the guild rather
    # than about the caller, so it is asked on the system engine.
    await guilds_service.lock_guild_seats(system_session, guild_id)

    # The seat is what a guild has to keep. An ordinary admin may leave freely:
    # every guild has a superadmin, so the community is never left without one.
    # And the only member of a community may leave whatever they hold — there
    # is nobody there to strand.
    if await guilds_service.would_strand_guild(
        system_session, guild_id=guild_id, user_id=current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.CANNOT_VACATE_LAST_SUPERADMIN,
        )

    # Ownership release happens inside remove_user_from_guild, while the
    # leaver's membership rows are still in place for RLS to match.
    await guilds_service.remove_user_from_guild(
        session, guild_id=guild_id, user_id=current_user.id
    )

    await session.commit()
    # Left the guild — drop this user's live content streams immediately.
    await content_sockets.revoke_user(guild_id, current_user.id)
    # …and tell this guild's apps that the credentials this person connected
    # under it are finished. After the commit, so an app is never told to let go
    # of something a rollback would have put back.
    await app_revocation_service.dispatch_revocations(
        app_revocation_service.drain_revocations(session)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
