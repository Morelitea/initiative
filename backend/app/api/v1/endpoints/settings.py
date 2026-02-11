from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import SessionDep, get_current_active_user, GuildContext, require_guild_roles
from app.api.v1.endpoints.admin import AdminUserDep
from app.core.config import settings as app_config
from app.core.rate_limit import limiter
from app.db.session import get_admin_session
from app.models.user import User
from app.models.app_setting import AppSetting
from app.models.guild import Guild, GuildRole
from app.models.initiative import Initiative, InitiativeRoleModel
from app.models.oidc_claim_mapping import OIDCClaimMapping, OIDCMappingTargetType
from app.schemas.settings import (
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
    RoleLabelsResponse,
    RoleLabelsUpdate,
)
from app.schemas.push import FCMConfigResponse
from app.services import app_settings as app_settings_service
from app.services import email as email_service

AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]

router = APIRouter()

GuildAdminContext = Annotated[GuildContext, Depends(require_guild_roles(GuildRole.admin))]


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
        has_password=bool(settings_obj.smtp_password),
        from_address=settings_obj.smtp_from_address,
        test_recipient=settings_obj.smtp_test_recipient,
    )


@router.get("/auth", response_model=OIDCSettingsResponse)
async def get_oidc_settings(
    session: SessionDep,
    _admin: AdminUserDep,
) -> OIDCSettingsResponse:
    settings_obj = await app_settings_service.get_app_settings(session)
    return OIDCSettingsResponse(
        enabled=settings_obj.oidc_enabled,
        discovery_url=settings_obj.oidc_discovery_url,
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
    session: SessionDep,
    _admin: AdminUserDep,
) -> OIDCSettingsResponse:
    updated = await app_settings_service.update_oidc_settings(
        session,
        enabled=payload.enabled,
        discovery_url=payload.discovery_url,
        client_id=payload.client_id,
        client_secret=payload.client_secret,
        provider_name=payload.provider_name,
        scopes=payload.scopes,
    )
    return OIDCSettingsResponse(
        enabled=updated.oidc_enabled,
        discovery_url=updated.oidc_discovery_url,
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


@router.get("/roles", response_model=RoleLabelsResponse)
async def get_role_labels(
    session: SessionDep,
    _current_user: Annotated[User, Depends(get_current_active_user)],
) -> RoleLabelsResponse:
    settings_obj = await app_settings_service.get_app_settings(session)
    return RoleLabelsResponse(**settings_obj.role_labels)


@router.put("/interface", response_model=InterfaceSettingsResponse)
async def update_interface_settings(
    payload: InterfaceSettingsUpdate,
    session: SessionDep,
    _admin: AdminUserDep,
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


@router.put("/roles", response_model=RoleLabelsResponse)
async def update_role_labels(
    payload: RoleLabelsUpdate,
    session: SessionDep,
    _admin: AdminUserDep,
) -> RoleLabelsResponse:
    updated = await app_settings_service.update_role_labels(
        session,
        labels={k: v for k, v in payload.dict(exclude_unset=True).items()},
    )
    return RoleLabelsResponse(**updated.role_labels)


@router.get("/email", response_model=EmailSettingsResponse)
async def get_email_settings(
    session: SessionDep,
    _admin: AdminUserDep,
) -> EmailSettingsResponse:
    settings_obj = await app_settings_service.get_app_settings(session)
    return _email_settings_payload(settings_obj)


@router.put("/email", response_model=EmailSettingsResponse)
async def update_email_settings(
    payload: EmailSettingsUpdate,
    session: SessionDep,
    _admin: AdminUserDep,
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
    session: SessionDep,
    _admin: AdminUserDep,
) -> dict:
    settings_obj = await app_settings_service.get_app_settings(session)
    recipient = payload.recipient or settings_obj.smtp_test_recipient
    if not recipient:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provide a test email address.")
    try:
        await email_service.send_test_email(session, recipient)
    except email_service.EmailNotConfiguredError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="SMTP settings are incomplete.") from None
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
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
        application_id=app_config.FCM_APPLICATION_ID if app_config.FCM_ENABLED else None,
        api_key=app_config.FCM_API_KEY if app_config.FCM_ENABLED else None,
        sender_id=app_config.FCM_SENDER_ID if app_config.FCM_ENABLED else None,
    )


# --- OIDC Claim Mapping endpoints ---


async def _enrich_mapping(session: AsyncSession, mapping: OIDCClaimMapping) -> OIDCClaimMappingRead:
    """Build a read schema with denormalized names."""
    guild_name = None
    initiative_name = None
    initiative_role_name = None

    guild = (await session.exec(select(Guild).where(Guild.id == mapping.guild_id))).one_or_none()
    if guild:
        guild_name = guild.name

    if mapping.initiative_id is not None:
        initiative = (await session.exec(
            select(Initiative).where(Initiative.id == mapping.initiative_id)
        )).one_or_none()
        if initiative:
            initiative_name = initiative.name

    if mapping.initiative_role_id is not None:
        role = (await session.exec(
            select(InitiativeRoleModel).where(InitiativeRoleModel.id == mapping.initiative_role_id)
        )).one_or_none()
        if role:
            initiative_role_name = role.display_name

    return OIDCClaimMappingRead(
        id=mapping.id,
        claim_value=mapping.claim_value,
        target_type=mapping.target_type.value if isinstance(mapping.target_type, OIDCMappingTargetType) else mapping.target_type,
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
    _admin: AdminUserDep,
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
    _admin: AdminUserDep,
) -> dict:
    settings_obj = await app_settings_service.get_app_settings(session)
    cleaned = payload.claim_path.strip() if payload.claim_path else None
    settings_obj.oidc_role_claim_path = cleaned or None
    session.add(settings_obj)
    await session.commit()
    return {"claim_path": settings_obj.oidc_role_claim_path}


