import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    SessionDep,
    UserSessionDep,
    GuildContext,
    require_guild_roles,
)
from app.api.v1.platform_endpoints.admin import ConfigManageDep, GuildsManageDep
from app.core.config import settings as app_config
from app.core.rate_limit import limiter
from app.db.session import get_admin_session, set_rls_context
from app.models.platform.app_setting import AppSetting
from app.models.platform.guild import Guild, GuildMembership, GuildRole
from app.models.tenant.initiative import Initiative, InitiativeRoleModel
from app.models.platform.oidc_claim_mapping import (
    OIDCClaimMapping,
    OIDCMappingTargetType,
)
from app.schemas.platform.settings import (
    EmailSettingsResponse,
    EmailSettingsUpdate,
    EmailTestRequest,
    InterfaceSettingsResponse,
    InterfaceSettingsUpdate,
    OIDCClaimMappingCreate,
    OIDCClaimMappingRead,
    OIDCClaimMappingUpdate,
    OIDCClaimPathUpdate,
    OIDCMappingsResponse,
    OIDCSettingsResponse,
    OIDCSettingsUpdate,
)
from app.schemas.platform.guild import (
    PlatformGuildStorageRead,
    PlatformGuildStorageUpdate,
)
from app.schemas.platform.push import FCMConfigResponse
from app.core.messages import GuildMessages, SettingsMessages
from app.services.platform import app_settings as app_settings_service
from app.services.platform import guilds as guilds_service
from app.services import email as email_service

logger = logging.getLogger(__name__)

AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]

router = APIRouter()

GuildAdminContext = Annotated[
    GuildContext, Depends(require_guild_roles(GuildRole.admin))
]


def _backend_redirect_uri() -> str:
    return f"{app_config.APP_URL.rstrip('/')}{app_config.API_V1_STR}/auth/oidc/callback"


def _frontend_redirect_uri() -> str:
    return f"{app_config.APP_URL.rstrip('/')}/oidc/callback"


def _mobile_redirect_uri() -> str:
    return "initiative://oidc/callback"


def _email_settings_payload(settings_obj: AppSetting) -> EmailSettingsResponse:
    return EmailSettingsResponse(
        host=settings_obj.smtp_host,
        port=settings_obj.smtp_port,
        secure=settings_obj.smtp_secure,
        reject_unauthorized=settings_obj.smtp_reject_unauthorized,
        username=settings_obj.smtp_username,
        has_password=bool(settings_obj.smtp_password_encrypted),
        from_address=settings_obj.smtp_from_address,
        test_recipient=settings_obj.smtp_test_recipient,
    )


@router.get("/auth", response_model=OIDCSettingsResponse)
async def get_oidc_settings(
    session: UserSessionDep,
    _admin: ConfigManageDep,
) -> OIDCSettingsResponse:
    settings_obj = await app_settings_service.get_app_settings(session)
    return OIDCSettingsResponse(
        enabled=settings_obj.oidc_enabled,
        issuer=settings_obj.oidc_issuer,
        client_id=settings_obj.oidc_client_id,
        redirect_uri=_backend_redirect_uri(),
        post_login_redirect=_frontend_redirect_uri(),
        mobile_redirect_uri=_mobile_redirect_uri(),
        provider_name=settings_obj.oidc_provider_name,
        scopes=settings_obj.oidc_scopes,
    )


@router.put("/auth", response_model=OIDCSettingsResponse)
async def update_oidc_settings(
    payload: OIDCSettingsUpdate,
    session: UserSessionDep,
    _admin: ConfigManageDep,
) -> OIDCSettingsResponse:
    updated = await app_settings_service.update_oidc_settings(
        session,
        enabled=payload.enabled,
        issuer=payload.issuer,
        client_id=payload.client_id,
        client_secret=payload.client_secret,
        provider_name=payload.provider_name,
        scopes=payload.scopes,
    )
    return OIDCSettingsResponse(
        enabled=updated.oidc_enabled,
        issuer=updated.oidc_issuer,
        client_id=updated.oidc_client_id,
        redirect_uri=_backend_redirect_uri(),
        post_login_redirect=_frontend_redirect_uri(),
        mobile_redirect_uri=_mobile_redirect_uri(),
        provider_name=updated.oidc_provider_name,
        scopes=updated.oidc_scopes,
    )


