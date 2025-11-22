from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select

from app.api.deps import SessionDep, require_roles
from app.core.config import settings as app_config
from app.models.user import User, UserRole
from app.schemas.api_key import ApiKeyCreateRequest, ApiKeyCreateResponse, ApiKeyListResponse
from app.schemas.settings import (
    InterfaceSettingsResponse,
    InterfaceSettingsUpdate,
    OIDCSettingsResponse,
    OIDCSettingsUpdate,
    RegistrationSettingsResponse,
    RegistrationSettingsUpdate,
)
from app.services import api_keys as api_keys_service
from app.services import app_settings as app_settings_service

router = APIRouter()

AdminUser = Annotated[User, Depends(require_roles(UserRole.admin))]


def _backend_redirect_uri() -> str:
    return f"{app_config.APP_URL.rstrip('/')}{app_config.API_V1_STR}/auth/oidc/callback"


def _frontend_redirect_uri() -> str:
    return f"{app_config.APP_URL.rstrip('/')}/oidc/callback"


@router.get("/registration", response_model=RegistrationSettingsResponse)
async def get_registration_settings(session: SessionDep, _: AdminUser) -> RegistrationSettingsResponse:
    settings_obj = await app_settings_service.get_or_create_app_settings(session)
    pending_result = await session.exec(select(User).where(User.is_active.is_(False)))
    pending_users = pending_result.all()
    return RegistrationSettingsResponse(
        auto_approved_domains=settings_obj.auto_approved_domains,
        pending_users=pending_users,
    )


@router.get("/auth", response_model=OIDCSettingsResponse)
async def get_oidc_settings(session: SessionDep, _: AdminUser) -> OIDCSettingsResponse:
    settings_obj = await app_settings_service.get_or_create_app_settings(session)
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
    _: AdminUser,
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


@router.put("/registration", response_model=RegistrationSettingsResponse)
async def update_registration_settings(
    payload: RegistrationSettingsUpdate,
    session: SessionDep,
    _: AdminUser,
) -> RegistrationSettingsResponse:
    settings_obj = await app_settings_service.update_auto_approved_domains(session, payload.auto_approved_domains)
    pending_result = await session.exec(select(User).where(User.is_active.is_(False)))
    pending_users = pending_result.all()
    return RegistrationSettingsResponse(
        auto_approved_domains=settings_obj.auto_approved_domains,
        pending_users=pending_users,
    )


@router.get("/interface", response_model=InterfaceSettingsResponse)
async def get_interface_settings(session: SessionDep) -> InterfaceSettingsResponse:
    settings_obj = await app_settings_service.get_or_create_app_settings(session)
    return InterfaceSettingsResponse(
        light_accent_color=settings_obj.light_accent_color,
        dark_accent_color=settings_obj.dark_accent_color,
    )


@router.get("/api-keys", response_model=ApiKeyListResponse)
async def list_api_keys(session: SessionDep, current_admin: AdminUser) -> ApiKeyListResponse:
    keys = await api_keys_service.list_api_keys(session, user=current_admin)
    return ApiKeyListResponse(keys=keys)


@router.post("/api-keys", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: ApiKeyCreateRequest,
    session: SessionDep,
    current_admin: AdminUser,
) -> ApiKeyCreateResponse:
    secret, api_key = await api_keys_service.create_api_key(
        session,
        user=current_admin,
        name=payload.name,
        expires_at=payload.expires_at,
    )
    return ApiKeyCreateResponse(api_key=api_key, secret=secret)


@router.delete("/api-keys/{api_key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(api_key_id: int, session: SessionDep, current_admin: AdminUser) -> None:
    deleted = await api_keys_service.delete_api_key(session, user=current_admin, api_key_id=api_key_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")


@router.put("/interface", response_model=InterfaceSettingsResponse)
async def update_interface_settings(
    payload: InterfaceSettingsUpdate,
    session: SessionDep,
    _: AdminUser,
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
