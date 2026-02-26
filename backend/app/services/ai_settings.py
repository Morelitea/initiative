"""AI Settings service for managing hierarchical AI configuration.

This service handles AI settings at three levels:
- Platform (AppSetting): Global defaults and permissions
- Guild (GuildSetting): Guild-level overrides (if allowed)
- User: User-level overrides (if allowed)

Settings cascade: Platform -> Guild -> User
"""

from __future__ import annotations

import httpx
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import decrypt_field, encrypt_field, SALT_AI_API_KEY
from app.db.session import reapply_rls_context

from app.models.user import User
from app.schemas.ai_settings import (
    AIProvider,
    AITestConnectionRequest,
    AITestConnectionResponse,
    GuildAISettingsResponse,
    GuildAISettingsUpdate,
    PlatformAISettingsResponse,
    PlatformAISettingsUpdate,
    ResolvedAISettings,
    ResolvedAISettingsResponse,
    UserAISettingsResponse,
    UserAISettingsUpdate,
)
from app.services.app_settings import get_app_settings, get_or_create_guild_settings


def _normalize_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


# Platform-level AI settings
async def get_platform_ai_settings(session: AsyncSession) -> PlatformAISettingsResponse:
    """Get platform-level AI settings (super user only)."""
    settings = await get_app_settings(session)
    return PlatformAISettingsResponse(
        enabled=settings.ai_enabled,
        provider=AIProvider(settings.ai_provider) if settings.ai_provider else None,
        has_api_key=bool(settings.ai_api_key_encrypted),
        base_url=settings.ai_base_url,
        model=settings.ai_model,
        allow_guild_override=settings.ai_allow_guild_override,
        allow_user_override=settings.ai_allow_user_override,
    )


async def update_platform_ai_settings(
    session: AsyncSession,
    payload: PlatformAISettingsUpdate,
    *,
    api_key_provided: bool = False,
) -> PlatformAISettingsResponse:
    """Update platform-level AI settings (super user only)."""
    settings = await get_app_settings(session)

    settings.ai_enabled = payload.enabled
    settings.ai_provider = payload.provider.value if payload.provider else None
    settings.ai_base_url = _normalize_optional_string(payload.base_url)
    settings.ai_model = _normalize_optional_string(payload.model)
    settings.ai_allow_guild_override = payload.allow_guild_override
    settings.ai_allow_user_override = payload.allow_user_override

    if api_key_provided:
        normalized = _normalize_optional_string(payload.api_key)
        settings.ai_api_key_encrypted = encrypt_field(normalized, SALT_AI_API_KEY) if normalized else None

    session.add(settings)
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(settings)

    return PlatformAISettingsResponse(
        enabled=settings.ai_enabled,
        provider=AIProvider(settings.ai_provider) if settings.ai_provider else None,
        has_api_key=bool(settings.ai_api_key_encrypted),
        base_url=settings.ai_base_url,
        model=settings.ai_model,
        allow_guild_override=settings.ai_allow_guild_override,
        allow_user_override=settings.ai_allow_user_override,
    )


# Guild-level AI settings
async def get_guild_ai_settings(
    session: AsyncSession,
    guild_id: int,
) -> GuildAISettingsResponse:
    """Get guild-level AI settings with effective (computed) values."""
    platform_settings = await get_app_settings(session)
    guild_settings = await get_or_create_guild_settings(session, guild_id)

    can_override = platform_settings.ai_allow_guild_override

    # Compute effective settings
    effective_enabled = (
        guild_settings.ai_enabled
        if guild_settings.ai_enabled is not None and can_override
        else platform_settings.ai_enabled
    )
    effective_provider = (
        guild_settings.ai_provider
        if guild_settings.ai_provider is not None and can_override
        else platform_settings.ai_provider
    )
    effective_base_url = (
        guild_settings.ai_base_url
        if guild_settings.ai_base_url is not None and can_override
        else platform_settings.ai_base_url
    )
    effective_model = (
        guild_settings.ai_model
        if guild_settings.ai_model is not None and can_override
        else platform_settings.ai_model
    )

    # Determine effective allow_user_override
    if not platform_settings.ai_allow_user_override:
        effective_allow_user_override = False
    elif guild_settings.ai_allow_user_override is not None and can_override:
        effective_allow_user_override = guild_settings.ai_allow_user_override
    else:
        effective_allow_user_override = True

    return GuildAISettingsResponse(
        enabled=guild_settings.ai_enabled,
        provider=AIProvider(guild_settings.ai_provider) if guild_settings.ai_provider else None,
        has_api_key=bool(guild_settings.ai_api_key_encrypted),
        base_url=guild_settings.ai_base_url,
        model=guild_settings.ai_model,
        allow_user_override=guild_settings.ai_allow_user_override,
        effective_enabled=effective_enabled,
        effective_provider=AIProvider(effective_provider) if effective_provider else None,
        effective_base_url=effective_base_url,
        effective_model=effective_model,
        effective_allow_user_override=effective_allow_user_override,
        can_override=can_override,
    )