@router.get("/interface", response_model=InterfaceSettingsResponse)
async def get_interface_settings(
    session: SessionDep,
) -> InterfaceSettingsResponse:
    settings_obj = await app_settings_service.get_app_settings(session)
    return InterfaceSettingsResponse(
        light_accent_color=settings_obj.light_accent_color,
        dark_accent_color=settings_obj.dark_accent_color,
    )


@router.put("/interface", response_model=InterfaceSettingsResponse)
async def update_interface_settings(
    payload: InterfaceSettingsUpdate,
    session: UserSessionDep,
    _admin: ConfigManageDep,
) -> InterfaceSettingsResponse:
    settings_obj = await app_settings_service.update_interface_colors(
        session,
        light_accent_color=payload.light_accent_color,
        dark_accent_color=payload.dark_accent_color,
    )
    return InterfaceSettingsResponse(
        light_accent_color=settings_obj.light_accent_color,
        dark_accent_color=settings_obj.dark_accent_color,
    )


@router.get("/email", response_model=EmailSettingsResponse)
async def get_email_settings(
    session: UserSessionDep,
    _admin: ConfigManageDep,
) -> EmailSettingsResponse:
    settings_obj = await app_settings_service.get_app_settings(session)
    return _email_settings_payload(settings_obj)


@router.put("/email", response_model=EmailSettingsResponse)
async def update_email_settings(
    payload: EmailSettingsUpdate,
    session: UserSessionDep,
    _admin: ConfigManageDep,
) -> EmailSettingsResponse:
    data = payload.model_dump(exclude_unset=True)
    password_provided = "password" in data
    updated = await app_settings_service.update_email_settings(
        session,
        host=payload.host,
        port=payload.port,
        secure=payload.secure,
        reject_unauthorized=payload.reject_unauthorized,
        username=payload.username,
        password=payload.password,
        password_provided=password_provided,
        from_address=payload.from_address,
        test_recipient=payload.test_recipient,
    )
    return _email_settings_payload(updated)


@router.post("/email/test")
async def send_test_email(
    payload: EmailTestRequest,
    session: UserSessionDep,
    _admin: ConfigManageDep,
) -> dict:
    settings_obj = await app_settings_service.get_app_settings(session)
    recipient = payload.recipient or settings_obj.smtp_test_recipient
    if not recipient:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=SettingsMessages.PROVIDE_TEST_EMAIL,
        )
    try:
        await email_service.send_test_email(session, recipient)
    except email_service.EmailNotConfiguredError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=SettingsMessages.SMTP_INCOMPLETE,
        ) from None
    except RuntimeError as exc:
        # Log the real cause (may include SMTP host/port/server banner) for the
        # operator, but return only a generic machine-readable code so the
        # response never leaks internal mail-server details (pentest SEC-16).
        logger.warning("Test email delivery failed: %s", str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=SettingsMessages.EMAIL_SEND_FAILED,
        ) from exc
    return {"status": "sent"}


@router.get("/fcm-config", response_model=FCMConfigResponse)
@limiter.limit("20/minute")
async def get_fcm_config(request: Request) -> FCMConfigResponse:
    """Get public FCM configuration for mobile app initialization.

    This endpoint is public (no authentication required) and only exposes
    public fields needed by the mobile app to initialize Firebase.
    Service account credentials are NOT exposed.

    Rate limited to 20 requests per minute to prevent abuse.
    """
    return FCMConfigResponse(
        enabled=app_config.FCM_ENABLED,
        project_id=app_config.FCM_PROJECT_ID if app_config.FCM_ENABLED else None,
        application_id=app_config.FCM_APPLICATION_ID
        if app_config.FCM_ENABLED
        else None,
        api_key=app_config.FCM_API_KEY if app_config.FCM_ENABLED else None,
        sender_id=app_config.FCM_SENDER_ID if app_config.FCM_ENABLED else None,
    )


