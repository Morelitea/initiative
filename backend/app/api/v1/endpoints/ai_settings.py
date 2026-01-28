"""AI Settings API endpoints.

Provides hierarchical AI settings management:
- Platform level: Platform admins only
- Guild level: Guild admins
- User level: Any authenticated user (if allowed)
"""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.api.deps import SessionDep, get_current_active_user, GuildContext, require_guild_roles
from app.api.v1.endpoints.admin import AdminUserDep
from app.models.guild import GuildRole
from app.models.user import User
from app.schemas.ai_settings import (
    AIModelsRequest,
    AIModelsResponse,
    AITestConnectionRequest,
    AITestConnectionResponse,
    GuildAISettingsResponse,
    GuildAISettingsUpdate,
    PlatformAISettingsResponse,
    PlatformAISettingsUpdate,
    ResolvedAISettingsResponse,
    UserAISettingsResponse,
    UserAISettingsUpdate,
)
from app.services import ai_settings as ai_settings_service

router = APIRouter()

GuildAdminContext = Annotated[GuildContext, Depends(require_guild_roles(GuildRole.admin))]


# Platform-level endpoints (platform admin only)
@router.get("/ai/platform", response_model=PlatformAISettingsResponse)
async def get_platform_ai_settings(
    session: SessionDep,
    _admin: AdminUserDep,
) -> PlatformAISettingsResponse:
    """Get platform-level AI settings. Platform admin only."""
    return await ai_settings_service.get_platform_ai_settings(session)


@router.put("/ai/platform", response_model=PlatformAISettingsResponse)
async def update_platform_ai_settings(
    payload: PlatformAISettingsUpdate,
    session: SessionDep,
    _admin: AdminUserDep,
) -> PlatformAISettingsResponse:
    """Update platform-level AI settings. Platform admin only."""
    data = payload.model_dump(exclude_unset=True)
    api_key_provided = "api_key" in data
    return await ai_settings_service.update_platform_ai_settings(
        session, payload, api_key_provided=api_key_provided
    )


# Guild-level endpoints (guild admin only)
@router.get("/ai/guild", response_model=GuildAISettingsResponse)
async def get_guild_ai_settings(
    session: SessionDep,
    guild_ctx: GuildAdminContext,
) -> GuildAISettingsResponse:
    """Get guild-level AI settings. Guild admin only."""
    return await ai_settings_service.get_guild_ai_settings(session, guild_ctx.guild_id)


@router.put("/ai/guild", response_model=GuildAISettingsResponse)
async def update_guild_ai_settings(
    payload: GuildAISettingsUpdate,
    session: SessionDep,
    guild_ctx: GuildAdminContext,
) -> GuildAISettingsResponse:
    """Update guild-level AI settings. Guild admin only."""
    try:
        data = payload.model_dump(exclude_unset=True)
        api_key_provided = "api_key" in data
        return await ai_settings_service.update_guild_ai_settings(
            session, guild_ctx.guild_id, payload, api_key_provided=api_key_provided
        )
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


# User-level endpoints (any authenticated user)
@router.get("/ai/user", response_model=UserAISettingsResponse)
async def get_user_ai_settings(
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    x_guild_id: Optional[int] = Header(None, alias="X-Guild-ID"),
) -> UserAISettingsResponse:
    """Get user-level AI settings."""
    guild_id = x_guild_id or current_user.active_guild_id
    return await ai_settings_service.get_user_ai_settings(session, current_user, guild_id)


@router.put("/ai/user", response_model=UserAISettingsResponse)
async def update_user_ai_settings(
    payload: UserAISettingsUpdate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    x_guild_id: Optional[int] = Header(None, alias="X-Guild-ID"),
) -> UserAISettingsResponse:
    """Update user-level AI settings."""
    try:
        guild_id = x_guild_id or current_user.active_guild_id
        data = payload.model_dump(exclude_unset=True)
        api_key_provided = "api_key" in data
        return await ai_settings_service.update_user_ai_settings(
            session, current_user, payload, guild_id, api_key_provided=api_key_provided
        )
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


# Resolved settings endpoint (any authenticated user)
@router.get("/ai/resolved", response_model=ResolvedAISettingsResponse)
async def get_resolved_ai_settings(
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    x_guild_id: Optional[int] = Header(None, alias="X-Guild-ID"),
) -> ResolvedAISettingsResponse:
    """Get resolved (effective) AI settings for the current user.

    This returns the final computed settings without exposing API keys.
    """
    guild_id = x_guild_id or current_user.active_guild_id
    return await ai_settings_service.get_resolved_ai_settings_response(session, current_user, guild_id)


# Test connection endpoint (any authenticated user)
@router.post("/ai/test", response_model=AITestConnectionResponse)
async def test_ai_connection(
    payload: AITestConnectionRequest,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    x_guild_id: Optional[int] = Header(None, alias="X-Guild-ID"),
) -> AITestConnectionResponse:
    """Test connection to an AI provider.

    If no API key is provided in the request, it will use the existing
    key from the user's resolved settings.
    """
    api_key = payload.api_key
    if not api_key:
        # Get existing key from resolved settings
        guild_id = x_guild_id or current_user.active_guild_id
        resolved = await ai_settings_service.resolve_ai_settings(session, current_user, guild_id)
        api_key = resolved.api_key

    return await ai_settings_service.test_ai_connection(payload, existing_api_key=api_key)


# Fetch models endpoint (any authenticated user)
@router.post("/ai/models", response_model=AIModelsResponse)
async def fetch_ai_models(
    payload: AIModelsRequest,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    x_guild_id: Optional[int] = Header(None, alias="X-Guild-ID"),
) -> AIModelsResponse:
    """Fetch available models from an AI provider.

    If no API key is provided in the request, it will use the existing
    key from the user's resolved settings.
    """
    api_key = payload.api_key
    if not api_key:
        # Get existing key from resolved settings
        guild_id = x_guild_id or current_user.active_guild_id
        resolved = await ai_settings_service.resolve_ai_settings(session, current_user, guild_id)
        api_key = resolved.api_key

    models, error = await ai_settings_service.fetch_models(
        payload.provider,
        api_key,
        payload.base_url,
    )

    return AIModelsResponse(models=models, error=error)
