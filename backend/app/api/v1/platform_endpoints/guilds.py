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
from sqlalchemy import text

from app.api.deps import (
    SessionDep,
    UploadUserDep,
    UserSessionDep,
    get_current_active_user,
)
from app.core.auth_context import satisfied_provider_ids
from app.core.capabilities import Capability, user_has_capability
from app.core.config import settings
from app.core.messages import BillingMessages, GuildMessages
from app.core.rate_limit import limiter
from app.core.security import (
    HandoffSigningNotConfiguredError,
    create_billing_portal_handoff_token,
    verify_password,
)
from app.db.schema_provisioning import deprovision_guild
from app.db.session import get_admin_session, set_rls_context
from app.models.platform.guild import (
    Guild,
    GuildCategory,
    GuildMembership,
    GuildRole,
    GuildStatus,
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
    GuildEntitlementsRead,
    GuildAuthPolicyRead,
    GuildAuthPolicyUpdate,
    GuildCreate,
    GuildDeletionRequest,
    GuildMembershipUpdate,
    GuildRead,
    GuildInviteAcceptRequest,
    GuildInviteCreate,
    GuildInviteRead,
    GuildInviteStatus,
    GuildOrderUpdate,
    GuildUpdate,
    LeaveGuildEligibilityResponse,
)
from app.core.config import AuthScope
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.guild_auth_policy import GuildAuthPolicy
from app.services.auth.identity import has_federated_identity
from app.services.auth.platform_provider import is_login_ready
from app.services.platform import guild_images as images_service
from app.services.tenant.attachments import FileTooLargeError, read_upload_bounded
from app.services.platform import guilds as guilds_service
from app.services.realtime import manager as realtime_manager
from app.services.tenant import app_connections as app_connections_service
from app.services.tenant import app_revocation as app_revocation_service
from app.services import rls as rls_service
from app.services.stream_authz import authority as stream_authority
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]

router = APIRouter()
logger = logging.getLogger(__name__)