# --- Guild storage limits (Admin dashboard → Guilds tab) ---


@router.get("/guilds", response_model=list[PlatformGuildStorageRead])
async def list_platform_guild_storage(
    session: AdminSessionDep,
    _admin: GuildsManageDep,
) -> list[PlatformGuildStorageRead]:
    """List every guild with its storage cap, for the Admin dashboard Guilds tab.

    Admin/owner (``guilds.manage``). Reads only shared ``public`` tables
    (``guilds``, ``guild_memberships``) — no guild-scoped content — so it runs on
    the system admin engine without routing into any guild schema. Member
    counts come from a single grouped query rather than per-guild (no N+1).
    """
    guilds = (await session.exec(select(Guild).order_by(Guild.name))).all()
    counts = dict(
        (
            await session.exec(
                select(GuildMembership.guild_id, func.count()).group_by(
                    GuildMembership.guild_id
                )
            )
        ).all()
    )
    return [
        PlatformGuildStorageRead(
            id=g.id,
            name=g.name,
            member_count=counts.get(g.id, 0),
            max_storage_bytes=g.max_storage_bytes,
            max_users=g.max_users,
        )
        for g in guilds
    ]


@router.patch("/guilds/{guild_id}", response_model=PlatformGuildStorageRead)
async def update_platform_guild_storage(
    guild_id: int,
    payload: PlatformGuildStorageUpdate,
    session: AdminSessionDep,
    _admin: GuildsManageDep,
) -> PlatformGuildStorageRead:
    """Set a guild's storage and/or member caps (``null`` = unlimited). Admin/owner.

    Writes only shared ``public.guilds`` columns (``max_storage_bytes`` /
    ``max_users``) — no guild-schema routing needed. ``model_fields_set`` tells an
    omitted field (leave untouched) from one sent as ``null`` (reset to
    unlimited), so a PATCH may carry either cap or both. Lowering a cap below the
    current usage/headcount simply blocks further uploads / new joins; it never
    removes existing blobs or members.
    """
    provided = payload.model_fields_set
    try:
        guild = await guilds_service.update_guild(
            session,
            guild_id=guild_id,
            max_storage_bytes=payload.max_storage_bytes,
            max_storage_bytes_provided="max_storage_bytes" in provided,
            max_users=payload.max_users,
            max_users_provided="max_users" in provided,
        )
    except ValueError as exc:
        # update_guild -> get_guild raises ValueError(GUILD_NOT_FOUND) when the row
        # is gone. Letting it own the existence check (rather than a separate
        # pre-SELECT) closes the TOCTOU window where a concurrent delete between
        # the two queries would otherwise surface as an unhandled 500.
        if str(exc) == GuildMessages.GUILD_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=SettingsMessages.GUILD_NOT_FOUND,
            ) from exc
        raise
    await session.commit()
    member_count = await guilds_service.count_members(session, guild_id=guild_id)
    return PlatformGuildStorageRead(
        id=guild.id,
        name=guild.name,
        member_count=member_count,
        max_storage_bytes=guild.max_storage_bytes,
        max_users=guild.max_users,
    )


# --- OIDC Claim Mapping endpoints ---


async def _route_admin_to_guild(session: AsyncSession, guild_id: int) -> None:
    """Route the admin session into a guild's ``guild_<id>`` schema.

    Initiatives and initiative roles are guild-scoped content: their rows live in
    each guild's schema, not in the empty ``public`` template copies. Reading them
    requires routing the session into that schema. ``expunge_all`` first because
    row ids are unique only within a schema — a cached object from a previously
    routed guild could otherwise be returned for a colliding id.
    """
    session.expunge_all()
    await set_rls_context(session, guild_id=guild_id)


async def _reset_admin_session(session: AsyncSession) -> None:
    """Return the admin session to its neutral public / login-role baseline.

    After routing into a guild schema the session has assumed that guild's role,
    which has no write access to shared ``public`` config tables. Reset to the
    admin login role (``SET ROLE none``, ``search_path public``) before
    writing the mapping back to ``public``.
    """
    await set_rls_context(session)


