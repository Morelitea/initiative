from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import select

from app.api.deps import SessionDep, require_roles
from app.core.config import settings as app_config
from app.models.user import User, UserRole
from app.schemas.settings import (
    OIDCSettingsResponse,
    OIDCSettingsUpdate,
    RegistrationSettingsResponse,
    RegistrationSettingsUpdate,
)
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