def _serialize_guild(
    guild: Guild,
    membership: GuildMembership,
    retention_days: int | None = None,
    member_count: int = 0,
    administration: GuildAdministration | None = None,
    images: dict[GuildImageVariant, str] | None = None,
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
      guild settings section is admin-gated, as is ``/g/{id}/storage/usage``,
      the panel's other half), so a regular member's payload leaves them
      ``None``.

    Most of the second group now arrives as ``administration`` — a separate row
    the caller may read but no request path may write. Callers serving a member
    pass ``None`` for it and never read the row at all.
    """
    is_admin = membership.role == GuildRole.admin
    # Role decides, not the caller: passing the row for a member still serves a
    # member's payload, so this stays the one place the split is made.
    admin_row = administration if is_admin else None
    return GuildRead(
        id=guild.id,
        name=guild.name,
        description=guild.description,
        created_at=guild.created_at,
        updated_at=guild.updated_at,
        role=membership.role,
        position=membership.position,
        # Trash retention window — set from the admin-only trash settings tab.
        retention_days=retention_days if is_admin else None,
        member_count=member_count,
        # Operator-set caps, shown against usage on the admin settings page.
        max_storage_bytes=admin_row.max_storage_bytes if admin_row else None,
        max_users=admin_row.max_users if admin_row else None,
        # Display-only plan label (never an enforcement input); the SPA shows
        # it only when a billing portal is configured.
        tier_name=admin_row.tier_name if admin_row else None,
        # Only guild admins learn the lifecycle status (for the settings-page
        # chip); members get None so a moderation hold isn't disclosed to them.
        status=GuildStatus(guild.status) if is_admin else None,
        # Every member learns the *effect* of a read_only hold (their writes
        # already fail at the DB role level) so the UI can drop write
        # affordances — without disclosing the status itself.
        content_read_only=(guild.status == GuildStatus.read_only.value),
        # Admins only: lets their settings UI show/hide the Authentication tab.
        guild_auth_enabled=admin_row.guild_auth_enabled if admin_row else None,
        # Guild identity, not administration: the directory publishes both to
        # strangers, so withholding them from the guild's own members would
        # only mean the settings page could not render its own state.
        is_community=guild.is_community,
        categories=[GuildCategory(value) for value in guild.categories],
        has_adult_content=guild.has_adult_content,
        # Where the guild's pictures are, not the pictures. Callers that have
        # no reason to have looked them up pass nothing, which reads the same
        # as a guild without any. The banner colour is a column, so it needs no
        # such arrangement.
        icon_url=(images or {}).get(GuildImageVariant.icon),
        banner_url=(images or {}).get(GuildImageVariant.full),
        banner_color=guild.banner_color,
    )


async def _ensure_guild_admin(
    session: SessionDep,
    *,
    guild_id: int,
    user_id: int,
) -> GuildMembership:
    # Set minimal RLS context so the guild_memberships query succeeds (own-row
    # read). No standing bypass: these endpoints are for a guild's *own* admins —
    # a platform ``data.bypass`` holder who isn't a member is denied here and
    # manages other guilds via the dedicated ``/admin/*`` (capability-gated)
    # routes instead. Full context is set by _set_guild_admin_rls after validation.
    await set_rls_context(session, user_id=user_id)
    membership = await rls_service.require_guild_membership(
        session,
        guild_id=guild_id,
        user_id=user_id,
    )
    rls_service.require_guild_admin(membership.role)
    return membership


async def _set_guild_admin_rls(
    session: AsyncSession,
    *,
    guild_id: int,
    user: User,
) -> None:
    """Set RLS context after _ensure_guild_admin has validated the user's role.

    The validated guild admin acts through the guild's own role
    (``guild_<id>`` + ``current_guild_role='admin'``), not a standing all-guild
    bypass — full authority within this one guild, scoped to it."""
    await set_rls_context(
        session,
        user_id=user.id,
        guild_id=guild_id,
        guild_role="admin",
    )


@router.get("/", response_model=List[GuildRead])
async def list_guilds(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> List[GuildRead]:
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
    payloads: List[GuildRead] = []
    for guild, membership, retention_days, member_count, administration in memberships:
        payloads.append(
            _serialize_guild(
                guild,
                membership,
                retention_days=retention_days,
                member_count=member_count,
                administration=administration,
                images=images.get(guild.id),
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


@router.get("/communities", response_model=CommunityGuildPage)
async def list_community_guilds(
    session: AdminSessionDep,
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
    online = realtime_manager.present_counts(guild.id for guild, _, _ in rows)
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
                banner_card_url=images.get(guild.id, {}).get(GuildImageVariant.card),
                banner_color=guild.banner_color,
                categories=[GuildCategory(value) for value in guild.categories],
                member_count=member_count,
                online_count=online.get(guild.id, 0),
                already_member=already_member,
            )
            for guild, member_count, already_member in rows
        ],
        total=total,
    )


@router.post("/communities/{guild_id}/join", response_model=GuildRead)
async def join_community_guild(
    guild_id: int,
    session: AdminSessionDep,
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
    except guilds_service.GuildCapacityError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    await session.commit()
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
        membership,
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
    session: AdminSessionDep,
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
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildRead:
    """Create a new guild. Uses admin session because the guild doesn't exist
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

    # The guild's shared rows (guild + admin membership) live in public. Commit
    # them first so provisioning + the in-schema seed below run as a distinct,
    # compensatable step (on failure: deprovision + delete these committed rows).
    guild = await guilds_service.create_guild(
        session,
        name=name,
        description=guild_in.description,
        creator=current_user,
        owner=owner,
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
        await session.commit()
    except Exception:
        logger.exception("Guild %s setup failed; rolling back", guild.id)
        # Roll back first: discards the failed seed's partial writes AND reverts
        # the SET ROLE guild_<id> (Postgres SET is transactional) so deprovision
        # can DROP the role. The admin session is then back to app_admin
        # (BYPASSRLS), so removing the shared rows isn't filtered by RLS.
        await session.rollback()
        with suppress(Exception):
            await deprovision_guild(guild.id)  # drops the schema + any partial content
        stale = await guilds_service.get_guild(session, guild_id=guild.id)
        if stale:
            await guilds_service.delete_guild(session, stale)
            await session.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=GuildMessages.GUILD_PROVISION_FAILED,
        )
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
        membership,
        member_count=member_count,
        administration=administration,
    )