async def _lookup_guild_initiative(
    session: AsyncSession,
    guild_id: int,
    initiative_id: int,
    initiative_role_id: int | None,
) -> tuple[Initiative | None, InitiativeRoleModel | None]:
    """Look up an initiative (and optional role) inside a guild's schema.

    Routes the session into ``guild_<id>`` for the read, then resets it back to
    the neutral admin baseline so callers can write the mapping to the shared
    ``public.oidc_claim_mappings`` table as the admin login role (the
    guild role has no write grant on config tables). ``populate_existing`` keeps
    a colliding id from another guild already in the identity map from being
    returned stale — ids are unique only within a schema.
    """
    await set_rls_context(session, guild_id=guild_id)
    try:
        initiative = (
            await session.exec(
                select(Initiative)
                .where(Initiative.id == initiative_id)
                .execution_options(populate_existing=True)
            )
        ).one_or_none()
        role: InitiativeRoleModel | None = None
        if initiative_role_id is not None:
            role = (
                await session.exec(
                    select(InitiativeRoleModel)
                    .where(InitiativeRoleModel.id == initiative_role_id)
                    .execution_options(populate_existing=True)
                )
            ).one_or_none()
        return initiative, role
    finally:
        await _reset_admin_session(session)


async def _enrich_mapping(
    session: AsyncSession, mapping: OIDCClaimMapping
) -> OIDCClaimMappingRead:
    """Build a read schema with denormalized names."""
    guild_name = None
    initiative_name = None
    initiative_role_name = None

    guild = (
        await session.exec(select(Guild).where(Guild.id == mapping.guild_id))
    ).one_or_none()
    if guild:
        guild_name = guild.name

    if mapping.initiative_id is not None:
        # Initiatives/roles are guild-scoped: resolve their names inside the
        # mapping's guild schema, not the empty public copies.
        initiative, role = await _lookup_guild_initiative(
            session,
            mapping.guild_id,
            mapping.initiative_id,
            mapping.initiative_role_id,
        )
        if initiative:
            initiative_name = initiative.name
        if role:
            initiative_role_name = role.display_name

    return OIDCClaimMappingRead(
        id=mapping.id,
        claim_value=mapping.claim_value,
        target_type=mapping.target_type.value
        if isinstance(mapping.target_type, OIDCMappingTargetType)
        else mapping.target_type,
        guild_id=mapping.guild_id,
        guild_role=mapping.guild_role,
        initiative_id=mapping.initiative_id,
        initiative_role_id=mapping.initiative_role_id,
        guild_name=guild_name,
        initiative_name=initiative_name,
        initiative_role_name=initiative_role_name,
    )