async def update_guild_ai_settings(
    session: AsyncSession,
    guild_id: int,
    payload: GuildAISettingsUpdate,
    *,
    api_key_provided: bool = False,
) -> GuildAISettingsResponse:
    """Update guild-level AI settings."""
    platform_settings = await get_app_settings(session)

    if not platform_settings.ai_allow_guild_override:
        raise PermissionError("Guild AI settings override is disabled by platform administrator")

    guild_settings = await get_or_create_guild_settings(session, guild_id)

    if payload.clear_settings:
        # Clear all AI settings to inherit from platform
        guild_settings.ai_enabled = None
        guild_settings.ai_provider = None
        guild_settings.ai_api_key_encrypted = None
        guild_settings.ai_base_url = None
        guild_settings.ai_model = None
        guild_settings.ai_allow_user_override = None
    else:
        guild_settings.ai_enabled = payload.enabled
        guild_settings.ai_provider = payload.provider.value if payload.provider else None
        guild_settings.ai_base_url = _normalize_optional_string(payload.base_url)
        guild_settings.ai_model = _normalize_optional_string(payload.model)
        guild_settings.ai_allow_user_override = payload.allow_user_override

        if api_key_provided:
            normalized = _normalize_optional_string(payload.api_key)
            guild_settings.ai_api_key_encrypted = encrypt_field(normalized, SALT_AI_API_KEY) if normalized else None

    session.add(guild_settings)
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(guild_settings)

    return await get_guild_ai_settings(session, guild_id)


# User-level AI settings
async def get_user_ai_settings(
    session: AsyncSession,
    user: User,
    guild_id: int | None = None,
) -> UserAISettingsResponse:
    """Get user-level AI settings with effective (computed) values."""
    platform_settings = await get_app_settings(session)

    # Get guild settings if guild_id is provided
    guild_settings = None
    if guild_id:
        guild_settings = await get_or_create_guild_settings(session, guild_id)

    # Determine if user can override
    can_override = platform_settings.ai_allow_user_override
    if can_override and guild_settings is not None:
        if guild_settings.ai_allow_user_override is not None:
            can_override = guild_settings.ai_allow_user_override

    # Compute effective settings, tracking which levels contribute
    sources: set[str] = {"platform"}

    # Start with platform settings
    effective_enabled = platform_settings.ai_enabled
    effective_provider = platform_settings.ai_provider
    effective_base_url = platform_settings.ai_base_url
    effective_model = platform_settings.ai_model

    # Apply guild overrides if allowed
    if guild_settings and platform_settings.ai_allow_guild_override:
        if guild_settings.ai_enabled is not None:
            effective_enabled = guild_settings.ai_enabled
            sources.add("guild")
        if guild_settings.ai_provider is not None:
            effective_provider = guild_settings.ai_provider
            sources.add("guild")
        if guild_settings.ai_base_url is not None:
            effective_base_url = guild_settings.ai_base_url
            sources.add("guild")
        if guild_settings.ai_model is not None:
            effective_model = guild_settings.ai_model
            sources.add("guild")

    # Apply user overrides if allowed
    if can_override:
        if user.ai_enabled is not None:
            effective_enabled = user.ai_enabled
            sources.add("user")
        if user.ai_provider is not None:
            effective_provider = user.ai_provider
            sources.add("user")
        if user.ai_base_url is not None:
            effective_base_url = user.ai_base_url
            sources.add("user")
        if user.ai_model is not None:
            effective_model = user.ai_model
            sources.add("user")

    # Determine overall settings source
    sources.discard("platform")  # Only count overrides
    if not sources:
        settings_source = "platform"
    elif len(sources) == 1:
        settings_source = sources.pop()
    else:
        settings_source = "mixed"

    return UserAISettingsResponse(
        enabled=user.ai_enabled,
        provider=AIProvider(user.ai_provider) if user.ai_provider else None,
        has_api_key=bool(user.ai_api_key_encrypted),
        base_url=user.ai_base_url,
        model=user.ai_model,
        effective_enabled=effective_enabled,
        effective_provider=AIProvider(effective_provider) if effective_provider else None,
        effective_base_url=effective_base_url,
        effective_model=effective_model,
        can_override=can_override,
        settings_source=settings_source,
    )