@router.post("/oidc-mappings", response_model=OIDCClaimMappingRead, status_code=status.HTTP_201_CREATED)
async def create_oidc_mapping(
    payload: OIDCClaimMappingCreate,
    session: AdminSessionDep,
    _admin: AdminUserDep,
) -> OIDCClaimMappingRead:
    # Validate target_type
    try:
        target_type = OIDCMappingTargetType(payload.target_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="target_type must be 'guild' or 'initiative'")

    # Validate guild_role
    if payload.guild_role not in ("admin", "member"):
        raise HTTPException(status_code=400, detail="guild_role must be 'admin' or 'member'")

    # Validate guild exists
    guild = (await session.exec(select(Guild).where(Guild.id == payload.guild_id))).one_or_none()
    if not guild:
        raise HTTPException(status_code=400, detail="Guild not found")

    # Validate initiative fields if target_type is initiative
    if target_type == OIDCMappingTargetType.initiative:
        if not payload.initiative_id:
            raise HTTPException(status_code=400, detail="initiative_id required for initiative mappings")
        if not payload.initiative_role_id:
            raise HTTPException(status_code=400, detail="initiative_role_id required for initiative mappings")
        initiative = (await session.exec(
            select(Initiative).where(Initiative.id == payload.initiative_id)
        )).one_or_none()
        if not initiative:
            raise HTTPException(status_code=400, detail="Initiative not found")
        if initiative.guild_id != payload.guild_id:
            raise HTTPException(status_code=400, detail="Initiative does not belong to the specified guild")
        role = (await session.exec(
            select(InitiativeRoleModel).where(InitiativeRoleModel.id == payload.initiative_role_id)
        )).one_or_none()
        if not role:
            raise HTTPException(status_code=400, detail="Initiative role not found")

    mapping = OIDCClaimMapping(
        claim_value=payload.claim_value.strip(),
        target_type=target_type,
        guild_id=payload.guild_id,
        guild_role=payload.guild_role,
        initiative_id=payload.initiative_id if target_type == OIDCMappingTargetType.initiative else None,
        initiative_role_id=payload.initiative_role_id if target_type == OIDCMappingTargetType.initiative else None,
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
    _admin: AdminUserDep,
) -> OIDCClaimMappingRead:
    mapping = (await session.exec(
        select(OIDCClaimMapping).where(OIDCClaimMapping.id == mapping_id)
    )).one_or_none()
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")

    data = payload.model_dump(exclude_unset=True)
    if "claim_value" in data and data["claim_value"] is not None:
        mapping.claim_value = data["claim_value"].strip()
    if "target_type" in data and data["target_type"] is not None:
        try:
            mapping.target_type = OIDCMappingTargetType(data["target_type"])
        except ValueError:
            raise HTTPException(status_code=400, detail="target_type must be 'guild' or 'initiative'")
    if "guild_id" in data and data["guild_id"] is not None:
        guild = (await session.exec(select(Guild).where(Guild.id == data["guild_id"]))).one_or_none()
        if not guild:
            raise HTTPException(status_code=400, detail="Guild not found")
        mapping.guild_id = data["guild_id"]
    if "guild_role" in data and data["guild_role"] is not None:
        if data["guild_role"] not in ("admin", "member"):
            raise HTTPException(status_code=400, detail="guild_role must be 'admin' or 'member'")
        mapping.guild_role = data["guild_role"]
    if "initiative_id" in data:
        mapping.initiative_id = data["initiative_id"]
    if "initiative_role_id" in data:
        mapping.initiative_role_id = data["initiative_role_id"]

    # Validate initiative consistency
    effective_target = mapping.target_type
    if isinstance(effective_target, str):
        effective_target = OIDCMappingTargetType(effective_target)
    if effective_target == OIDCMappingTargetType.initiative:
        if not mapping.initiative_id or not mapping.initiative_role_id:
            raise HTTPException(status_code=400, detail="initiative_id and initiative_role_id required for initiative mappings")

    mapping.updated_at = datetime.now(timezone.utc)
    session.add(mapping)
    await session.commit()
    await session.refresh(mapping)
    return await _enrich_mapping(session, mapping)


@router.delete("/oidc-mappings/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_oidc_mapping(
    mapping_id: int,
    session: AdminSessionDep,
    _admin: AdminUserDep,
) -> None:
    mapping = (await session.exec(
        select(OIDCClaimMapping).where(OIDCClaimMapping.id == mapping_id)
    )).one_or_none()
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")
    await session.delete(mapping)
    await session.commit()


@router.get("/oidc-mappings/options")
async def get_oidc_mapping_options(
    session: AdminSessionDep,
    _admin: AdminUserDep,
) -> dict:
    """Return all guilds, initiatives, and initiative roles for the mapping form."""
    guilds = (await session.exec(select(Guild).order_by(Guild.name))).all()
    initiatives = (await session.exec(select(Initiative).order_by(Initiative.name))).all()
    roles = (await session.exec(select(InitiativeRoleModel).order_by(InitiativeRoleModel.position))).all()
    return {
        "guilds": [{"id": g.id, "name": g.name} for g in guilds],
        "initiatives": [
            {"id": i.id, "name": i.name, "guild_id": i.guild_id}
            for i in initiatives
        ],
        "initiative_roles": [
            {"id": r.id, "name": r.display_name, "initiative_id": r.initiative_id}
            for r in roles
        ],
    }
