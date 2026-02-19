from functools import lru_cache

from pydantic import EmailStr, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PROJECT_NAME: str = "Initiative API"
    API_V1_STR: str = "/api/v1"

    DATABASE_URL: str = "postgresql+asyncpg://initiative:initiative@localhost:5432/initiative"
    DATABASE_URL_APP: str  # Non-superuser connection for RLS-enforced queries (required)
    DATABASE_URL_ADMIN: str  # Admin connection with BYPASSRLS for migrations (required)

    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    ALGORITHM: str = "HS256"

    AUTO_APPROVED_EMAIL_DOMAINS: list[str] = Field(default_factory=list)
    # APP_URL should point to the frontend entry so redirect URIs resolve correctly
    APP_URL: str = "http://localhost:5173"
    OIDC_ENABLED: bool = False
    OIDC_ISSUER: str | None = None
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

    # FCM Push Notifications
    FCM_ENABLED: bool = False
    FCM_PROJECT_ID: str | None = None
    FCM_APPLICATION_ID: str | None = None  # Android: 1:123:android:abc, iOS: 1:123:ios:def
    FCM_API_KEY: str | None = None  # Firebase API key (public, safe to expose)
    FCM_SENDER_ID: str | None = None  # FCM sender ID (numeric)
    FCM_SERVICE_ACCOUNT_JSON: str | None = None  # Service account for backend sending (private)

    UPLOADS_DIR: str = "uploads"
    STATIC_DIR: str = "static"

    FIRST_SUPERUSER_EMAIL: EmailStr | None = None
    FIRST_SUPERUSER_PASSWORD: str | None = None
    FIRST_SUPERUSER_FULL_NAME: str | None = None
    DISABLE_GUILD_CREATION: bool = False
    ENABLE_PUBLIC_REGISTRATION: bool = True  # When False, requires invite code to register
    BEHIND_PROXY: bool = False  # Set True when behind nginx/load balancer to trust X-Forwarded-For

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
            return ["openid", "profile", "email", "offline_access"]
        if isinstance(value, str):
            if not value.strip():
                return ["openid", "profile", "email", "offline_access"]
            items = value.replace(",", " ").split()
        else:
            items = value
        normalized: list[str] = []
        for scope in items:
            cleaned = scope.strip()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized or ["openid", "profile", "email"]

    @model_validator(mode="before")
    @classmethod
    def _oidc_issuer_compat(cls, values: dict) -> dict:
        if not values.get("OIDC_ISSUER") and values.get("OIDC_DISCOVERY_URL"):
            values["OIDC_ISSUER"] = values["OIDC_DISCOVERY_URL"]
        return values


@lru_cache
# Use caching to avoid re-reading the env file over and over
# (FastAPI startup imports Config many times).
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
