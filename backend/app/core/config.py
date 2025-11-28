from functools import lru_cache
import json
from typing import Any

from pydantic import EmailStr, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def flexible_json_loads(value: str) -> Any:
    """Gracefully fall back to raw strings when JSON decoding fails."""
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        json_loads=flexible_json_loads,
    )

    PROJECT_NAME: str = "Initiative API"
    API_V1_STR: str = "/api/v1"

    DATABASE_URL: str = "postgresql+asyncpg://initiative:initiative@localhost:5432/initiative"

    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    ALGORITHM: str = "HS256"

    AUTO_APPROVED_EMAIL_DOMAINS: list[str] = Field(default_factory=list)
    # APP_URL should point to the frontend entry so redirect URIs resolve correctly
    APP_URL: str = "http://localhost:5173"
    OIDC_ENABLED: bool = False
    OIDC_DISCOVERY_URL: str | None = None
    OIDC_CLIENT_ID: str | None = None
    OIDC_CLIENT_SECRET: str | None = None
    OIDC_REDIRECT_URI: str | None = None
    OIDC_POST_LOGIN_REDIRECT: str | None = None
    OIDC_PROVIDER_NAME: str | None = None
    OIDC_SCOPES: list[str] | str | None = None
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_SECURE: bool = False
    SMTP_REJECT_UNAUTHORIZED: bool = True
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM_ADDRESS: str | None = None
    SMTP_TEST_RECIPIENT: str | None = None

    UPLOADS_DIR: str = "uploads"

    FIRST_SUPERUSER_EMAIL: EmailStr | None = None
    FIRST_SUPERUSER_PASSWORD: str | None = None
    FIRST_SUPERUSER_FULL_NAME: str | None = None
    DISABLE_GUILD_CREATION: bool = False

    @field_validator("AUTO_APPROVED_EMAIL_DOMAINS", mode="before")
    @classmethod
    def parse_email_domains(cls, value: str | list[str] | None) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            if not value.strip():
                return []
            items = value.split(",")
        else:
            items = value
        return [item.strip().lower() for item in items if item and item.strip()]

    @field_validator("OIDC_SCOPES", mode="before")
    @classmethod
    def parse_oidc_scopes(cls, value: str | list[str] | None) -> list[str]:
        if value is None:
            return ["openid", "profile", "email"]
        if isinstance(value, str):
            if not value.strip():
                return ["openid", "profile", "email"]
            items = value.replace(",", " ").split()
        else:
            items = value
        normalized: list[str] = []
        for scope in items:
            cleaned = scope.strip()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized or ["openid", "profile", "email"]


@lru_cache
# Use caching to avoid re-reading the env file over and over
# (FastAPI startup imports Config many times).
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