async def update_user_ai_settings(
    session: AsyncSession,
    user: User,
    payload: UserAISettingsUpdate,
    guild_id: int | None = None,
    *,
    api_key_provided: bool = False,
) -> UserAISettingsResponse:
    """Update user-level AI settings."""
    platform_settings = await get_app_settings(session)

    # Check if user can override
    can_override = platform_settings.ai_allow_user_override
    if can_override and guild_id:
        guild_settings = await get_or_create_guild_settings(session, guild_id)
        if guild_settings.ai_allow_user_override is not None:
            can_override = guild_settings.ai_allow_user_override

    if not can_override:
        raise PermissionError("User AI settings override is disabled by administrator")

    if payload.clear_settings:
        # Clear all AI settings to inherit from guild/platform
        user.ai_enabled = None
        user.ai_provider = None
        user.ai_api_key_encrypted = None
        user.ai_base_url = None
        user.ai_model = None
    else:
        user.ai_enabled = payload.enabled
        user.ai_provider = payload.provider.value if payload.provider else None
        user.ai_base_url = _normalize_optional_string(payload.base_url)
        user.ai_model = _normalize_optional_string(payload.model)

        if api_key_provided:
            normalized = _normalize_optional_string(payload.api_key)
            user.ai_api_key_encrypted = encrypt_field(normalized, SALT_AI_API_KEY) if normalized else None

    session.add(user)
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(user)

    return await get_user_ai_settings(session, user, guild_id)


# Resolve final settings for AI usage
async def resolve_ai_settings(
    session: AsyncSession,
    user: User,
    guild_id: int | None = None,
) -> ResolvedAISettings:
    """Compute the final AI settings for a user, respecting the hierarchy."""
    platform_settings = await get_app_settings(session)

    # Start with platform settings
    _platform_key = (
        decrypt_field(platform_settings.ai_api_key_encrypted, SALT_AI_API_KEY)
        if platform_settings.ai_api_key_encrypted
        else None
    )
    result = ResolvedAISettings(
        enabled=platform_settings.ai_enabled,
        provider=AIProvider(platform_settings.ai_provider) if platform_settings.ai_provider else None,
        api_key=_platform_key,
        base_url=platform_settings.ai_base_url,
        model=platform_settings.ai_model,
        source="platform",
    )

    # Apply guild overrides if allowed
    if guild_id and platform_settings.ai_allow_guild_override:
        guild_settings = await get_or_create_guild_settings(session, guild_id)
        if guild_settings.ai_enabled is not None:
            result.enabled = guild_settings.ai_enabled
            result.source = "guild"
        if guild_settings.ai_provider is not None:
            result.provider = AIProvider(guild_settings.ai_provider)
            result.source = "guild"
        if guild_settings.ai_api_key_encrypted is not None:
            result.api_key = decrypt_field(guild_settings.ai_api_key_encrypted, SALT_AI_API_KEY)
            result.source = "guild"
        if guild_settings.ai_base_url is not None:
            result.base_url = guild_settings.ai_base_url
            result.source = "guild"
        if guild_settings.ai_model is not None:
            result.model = guild_settings.ai_model
            result.source = "guild"

        # Check user override permission
        can_user_override = platform_settings.ai_allow_user_override
        if guild_settings.ai_allow_user_override is not None:
            can_user_override = guild_settings.ai_allow_user_override
    else:
        can_user_override = platform_settings.ai_allow_user_override

    # Apply user overrides if allowed
    if can_user_override:
        if user.ai_enabled is not None:
            result.enabled = user.ai_enabled
            result.source = "user"
        if user.ai_provider is not None:
            result.provider = AIProvider(user.ai_provider)
            result.source = "user"
        if user.ai_api_key_encrypted is not None:
            result.api_key = decrypt_field(user.ai_api_key_encrypted, SALT_AI_API_KEY)
            result.source = "user"
        if user.ai_base_url is not None:
            result.base_url = user.ai_base_url
            result.source = "user"
        if user.ai_model is not None:
            result.model = user.ai_model
            result.source = "user"

    return result


