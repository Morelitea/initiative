from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AIProvider(str, Enum):
    openai = "openai"
    anthropic = "anthropic"
    ollama = "ollama"
    custom = "custom"


# Platform (AppSetting) level schemas
class PlatformAISettingsResponse(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    enabled: bool
    provider: Optional[AIProvider] = None
    has_api_key: bool = False
    base_url: Optional[str] = None
    model: Optional[str] = None
    allow_guild_override: bool = True
    allow_user_override: bool = True


class PlatformAISettingsUpdate(BaseModel):
    enabled: bool
    provider: Optional[AIProvider] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    allow_guild_override: bool = True
    allow_user_override: bool = True


# Guild level schemas
class GuildAISettingsResponse(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    # Guild's own settings (null = inherit)
    enabled: Optional[bool] = None
    provider: Optional[AIProvider] = None
    has_api_key: bool = False
    base_url: Optional[str] = None
    model: Optional[str] = None
    allow_user_override: Optional[bool] = None

    # Effective (computed) settings
    effective_enabled: bool = False
    effective_provider: Optional[AIProvider] = None
    effective_base_url: Optional[str] = None
    effective_model: Optional[str] = None
    effective_allow_user_override: bool = True

    # Permission flags
    can_override: bool = True  # Whether guild can override platform settings


class GuildAISettingsUpdate(BaseModel):
    enabled: Optional[bool] = None
    provider: Optional[AIProvider] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    allow_user_override: Optional[bool] = None
    clear_settings: bool = Field(
        default=False,
        description="If true, clears all guild AI settings to inherit from platform"
    )


# User level schemas
class UserAISettingsResponse(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    # User's own settings (null = inherit)
    enabled: Optional[bool] = None
    provider: Optional[AIProvider] = None
    has_api_key: bool = False
    base_url: Optional[str] = None
    model: Optional[str] = None

    # Effective (computed) settings
    effective_enabled: bool = False
    effective_provider: Optional[AIProvider] = None
    effective_base_url: Optional[str] = None
    effective_model: Optional[str] = None

    # Permission flags
    can_override: bool = True  # Whether user can override guild/platform settings
    settings_source: str = "platform"  # "platform", "guild", or "user"


class UserAISettingsUpdate(BaseModel):
    enabled: Optional[bool] = None
    provider: Optional[AIProvider] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    clear_settings: bool = Field(
        default=False,
        description="If true, clears all user AI settings to inherit from guild/platform"
    )


# Resolved settings (final computed, used internally)
class ResolvedAISettings(BaseModel):
    enabled: bool = False
    provider: Optional[AIProvider] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    source: str = "platform"  # Where the settings came from


# Resolved settings response (without API key for frontend)
class ResolvedAISettingsResponse(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    enabled: bool = False
    provider: Optional[AIProvider] = None
    has_api_key: bool = False
    base_url: Optional[str] = None
    model: Optional[str] = None
    source: str = "platform"


# Test connection schemas
class AITestConnectionRequest(BaseModel):
    provider: AIProvider
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None


class AITestConnectionResponse(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    success: bool
    message: str
    available_models: Optional[list[str]] = None


# Fetch models schemas
class AIModelsRequest(BaseModel):
    provider: AIProvider
    api_key: Optional[str] = None
    base_url: Optional[str] = None


class AIModelsResponse(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    models: list[str]
    error: Optional[str] = None
