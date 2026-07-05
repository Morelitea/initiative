"""Platform-level AI settings endpoints.

App-wide AI config (provider, model, API key) gated on ``config.manage``
(owner only). Mounted top-level under ``/settings`` — NOT guild-scoped.
The guild/user legs of the AI-settings cascade live in
``tenant_endpoints/ai_settings.py`` under ``/g/{guild_id}/settings``.
"""

from fastapi import APIRouter

from app.api.deps import UserSessionDep
from app.api.v1.platform_endpoints.admin import ConfigManageDep
from app.schemas.ai_settings import (
    PlatformAISettingsResponse,
    PlatformAISettingsUpdate,
)
from app.services import ai_settings as ai_settings_service

platform_router = APIRouter()


@platform_router.get("/ai/platform", response_model=PlatformAISettingsResponse)
async def get_platform_ai_settings(
    session: UserSessionDep,
    _admin: ConfigManageDep,
) -> PlatformAISettingsResponse:
    """Get platform-level AI settings (``config.manage`` — owner only, owner-scoped)."""
    return await ai_settings_service.get_platform_ai_settings(session)


@platform_router.put("/ai/platform", response_model=PlatformAISettingsResponse)
async def update_platform_ai_settings(
    payload: PlatformAISettingsUpdate,
    session: UserSessionDep,
    _admin: ConfigManageDep,
) -> PlatformAISettingsResponse:
    """Update platform-level AI settings (``config.manage`` — owner only).

    Owner-scoped session: ``app_settings`` is owner-only after Phase 2 (GRANT + RLS),
    so this write runs as ``platform_owner`` rather than the bare login role.
    """
    data = payload.model_dump(exclude_unset=True)
    api_key_provided = "api_key" in data
    return await ai_settings_service.update_platform_ai_settings(
        session, payload, api_key_provided=api_key_provided
    )