async def get_resolved_ai_settings_response(
    session: AsyncSession,
    user: User,
    guild_id: int | None = None,
) -> ResolvedAISettingsResponse:
    """Get resolved settings without exposing API key (for frontend)."""
    resolved = await resolve_ai_settings(session, user, guild_id)
    return ResolvedAISettingsResponse(
        enabled=resolved.enabled,
        provider=resolved.provider,
        has_api_key=bool(resolved.api_key),
        base_url=resolved.base_url,
        model=resolved.model,
        source=resolved.source,
    )


# Test AI connection
async def test_ai_connection(
    request: AITestConnectionRequest,
    *,
    existing_api_key: str | None = None,
) -> AITestConnectionResponse:
    """Test connection to an AI provider."""
    api_key = request.api_key or existing_api_key

    if request.provider == AIProvider.openai:
        return await _test_openai_connection(api_key, request.model)
    elif request.provider == AIProvider.anthropic:
        return await _test_anthropic_connection(api_key, request.model)
    elif request.provider == AIProvider.ollama:
        return await _test_ollama_connection(request.base_url, request.model)
    elif request.provider == AIProvider.custom:
        return await _test_custom_connection(api_key, request.base_url, request.model)
    else:
        return AITestConnectionResponse(
            success=False,
            message=f"Unknown provider: {request.provider}",
        )


def _is_openai_chat_model(model_id: str) -> bool:
    """Check if an OpenAI model is a chat/completion model."""
    model_lower = model_id.lower()
    # Include GPT models, O1/O3 reasoning models, and chatgpt models
    chat_prefixes = ("gpt-", "o1", "o3", "chatgpt-")
    # Exclude non-chat models
    excluded = ("whisper", "tts", "dall-e", "embedding", "davinci", "babbage", "curie", "ada", "image", "audio")

    if any(model_lower.startswith(p) for p in chat_prefixes):
        return not any(e in model_lower for e in excluded)
    return False


def _sort_openai_models(models: list[str]) -> list[str]:
    """Sort OpenAI models with newest/best first."""
    # Priority order for model prefixes (higher = better)
    priority = {
        "gpt-4o": 100,
        "gpt-4-turbo": 90,
        "gpt-4": 80,
        "o1": 70,
        "o3": 70,
        "chatgpt-4o": 60,
        "gpt-3.5-turbo": 50,
    }

    def get_priority(model: str) -> int:
        model_lower = model.lower()
        for prefix, prio in priority.items():
            if model_lower.startswith(prefix):
                return prio
        return 0

    return sorted(models, key=lambda m: (-get_priority(m), m))


async def _test_openai_connection(
    api_key: str | None,
    model: str | None,
) -> AITestConnectionResponse:
    """Test OpenAI API connection."""
    if not api_key:
        return AITestConnectionResponse(
            success=False,
            message="API key is required for OpenAI",
        )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )

            if response.status_code == 401:
                return AITestConnectionResponse(
                    success=False,
                    message="Invalid API key",
                )
            elif response.status_code != 200:
                return AITestConnectionResponse(
                    success=False,
                    message=f"API error: {response.status_code}",
                )

            data = response.json()
            all_models = [m["id"] for m in data.get("data", [])]
            chat_models = [m for m in all_models if _is_openai_chat_model(m)]
            sorted_models = _sort_openai_models(chat_models)

            # Validate model if specified
            if model:
                if model not in all_models:
                    return AITestConnectionResponse(
                        success=False,
                        message=f"Model '{model}' not found. Select a model from the list.",
                        available_models=sorted_models,
                    )

            return AITestConnectionResponse(
                success=True,
                message="Connection successful",
                available_models=sorted_models,
            )
    except httpx.TimeoutException:
        return AITestConnectionResponse(
            success=False,
            message="Connection timed out",
        )
    except Exception as e:
        return AITestConnectionResponse(
            success=False,
            message=f"Connection failed: {str(e)}",
        )