@router.get("/{guild_id}/invites", response_model=List[GuildInviteRead])
async def list_guild_invites(
    guild_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> List[GuildInviteRead]:
    await _ensure_guild_admin(
        session,
        guild_id=guild_id,
        user_id=current_user.id,
    )
    await _set_guild_admin_rls(session, guild_id=guild_id, user=current_user)
    invites = await guilds_service.list_guild_invites(session, guild_id=guild_id)
    return [GuildInviteRead.model_validate(invite) for invite in invites]


@router.patch("/{guild_id}", response_model=GuildRead)
async def update_guild(
    guild_id: int,
    updates: GuildUpdate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildRead:
    membership = await _ensure_guild_admin(
        session,
        guild_id=guild_id,
        user_id=current_user.id,
    )
    await _set_guild_admin_rls(session, guild_id=guild_id, user=current_user)
    retention_days_provided = "retention_days" in updates.model_fields_set
    categories_provided = "categories" in updates.model_fields_set
    has_adult_content_provided = "has_adult_content" in updates.model_fields_set
    banner_color_provided = "banner_color" in updates.model_fields_set
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
            banner_color=updates.banner_color,
            banner_color_provided=banner_color_provided,
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
    await session.commit()
    retention_days = await guilds_service.get_guild_retention_days(session, guild_id)
    member_count = await guilds_service.count_members(session, guild_id=guild_id)
    # Only a guild admin reaches this endpoint, so the caps belong in the reply.
    administration = await guilds_service.get_administration(session, guild_id=guild_id)
    return _serialize_guild(
        guild,
        membership,
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
# the platform router rather than under ``/g/{id}/…``, and why they run on the
# system engine — see ``guild_images.may_read_image`` for the rule and the
# reasoning.


@router.get("/{guild_id}/entitlements", response_model=GuildEntitlementsRead)
async def read_guild_entitlements(
    guild_id: int,
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildEntitlementsRead:
    """What an operator has turned on for this guild, for its own admins.

    Its own read rather than fields on the guild payload: these are decisions
    made *about* a guild rather than by it, they live on the separate
    ``guild_administration`` row, and a member has no use for them. A guild
    admin does — it is how their settings page knows to offer the banner
    colour alone rather than an upload that would come back refused.
    """
    await _ensure_guild_admin(session, guild_id=guild_id, user_id=current_user.id)
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
    session: AdminSessionDep,
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
    user: User,
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
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
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

    await images_service.set_images(
        session, guild_id=guild_id, user_id=user.id, renditions=renditions
    )


@router.put("/{guild_id}/icon", response_model=GuildRead)
async def set_guild_icon(
    guild_id: int,
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    icon: UploadFile = File(...),
) -> GuildRead:
    """Replace the guild's icon. One square picture, resized by the client."""
    membership = await _ensure_guild_admin(
        session, guild_id=guild_id, user_id=current_user.id
    )
    await _store_guild_images(
        session,
        guild_id=guild_id,
        user=current_user,
        uploads=[(GuildImageVariant.icon, icon)],
    )
    await session.commit()
    return await _guild_payload_after_image_change(
        session, guild_id=guild_id, user=current_user, membership=membership
    )


@router.delete("/{guild_id}/icon", response_model=GuildRead)
async def clear_guild_icon(
    guild_id: int,
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildRead:
    """Remove the guild's icon. It falls back to its lettered avatar."""
    membership = await _ensure_guild_admin(
        session, guild_id=guild_id, user_id=current_user.id
    )
    await images_service.clear_images(
        session, guild_id=guild_id, variants=[GuildImageVariant.icon]
    )
    await session.commit()
    return await _guild_payload_after_image_change(
        session, guild_id=guild_id, user=current_user, membership=membership
    )


@router.put("/{guild_id}/banner", response_model=GuildRead)
async def set_guild_banner(
    guild_id: int,
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    full: UploadFile = File(...),
    card: UploadFile = File(...),
) -> GuildRead:
    """Replace the guild's banner with the two renditions of one picture.

    The admin chooses a single image; the settings page resizes it to both
    renditions and sends them together, so a guild is never left showing a new
    card over an old front page.
    """
    membership = await _ensure_guild_admin(
        session, guild_id=guild_id, user_id=current_user.id
    )
    administration = await guilds_service.get_administration(session, guild_id=guild_id)
    if administration is not None and not administration.banner_image_enabled:
        # Only uploading is gated. The banner surface stays, a banner the guild
        # already has keeps being served, and what a guild without artwork sets
        # instead is the colour on ``guilds.banner_color``, through PATCH.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.BANNER_IMAGE_NOT_ENTITLED,
        )
    await _store_guild_images(
        session,
        guild_id=guild_id,
        user=current_user,
        uploads=list(zip(BANNER_VARIANTS, (full, card))),
    )
    await session.commit()
    return await _guild_payload_after_image_change(
        session, guild_id=guild_id, user=current_user, membership=membership
    )


@router.delete("/{guild_id}/banner", response_model=GuildRead)
async def clear_guild_banner(
    guild_id: int,
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildRead:
    """Remove the guild's banner. Both surfaces fall back to their plain form."""
    membership = await _ensure_guild_admin(
        session, guild_id=guild_id, user_id=current_user.id
    )
    await images_service.clear_images(
        session, guild_id=guild_id, variants=list(BANNER_VARIANTS)
    )
    await session.commit()
    return await _guild_payload_after_image_change(
        session, guild_id=guild_id, user=current_user, membership=membership
    )


async def _guild_payload_after_image_change(
    session: AsyncSession,
    *,
    guild_id: int,
    user: User,
    membership: GuildMembership,
) -> GuildRead:
    """The guild as its admin now sees it, so the SPA needs no follow-up read.

    Routed into the guild first, and only once the write above has committed.
    A ``GuildRead`` is not all public-schema: the trash retention window lives
    in the guild's own schema, which an unrouted session cannot see at all.
    ``SET ROLE`` drops the system engine's bypass, which is why this runs after
    the commit rather than around it — and everything read below is then read
    as the guild admin the caller actually is.
    """
    await set_rls_context(
        session, user_id=user.id, guild_id=guild_id, guild_role="admin"
    )
    guild = await guilds_service.get_guild(session, guild_id=guild_id)
    if guild is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=GuildMessages.GUILD_NOT_FOUND
        )
    return _serialize_guild(
        guild,
        membership,
        retention_days=await guilds_service.get_guild_retention_days(session, guild_id),
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
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> BillingPortalHandoffResponse:
    """Mint a billing-portal handoff for a guild admin. Guild admin only."""
    if not settings.BILLING_URL:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=BillingMessages.PORTAL_NOT_CONFIGURED,
        )

    await _ensure_guild_admin(
        session,
        guild_id=guild_id,
        user_id=current_user.id,
    )

    try:
        token, expires_in_seconds = create_billing_portal_handoff_token(
            user_id=current_user.id,
            guild_id=guild_id,
            guild_role=GuildRole.admin.value,
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


def _require_guild_auth_scope() -> None:
    """The guild sign-in configuration surface exists only when the instance's
    deploy-time posture is per-guild login; under platform posture it is absent
    (404), the same way dormant login providers behave. Enforcement of an
    existing policy row is deliberately not posture-gated — only its management
    is."""
    if settings.AUTH_SCOPE != AuthScope.guild:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildMessages.GUILD_AUTH_NOT_ENABLED,
        )


async def _require_guild_auth_enabled(
    admin_session: AsyncSession, guild_id: int
) -> None:
    """The per-guild sign-in *configuration* surface exists only when an
    operator has enabled guild auth for this guild (the Guilds-dashboard
    toggle); absent (404) otherwise — the same shape as the posture gate above.
    Like that gate, this bounds *management* only: turning the toggle back off
    never deletes providers, keeps existing members signing in through them, and
    leaves any existing sign-in requirement enforced (see the Guild model)."""
    administration = (
        await admin_session.exec(
            select(GuildAdministration).where(GuildAdministration.guild_id == guild_id)
        )
    ).one_or_none()
    if administration is None or not administration.guild_auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildMessages.GUILD_AUTH_NOT_ENABLED,
        )


def _auth_policy_read(
    policy_row, provider_display_name: str | None = None
) -> GuildAuthPolicyRead:
    if policy_row is None or policy_row.policy == "open":
        return GuildAuthPolicyRead(policy="open")
    return GuildAuthPolicyRead(
        policy="required",
        provider_id=policy_row.provider_id,
        provider_slug=policy_row.provider_slug,
        provider_display_name=provider_display_name,
    )


@router.get("/{guild_id}/auth-policy", response_model=GuildAuthPolicyRead)
async def get_guild_auth_policy(
    guild_id: int,
    session: SessionDep,
    admin_session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildAuthPolicyRead:
    """The guild's sign-in requirement. Guild admin only (the settings UI);
    a blocked session learns the required provider from the step-up 401's
    header, not from here. Absent (404) unless the platform posture is
    per-guild login."""
    _require_guild_auth_scope()
    await _require_guild_auth_enabled(admin_session, guild_id)
    await _ensure_guild_admin(session, guild_id=guild_id, user_id=current_user.id)
    policy_row = await admin_session.get(GuildAuthPolicy, guild_id)
    display_name = None
    if policy_row is not None and policy_row.provider_id is not None:
        provider = await admin_session.get(AuthProvider, policy_row.provider_id)
        display_name = provider.display_name if provider else None
    return _auth_policy_read(policy_row, display_name)


@router.put("/{guild_id}/auth-policy", response_model=GuildAuthPolicyRead)
async def set_guild_auth_policy(
    guild_id: int,
    payload: GuildAuthPolicyUpdate,
    session: SessionDep,
    admin_session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildAuthPolicyRead:
    """Set the guild's sign-in requirement. Guild admin only.

    ``open`` deletes the stored row (no row IS open). ``required`` names one
    of the guild's own login-ready providers — and the calling admin's own
    session must already satisfy it, which both proves the provider works
    end-to-end and keeps an admin from locking their guild (and themselves)
    behind a sign-in they haven't completed. Absent (404) unless the platform
    posture is per-guild login."""
    _require_guild_auth_scope()
    await _require_guild_auth_enabled(admin_session, guild_id)
    await _ensure_guild_admin(session, guild_id=guild_id, user_id=current_user.id)

    if payload.policy == "open":
        policy_row = await admin_session.get(GuildAuthPolicy, guild_id)
        if policy_row is not None:
            await admin_session.delete(policy_row)
            await admin_session.commit()
        return GuildAuthPolicyRead(policy="open")

    if payload.provider_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.GUILD_AUTH_POLICY_INVALID_PROVIDER,
        )
    provider = await admin_session.get(AuthProvider, payload.provider_id)
    if (
        provider is None
        or provider.guild_id != guild_id
        or not is_login_ready(provider)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.GUILD_AUTH_POLICY_INVALID_PROVIDER,
        )
    if provider.id not in satisfied_provider_ids():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.GUILD_AUTH_POLICY_SELF_UNSATISFIED,
        )

    policy_row = await admin_session.get(GuildAuthPolicy, guild_id)
    if policy_row is None:
        policy_row = GuildAuthPolicy(
            guild_id=guild_id,
            policy="required",
            provider_id=provider.id,
            provider_slug=provider.slug,
        )
    else:
        policy_row.policy = "required"
        policy_row.provider_id = provider.id
        policy_row.provider_slug = provider.slug
    admin_session.add(policy_row)
    await admin_session.commit()
    return _auth_policy_read(policy_row, provider.display_name)


@router.delete(
    "/{guild_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
async def delete_guild(
    guild_id: int,
    request: GuildDeletionRequest,
    session: SessionDep,
    admin_session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    await _ensure_guild_admin(
        session,
        guild_id=guild_id,
        user_id=current_user.id,
    )
    await _set_guild_admin_rls(session, guild_id=guild_id, user=current_user)
    guild = await guilds_service.get_guild(session, guild_id=guild_id)

    # Password gate — skipped for SSO-only users (provisioned with a
    # random hash they were never shown), same rationale as the
    # account-deletion endpoint. 400 not 401 so the SPA's axios
    # interceptor doesn't treat a wrong password as a session expiry and
    # force-log-out the user mid-confirmation.
    if not await has_federated_identity(admin_session, user_id=current_user.id):
        if not verify_password(request.password, current_user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=GuildMessages.INVALID_PASSWORD,
            )

    # The whole phrase is uppercased, including the name, so casing on
    # the guild name can't trip up the confirmation.
    expected = f"DELETE GUILD {guild.name.upper()}"
    if request.confirmation_text != expected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.CONFIRMATION_MISMATCH,
        )

    # End the guild's app access while the schema is still there to read. The
    # DROP below would take the rows with it silently, which would leave vendor
    # grants outliving the guild that authorized them — so each app is told to
    # let go first, and the intents are delivered once the deletion commits.
    await app_connections_service.delete_guild_connections(session)

    # Delete the guild ROW first — reliable, and the guild is immediately gone from
    # the app's point of view. Its ON DELETE CASCADE FKs clear the shared roster
    # (memberships, invites, OIDC mappings, access grants). The guild-scoped data
    # lives in the schema, which holds no FKs back to public.guilds, so the
    # row delete isn't blocked by it. Runs as the assumed guild role, so the
    # public.guilds guild_delete RLS policy (current_guild_id) matches.
    await guilds_service.delete_guild(session, guild)
    await session.commit()
    await app_revocation_service.dispatch_revocations(
        app_revocation_service.drain_revocations(session)
    )

    # Drop the schema + role as best-effort cleanup. Reset the assumed guild role
    # first (committed) so DROP ROLE can run. With the cross-schema FKs gone,
    # DROP SCHEMA only locks this guild's tables — no contention with the app's
    # reads of public.guilds/users. A failed cleanup must NEVER undo the committed
    # deletion: an orphaned, empty schema is harmless and reclaimed on a retry or
    # the next provision of that id.
    await session.exec(text("SELECT set_config('role', 'none', false)"))
    await session.commit()
    try:
        await deprovision_guild(guild_id)
    except Exception:
        logger.exception(
            "Schema/role cleanup for deleted guild %s failed (orphan is harmless)",
            guild_id,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{guild_id}/invites",
    response_model=GuildInviteRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_guild_invite(
    guild_id: int,
    invite_in: GuildInviteCreate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildInviteRead:
    await _ensure_guild_admin(
        session,
        guild_id=guild_id,
        user_id=current_user.id,
    )
    await _set_guild_admin_rls(session, guild_id=guild_id, user=current_user)
    try:
        invite = await guilds_service.create_guild_invite(
            session,
            guild_id=guild_id,
            created_by=current_user.id,
            expires_at=invite_in.expires_at,
            max_uses=invite_in.max_uses,
            invitee_email=invite_in.invitee_email,
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
    invite_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    await _ensure_guild_admin(
        session,
        guild_id=guild_id,
        user_id=current_user.id,
    )
    await _set_guild_admin_rls(session, guild_id=guild_id, user=current_user)
    await guilds_service.delete_guild_invite(
        session, guild_id=guild_id, invite_id=invite_id
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/invite/accept", response_model=GuildRead)
async def accept_invite(
    payload: GuildInviteAcceptRequest,
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildRead:
    """Accept a guild invite. Uses admin session because the user doesn't
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
    await session.commit()
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
        membership,
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
    user_id: int,
    payload: GuildMembershipUpdate,
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    """Update a user's guild membership role. Guild admin only.

    Restrictions:
    - Cannot change your own role
    - Cannot demote the last guild admin
    """
    # Runs on the system engine (AdminSessionDep): the guild role holds no UPDATE
    # on guild_memberships, so a role change happens only here, after the
    # guild-admin check — never under a request-path role. See migration 0145.
    await _ensure_guild_admin(
        session,
        guild_id=guild_id,
        user_id=current_user.id,
    )

    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.CANNOT_CHANGE_OWN_ROLE,
        )

    # 'support' is a synthesized PAM identity, never a stored membership role
    # (the guild_role enum has only admin/member) — reject before it hits the DB.
    if payload.role == GuildRole.support:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.GUILD_ROLE_NOT_ASSIGNABLE,
        )

    target_membership = await guilds_service.get_membership(
        session, guild_id=guild_id, user_id=user_id, for_update=True
    )
    if target_membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildMessages.USER_NOT_FOUND_IN_GUILD,
        )

    # Check if demoting the last guild admin (FOR UPDATE already acquired above)
    if target_membership.role == GuildRole.admin and payload.role != GuildRole.admin:
        from app.services.platform.users import is_last_admin_of_guild

        if await is_last_admin_of_guild(session, guild_id, user_id, for_update=True):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=GuildMessages.CANNOT_DEMOTE_LAST_ADMIN,
            )

    target_membership.role = payload.role
    session.add(target_membership)
    await session.commit()
    # Guild-level access change (e.g. admin → member loses the guild-admin
    # bypass): re-check this user's live content streams now so the change takes
    # effect immediately, not on the next bounded re-auth tick.
    await stream_authority.revoke_user(guild_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{guild_id}/leave/eligibility", response_model=LeaveGuildEligibilityResponse
)
async def check_leave_eligibility(
    guild_id: int,
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> LeaveGuildEligibilityResponse:
    """Check if the current user can leave a guild.

    Being the guild's last admin is the only thing that stops them. Content they
    own is released on the way out and left unowned for a guild admin to claim,
    so there is nothing to hand over first.
    """
    membership = await guilds_service.get_membership(
        session, guild_id=guild_id, user_id=current_user.id
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=GuildMessages.NOT_GUILD_MEMBER
        )

    from app.services.platform.users import is_last_admin_of_guild

    is_last_admin = await is_last_admin_of_guild(session, guild_id, current_user.id)

    return LeaveGuildEligibilityResponse(
        can_leave=not is_last_admin,
        is_last_admin=is_last_admin,
    )


@router.delete(
    "/{guild_id}/leave", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
async def leave_guild(
    guild_id: int,
    session: UserSessionDep,
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
    # context so those writes aren't filtered to zero rows.
    await set_rls_context(
        session,
        user_id=current_user.id,
        guild_id=guild_id,
        guild_role=membership.role.value,
    )

    from app.services.platform.users import is_last_admin_of_guild

    if await is_last_admin_of_guild(
        session, guild_id, current_user.id, for_update=True
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.CANNOT_LEAVE_LAST_ADMIN,
        )

    # Ownership release happens inside remove_user_from_guild, while the
    # leaver's membership rows are still in place for RLS to match.
    await guilds_service.remove_user_from_guild(
        session, guild_id=guild_id, user_id=current_user.id
    )

    await session.commit()
    # Left the guild — drop this user's live content streams immediately.
    await stream_authority.revoke_user(guild_id, current_user.id)
    # …and tell this guild's apps that the credentials this person connected
    # under it are finished. After the commit, so an app is never told to let go
    # of something a rollback would have put back.
    await app_revocation_service.dispatch_revocations(
        app_revocation_service.drain_revocations(session)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