@router.get("/oidc-mappings", response_model=OIDCMappingsResponse)
async def get_oidc_mappings(
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> OIDCMappingsResponse:
    settings_obj = await app_settings_service.get_app_settings(session)
    stmt = select(OIDCClaimMapping).order_by(OIDCClaimMapping.id)
    mappings = (await session.exec(stmt)).all()
    enriched = [await _enrich_mapping(session, m) for m in mappings]
    return OIDCMappingsResponse(
        claim_path=settings_obj.oidc_role_claim_path,
        mappings=enriched,
    )


@router.put("/oidc-mappings/claim-path")
async def update_oidc_claim_path(
    payload: OIDCClaimPathUpdate,
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> dict:
    # Residual admin-engine: kept with the rest of the oidc-mappings surface,
    # which is deferred to Phase 3 (guild-scoped / dual-path + break-glass).
    settings_obj = await app_settings_service.get_app_settings(session)
    cleaned = payload.claim_path.strip() if payload.claim_path else None
    settings_obj.oidc_role_claim_path = cleaned or None
    session.add(settings_obj)
    await session.commit()
    return {"claim_path": settings_obj.oidc_role_claim_path}


@router.post(
    "/oidc-mappings",
    response_model=OIDCClaimMappingRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_oidc_mapping(
    payload: OIDCClaimMappingCreate,
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> OIDCClaimMappingRead:
    # Validate target_type
    try:
        target_type = OIDCMappingTargetType(payload.target_type)
    except ValueError:
        raise HTTPException(
            status_code=400, detail=SettingsMessages.INVALID_TARGET_TYPE
        )

    # Validate guild_role
    if payload.guild_role not in ("admin", "member"):
        raise HTTPException(status_code=400, detail=SettingsMessages.INVALID_GUILD_ROLE)

    # Validate guild exists
    guild = (
        await session.exec(select(Guild).where(Guild.id == payload.guild_id))
    ).one_or_none()
    if not guild:
        raise HTTPException(status_code=400, detail=SettingsMessages.GUILD_NOT_FOUND)

    # Validate initiative fields if target_type is initiative
    if target_type == OIDCMappingTargetType.initiative:
        if not payload.initiative_id:
            raise HTTPException(
                status_code=400, detail=SettingsMessages.INITIATIVE_ID_REQUIRED
            )
        if not payload.initiative_role_id:
            raise HTTPException(
                status_code=400, detail=SettingsMessages.INITIATIVE_ROLE_ID_REQUIRED
            )
        initiative, role = await _lookup_guild_initiative(
            session,
            payload.guild_id,
            payload.initiative_id,
            payload.initiative_role_id,
        )
        if not initiative:
            raise HTTPException(
                status_code=400, detail=SettingsMessages.INITIATIVE_NOT_FOUND
            )
        # Defence-in-depth: the lookup already routed into guild_<payload.guild_id>,
        # so a found initiative's guild_id matches by construction. Retained to
        # catch a data-integrity anomaly (an initiative row whose stored guild_id
        # disagrees with its schema) rather than silently binding the mapping.
        if initiative.guild_id != payload.guild_id:
            raise HTTPException(
                status_code=400, detail=SettingsMessages.INITIATIVE_WRONG_GUILD
            )
        if not role:
            raise HTTPException(
                status_code=400, detail=SettingsMessages.INITIATIVE_ROLE_NOT_FOUND
            )

    mapping = OIDCClaimMapping(
        claim_value=payload.claim_value.strip(),
        target_type=target_type,
        guild_id=payload.guild_id,
        guild_role=payload.guild_role,
        initiative_id=payload.initiative_id
        if target_type == OIDCMappingTargetType.initiative
        else None,
        initiative_role_id=payload.initiative_role_id
        if target_type == OIDCMappingTargetType.initiative
        else None,
    )
    session.add(mapping)
    await session.commit()
    await session.refresh(mapping)
    return await _enrich_mapping(session, mapping)


@router.put("/oidc-mappings/{mapping_id}", response_model=OIDCClaimMappingRead)
async def update_oidc_mapping(
    mapping_id: int,
    payload: OIDCClaimMappingUpdate,
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> OIDCClaimMappingRead:
    mapping = (
        await session.exec(
            select(OIDCClaimMapping).where(OIDCClaimMapping.id == mapping_id)
        )
    ).one_or_none()
    if not mapping:
        raise HTTPException(status_code=404, detail=SettingsMessages.MAPPING_NOT_FOUND)

    data = payload.model_dump(exclude_unset=True)
    if "claim_value" in data and data["claim_value"] is not None:
        mapping.claim_value = data["claim_value"].strip()
    if "target_type" in data and data["target_type"] is not None:
        try:
            mapping.target_type = OIDCMappingTargetType(data["target_type"])
        except ValueError:
            raise HTTPException(
                status_code=400, detail=SettingsMessages.INVALID_TARGET_TYPE
            )
    if "guild_id" in data and data["guild_id"] is not None:
        guild = (
            await session.exec(select(Guild).where(Guild.id == data["guild_id"]))
        ).one_or_none()
        if not guild:
            raise HTTPException(
                status_code=400, detail=SettingsMessages.GUILD_NOT_FOUND
            )
        mapping.guild_id = data["guild_id"]
    if "guild_role" in data and data["guild_role"] is not None:
        if data["guild_role"] not in ("admin", "member"):
            raise HTTPException(
                status_code=400, detail=SettingsMessages.INVALID_GUILD_ROLE
            )
        mapping.guild_role = data["guild_role"]
    if "initiative_id" in data:
        mapping.initiative_id = data["initiative_id"]
    if "initiative_role_id" in data:
        mapping.initiative_role_id = data["initiative_role_id"]

    # Full validation of the final state
    effective_target = mapping.target_type
    if isinstance(effective_target, str):
        effective_target = OIDCMappingTargetType(effective_target)
    if effective_target == OIDCMappingTargetType.initiative:
        if not mapping.initiative_id or not mapping.initiative_role_id:
            raise HTTPException(
                status_code=400, detail=SettingsMessages.INITIATIVE_FIELDS_REQUIRED
            )
        initiative, role = await _lookup_guild_initiative(
            session,
            mapping.guild_id,
            mapping.initiative_id,
            mapping.initiative_role_id,
        )
        if not initiative:
            raise HTTPException(
                status_code=400, detail=SettingsMessages.INITIATIVE_NOT_FOUND
            )
        # Defence-in-depth: structurally guaranteed now (the lookup routes into
        # guild_<mapping.guild_id>), kept to catch a stored guild_id that disagrees
        # with its schema rather than binding the mapping to a mismatched guild.
        if initiative.guild_id != mapping.guild_id:
            raise HTTPException(
                status_code=400, detail=SettingsMessages.INITIATIVE_WRONG_GUILD
            )
        if not role:
            raise HTTPException(
                status_code=400, detail=SettingsMessages.INITIATIVE_ROLE_NOT_FOUND
            )
    else:
        # Guild-only mapping: clear initiative fields
        mapping.initiative_id = None
        mapping.initiative_role_id = None

    mapping.updated_at = datetime.now(timezone.utc)
    session.add(mapping)
    await session.commit()
    await session.refresh(mapping)
    return await _enrich_mapping(session, mapping)


@router.delete("/oidc-mappings/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_oidc_mapping(
    mapping_id: int,
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> None:
    mapping = (
        await session.exec(
            select(OIDCClaimMapping).where(OIDCClaimMapping.id == mapping_id)
        )
    ).one_or_none()
    if not mapping:
        raise HTTPException(status_code=404, detail=SettingsMessages.MAPPING_NOT_FOUND)
    await session.delete(mapping)
    await session.commit()


@router.get("/oidc-mappings/options")
async def get_oidc_mapping_options(
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> dict:
    """Return all guilds, initiatives, and initiative roles for the mapping form."""
    # Guilds live in shared public; materialize them before routing into any guild
    # schema (routing expunges the ORM objects).
    guilds = (await session.exec(select(Guild).order_by(Guild.name))).all()
    guild_payload = [{"id": g.id, "name": g.name} for g in guilds]

    # Initiatives and initiative roles are guild-scoped content: their rows live in
    # each guild's guild_<id> schema, not in the empty public copies. Route into
    # every guild's schema in turn and collect them. Row ids are unique only within
    # a schema, so each role carries its guild_id for the client to disambiguate
    # against colliding initiative ids across guilds.
    initiatives_payload: list[dict] = []
    roles_payload: list[dict] = []
    try:
        for g in guild_payload:
            await _route_admin_to_guild(session, g["id"])
            initiatives = (
                await session.exec(select(Initiative).order_by(Initiative.name))
            ).all()
            roles = (
                await session.exec(
                    select(InitiativeRoleModel).order_by(InitiativeRoleModel.position)
                )
            ).all()
            initiatives_payload.extend(
                {"id": i.id, "name": i.name, "guild_id": i.guild_id}
                for i in initiatives
            )
            roles_payload.extend(
                {
                    "id": r.id,
                    "name": r.display_name,
                    "initiative_id": r.initiative_id,
                    "guild_id": g["id"],
                }
                for r in roles
            )
    finally:
        # Don't leave the pooled connection routed into the last guild's schema:
        # reset to the neutral admin baseline like every write path in this file.
        await _reset_admin_session(session)

    return {
        "guilds": guild_payload,
        "initiatives": initiatives_payload,
        "initiative_roles": roles_payload,
    }