async def _test_anthropic_connection(
    api_key: str | None,
    model: str | None,
) -> AITestConnectionResponse:
    """Test Anthropic API connection."""
    if not api_key:
        return AITestConnectionResponse(
            success=False,
            message="API key is required for Anthropic",
        )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Fetch available models from Anthropic's models endpoint
            response = await client.get(
                "https://api.anthropic.com/v1/models",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
            )

            if response.status_code == 401:
                return AITestConnectionResponse(
                    success=False,
                    message="Invalid API key",
                )
            elif response.status_code != 200:
                return AITestConnectionResponse(
                    success=False,
                    message=f"API error: {response.status_code}",
                )

            data = response.json()
            models = [m["id"] for m in data.get("data", [])]

            # Validate model if specified
            if model and models:
                if model not in models:
                    return AITestConnectionResponse(
                        success=False,
                        message=f"Model '{model}' not found. Select a model from the list.",
                        available_models=models,
                    )

            return AITestConnectionResponse(
                success=True,
                message="Connection successful",
                available_models=models,
            )
    except httpx.TimeoutException:
        return AITestConnectionResponse(
            success=False,
            message="Connection timed out",
        )
    except Exception as e:
        return AITestConnectionResponse(
            success=False,
            message=f"Connection failed: {str(e)}",
        )


async def _test_ollama_connection(
    base_url: str | None,
    model: str | None,
) -> AITestConnectionResponse:
    """Test Ollama connection."""
    url = (base_url or "http://localhost:11434").rstrip("/")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{url}/api/tags")

            if response.status_code != 200:
                return AITestConnectionResponse(
                    success=False,
                    message=f"Ollama API error: {response.status_code}",
                )

            data = response.json()
            models = [m["name"] for m in data.get("models", [])]

            # Validate model if specified
            if model and models:
                # Ollama models can be "name" or "name:tag", check both forms
                model_names = {m.split(":")[0] for m in models}
                model_base = model.split(":")[0]
                if model not in models and model_base not in model_names:
                    return AITestConnectionResponse(
                        success=False,
                        message=f"Model '{model}' not found. Select a model from the list.",
                        available_models=models,
                    )

            return AITestConnectionResponse(
                success=True,
                message="Connection successful",
                available_models=models,
            )
    except httpx.ConnectError:
        return AITestConnectionResponse(
            success=False,
            message=f"Could not connect to Ollama at {url}",
        )
    except httpx.TimeoutException:
        return AITestConnectionResponse(
            success=False,
            message="Connection timed out",
        )
    except Exception as e:
        return AITestConnectionResponse(
            success=False,
            message=f"Connection failed: {str(e)}",
        )


async def _test_custom_connection(
    api_key: str | None,
    base_url: str | None,
    model: str | None,
) -> AITestConnectionResponse:
    """Test custom OpenAI-compatible endpoint."""
    if not base_url:
        return AITestConnectionResponse(
            success=False,
            message="Base URL is required for custom provider",
        )

    url = base_url.rstrip("/")
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Try to get models list (OpenAI-compatible)
            response = await client.get(f"{url}/models", headers=headers)

            if response.status_code == 401:
                return AITestConnectionResponse(
                    success=False,
                    message="Invalid API key",
                )
            elif response.status_code == 404:
                # Models endpoint might not exist, try a health check
                return AITestConnectionResponse(
                    success=True,
                    message="Connected (models list not available)",
                    available_models=None,
                )
            elif response.status_code != 200:
                return AITestConnectionResponse(
                    success=False,
                    message=f"API error: {response.status_code}",
                )

            data = response.json()
            models = [m["id"] for m in data.get("data", [])]

            # Validate model if specified and models list is available
            if model and models:
                if model not in models:
                    return AITestConnectionResponse(
                        success=False,
                        message=f"Model '{model}' not found. Select a model from the list.",
                        available_models=models[:20],
                    )

            return AITestConnectionResponse(
                success=True,
                message="Connection successful",
                available_models=models[:20] if models else None,
            )
    except httpx.ConnectError:
        return AITestConnectionResponse(
            success=False,
            message=f"Could not connect to {url}",
        )
    except httpx.TimeoutException:
        return AITestConnectionResponse(
            success=False,
            message="Connection timed out",
        )
    except Exception as e:
        return AITestConnectionResponse(
            success=False,
            message=f"Connection failed: {str(e)}",
        )


