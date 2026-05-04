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
    COOKIE_NAME: str = "session_token"

    @property
    def cookie_secure(self) -> bool:
        return self.APP_URL.startswith("https")

    AUTO_APPROVED_EMAIL_DOMAINS: list[str] = Field(default_factory=list)
    # APP_URL should point to the frontend entry so redirect URIs resolve correctly
    APP_URL: str = "http://localhost:5173"
    CORS_ALLOWED_ORIGINS: list[str] = Field(default_factory=lambda: ["*"])
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

    # Optional advanced tool plug-in: when ADVANCED_TOOL_URL is set, the SPA
    # surfaces a per-initiative toggle that, when enabled, embeds the URL as
    # an iframe sub-page under the initiative. Both unset on the default OSS
    # image — the toggle and panel are then fully hidden.
    ADVANCED_TOOL_NAME: str | None = None
    ADVANCED_TOOL_URL: str | None = None

    # Optional captcha gate on the public registration endpoint to push
    # back on bot signups. ``CAPTCHA_PROVIDER`` selects the vendor —
    # ``"hcaptcha"`` / ``"turnstile"`` / ``"recaptcha"`` — and the SPA
    # picks the matching widget at runtime via ``GET /api/v1/config``.
    # ``CAPTCHA_SITE_KEY`` is the public key embedded in the widget;
    # ``CAPTCHA_SECRET_KEY`` is the server-side key used to call the
    # provider's siteverify endpoint. When any of the three is unset
    # (or ``CAPTCHA_PROVIDER`` is unrecognised) the check is silently
    # disabled — registrations work as before, no error, no widget.
    # The bootstrap first-user path skips the gate regardless (no bot
    # economics before any users exist).
    CAPTCHA_PROVIDER: str | None = None
    CAPTCHA_SITE_KEY: str | None = None
    CAPTCHA_SECRET_KEY: str | None = None
    # Comma-separated origin allowlist for postMessage handoff to the
    # advanced tool iframe. The frontend only accepts messages from these
    # origins, and only sends messages to the iframe origin derived from
    # ADVANCED_TOOL_URL. Defaults to the ADVANCED_TOOL_URL origin if unset.
    ADVANCED_TOOL_ALLOWED_ORIGINS: list[str] | str | None = None

    # Optional asymmetric key material for signing advanced-tool handoff
    # JWTs with RS256 instead of HS256. When set, the proprietary embed
    # backend verifies tokens using the matching public key only — no
    # secret has to be shared between FOSS and the embed service. Falls
    # back to HS256 with SECRET_KEY when unset, so OSS deployments work
    # out of the box. Generate a 2048-bit RSA keypair with
    # ``openssl genrsa -out private.pem 2048`` and feed the PEM here.
    HANDOFF_SIGNING_PRIVATE_KEY_PEM: str | None = None
    # Key id stamped on the JWT header. The proprietary side reads ``kid``
    # to pick the right verifying key — useful when rotating.
    HANDOFF_SIGNING_KEY_ID: str | None = None

    # Inbound delegation from the advanced-tool service (initiative-auto).
    # When auto needs to call Initiative on behalf of a user — either
    # because the user is in the iframe right now, or because a workflow
    # they own is firing — it presents a JWT signed with RS256 by its
    # own private key. This is the matching public key. When unset,
    # delegation auth is disabled and Initiative only accepts its own
    # session tokens / API keys.
    AUTO_DELEGATION_PUBLIC_KEY_PEM: str | None = None
    AUTO_DELEGATION_AUDIENCE: str = "initiative:auto-delegation"
    AUTO_DELEGATION_ISSUER: str = "initiative-auto"

    # Local-dev escape hatch for the webhook SSRF guard. When TRUE, the
    # dispatcher accepts ``http://`` and private/loopback/link-local
    # targets — needed only for round-tripping with auto running on
    # ``http://localhost:9002`` where there's no TLS cert and the
    # address is non-public by definition. Default FALSE; production
    # deployments MUST NOT enable this — plain http lets a MITM strip
    # the signature header and forge payloads.
    WEBHOOK_ALLOW_PRIVATE_TARGETS: bool = False

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

    @field_validator("CORS_ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_cors_allowed_origins(cls, value: str | list[str] | None) -> list[str]:
        if value is None:
            return ["*"]
        if isinstance(value, str):
            if not value.strip():
                return ["*"]
            items = value.split(",")
        else:
            items = value
        return [item.strip() for item in items if item and item.strip()] or ["*"]

    @field_validator("ADVANCED_TOOL_ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_advanced_tool_origins(cls, value: str | list[str] | None) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            if not value.strip():
                return []
            items = value.split(",")
        else:
            items = value
        return [item.strip() for item in items if item and item.strip()]

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
