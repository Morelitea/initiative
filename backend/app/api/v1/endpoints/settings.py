from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from app.api.deps import SessionDep, get_current_active_user, GuildContext, require_guild_roles
from app.core.config import settings as app_config
from app.models.user import User
from app.models.app_setting import AppSetting
from app.models.guild import GuildRole
from app.schemas.api_key import ApiKeyCreateRequest, ApiKeyCreateResponse, ApiKeyListResponse
from app.schemas.settings import (
    EmailSettingsResponse,
    EmailSettingsUpdate,
    EmailTestRequest,
    InterfaceSettingsResponse,
    InterfaceSettingsUpdate,
    OIDCSettingsResponse,
    OIDCSettingsUpdate,
    RoleLabelsResponse,
    RoleLabelsUpdate,
)
from app.services import api_keys as api_keys_service
from app.services import app_settings as app_settings_service
from app.services import email as email_service

router = APIRouter()

GuildAdminContext = Annotated[GuildContext, Depends(require_guild_roles(GuildRole.admin))]
SUPER_USER_ID = 1


def _backend_redirect_uri() -> str:
    return f"{app_config.APP_URL.rstrip('/')}{app_config.API_V1_STR}/auth/oidc/callback"


def _frontend_redirect_uri() -> str:
    return f"{app_config.APP_URL.rstrip('/')}/oidc/callback"


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


def _require_super_user(current_user: Annotated[User, Depends(get_current_active_user)]) -> User:
    if current_user.id != SUPER_USER_ID:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super user access required")
    return current_user


@router.get("/auth", response_model=OIDCSettingsResponse)
async def get_oidc_settings(
    session: SessionDep,
    _super_user: Annotated[User, Depends(_require_super_user)],
) -> OIDCSettingsResponse:
    settings_obj = await app_settings_service.get_app_settings(session)
    return OIDCSettingsResponse(
        enabled=settings_obj.oidc_enabled,
        discovery_url=settings_obj.oidc_discovery_url,
        client_id=settings_obj.oidc_client_id,
        redirect_uri=_backend_redirect_uri(),
        post_login_redirect=_frontend_redirect_uri(),
        provider_name=settings_obj.oidc_provider_name,
        scopes=settings_obj.oidc_scopes,
    )


@router.put("/auth", response_model=OIDCSettingsResponse)
async def update_oidc_settings(
    payload: OIDCSettingsUpdate,
    session: SessionDep,
    _super_user: Annotated[User, Depends(_require_super_user)],
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
        provider_name=updated.oidc_provider_name,
        scopes=updated.oidc_scopes,
    )


@router.get("/interface", response_model=InterfaceSettingsResponse)
async def get_interface_settings(
    session: SessionDep,
    _current_user: Annotated[User, Depends(get_current_active_user)],
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


@router.get("/api-keys", response_model=ApiKeyListResponse)
async def list_api_keys(
    session: SessionDep,
    current_admin: Annotated[User, Depends(get_current_active_user)],
    _guild_context: GuildAdminContext,
) -> ApiKeyListResponse:
    keys = await api_keys_service.list_api_keys(session, user=current_admin)
    return ApiKeyListResponse(keys=keys)


@router.post("/api-keys", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: ApiKeyCreateRequest,
    session: SessionDep,
    current_admin: Annotated[User, Depends(get_current_active_user)],
    _guild_context: GuildAdminContext,
) -> ApiKeyCreateResponse:
    secret, api_key = await api_keys_service.create_api_key(
        session,
        user=current_admin,
        name=payload.name,
        expires_at=payload.expires_at,
    )
    return ApiKeyCreateResponse(api_key=api_key, secret=secret)


@router.delete("/api-keys/{api_key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    api_key_id: int,
    session: SessionDep,
    current_admin: Annotated[User, Depends(get_current_active_user)],
    _guild_context: GuildAdminContext,
) -> None:
    deleted = await api_keys_service.delete_api_key(session, user=current_admin, api_key_id=api_key_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")


@router.put("/interface", response_model=InterfaceSettingsResponse)
async def update_interface_settings(
    payload: InterfaceSettingsUpdate,
    session: SessionDep,
    _super_user: Annotated[User, Depends(_require_super_user)],
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
    _super_user: Annotated[User, Depends(_require_super_user)],
) -> RoleLabelsResponse:
    updated = await app_settings_service.update_role_labels(
        session,
        labels={k: v for k, v in payload.dict(exclude_unset=True).items()},
    )
    return RoleLabelsResponse(**updated.role_labels)


@router.get("/email", response_model=EmailSettingsResponse)
async def get_email_settings(
    session: SessionDep,
    _super_user: Annotated[User, Depends(_require_super_user)],
) -> EmailSettingsResponse:
    settings_obj = await app_settings_service.get_app_settings(session)
    return _email_settings_payload(settings_obj)


@router.put("/email", response_model=EmailSettingsResponse)
async def update_email_settings(
    payload: EmailSettingsUpdate,
    session: SessionDep,
    _super_user: Annotated[User, Depends(_require_super_user)],
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
    _super_user: Annotated[User, Depends(_require_super_user)],
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