# Fetch models functions
async def fetch_models(
    provider: AIProvider,
    api_key: str | None,
    base_url: str | None,
) -> tuple[list[str], str | None]:
    """Fetch available models from an AI provider.

    Returns (models, error_message). If successful, error_message is None.
    """
    if provider == AIProvider.openai:
        return await _fetch_openai_models(api_key)
    elif provider == AIProvider.anthropic:
        return await _fetch_anthropic_models(api_key)
    elif provider == AIProvider.ollama:
        return await _fetch_ollama_models(base_url)
    elif provider == AIProvider.custom:
        return await _fetch_custom_models(api_key, base_url)
    else:
        return [], f"Unknown provider: {provider}"


async def _fetch_openai_models(api_key: str | None) -> tuple[list[str], str | None]:
    """Fetch available models from OpenAI."""
    if not api_key:
        return [], "API key required"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )

            if response.status_code == 401:
                return [], "Invalid API key"
            elif response.status_code != 200:
                return [], f"API error: {response.status_code}"

            data = response.json()
            all_models = [m["id"] for m in data.get("data", [])]
            chat_models = [m for m in all_models if _is_openai_chat_model(m)]
            sorted_models = _sort_openai_models(chat_models)
            return sorted_models, None
    except httpx.TimeoutException:
        return [], "Request timed out"
    except Exception as e:
        return [], str(e)


async def _fetch_anthropic_models(api_key: str | None) -> tuple[list[str], str | None]:
    """Fetch available models from Anthropic."""
    if not api_key:
        return [], "API key required"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://api.anthropic.com/v1/models",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
            )

            if response.status_code == 401:
                return [], "Invalid API key"
            elif response.status_code != 200:
                return [], f"API error: {response.status_code}"

            data = response.json()
            models = [m["id"] for m in data.get("data", [])]
            return models, None
    except httpx.TimeoutException:
        return [], "Request timed out"
    except Exception as e:
        return [], str(e)


async def _fetch_ollama_models(base_url: str | None) -> tuple[list[str], str | None]:
    """Fetch available models from Ollama."""
    url = (base_url or "http://localhost:11434").rstrip("/")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{url}/api/tags")

            if response.status_code != 200:
                return [], f"API error: {response.status_code}"

            data = response.json()
            models = [m["name"] for m in data.get("models", [])]
            return models, None
    except httpx.ConnectError:
        return [], f"Could not connect to Ollama at {url}"
    except httpx.TimeoutException:
        return [], "Request timed out"
    except Exception as e:
        return [], str(e)


async def _fetch_custom_models(
    api_key: str | None,
    base_url: str | None,
) -> tuple[list[str], str | None]:
    """Fetch available models from custom OpenAI-compatible endpoint."""
    if not base_url:
        return [], "Base URL required"

    url = base_url.rstrip("/")
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{url}/models", headers=headers)

            if response.status_code == 401:
                return [], "Invalid API key"
            elif response.status_code == 404:
                return [], "Models endpoint not available"
            elif response.status_code != 200:
                return [], f"API error: {response.status_code}"

            data = response.json()
            models = [m["id"] for m in data.get("data", [])]
            return models[:50], None  # Limit to 50 models
    except httpx.ConnectError:
        return [], f"Could not connect to {url}"
    except httpx.TimeoutException:
        return [], "Request timed out"
    except Exception as e:
        return [], str(e)
