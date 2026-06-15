from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import EmailStr, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Origins used by the Capacitor native mobile app (iOS and Android).
# Must always be allowed regardless of CORS_ALLOWED_ORIGINS setting.
CAPACITOR_NATIVE_ORIGINS = [
    "https://com.morelitea.initiative",  # Capacitor custom hostname (Android + iOS with iosScheme=https)
    "capacitor://com.morelitea.initiative",  # Capacitor default iOS scheme with custom hostname
    "capacitor://localhost",  # Capacitor fallback (no custom hostname)
]

# Third-party origins the built SPA legitimately embeds in iframes, used to build
# the Content-Security-Policy (pentest MED-001). These are the document
# "smart link" providers available in the editor (always present).
CSP_EMBED_FRAME_ORIGINS = [
    "https://www.youtube-nocookie.com",
    "https://www.youtube.com",
    "https://www.figma.com",
    "https://www.loom.com",
    "https://player.vimeo.com",
    "https://docs.google.com",
    "https://miro.com",
    "https://airtable.com",
]

# Captcha providers → the extra origins each needs (script/frame/style/connect).
# Only the configured provider's origins are added; the gate is off by default.
CSP_CAPTCHA_ORIGINS = {
    "hcaptcha": ["https://hcaptcha.com", "https://*.hcaptcha.com"],
    "turnstile": ["https://challenges.cloudflare.com"],
    "recaptcha": ["https://www.google.com", "https://www.gstatic.com"],
}

# Origins the SPA fetches non-script assets from via fetch()/XHR, used to build
# the connect-src directive. The spell checker lazy-loads its English dictionary
# (.aff/.dic) from jsDelivr — see frontend/src/lib/spell-check.ts.
CSP_CONNECT_ORIGINS = [
    "https://cdn.jsdelivr.net",
]

# Origins the SPA loads web fonts from (font-src). The bundled Excalidraw
# whiteboard lazy-loads its .woff2 faces (Cascadia, Comic Shanns, Excalifont,
# etc.) from esm.sh at runtime.
CSP_FONT_ORIGINS = [
    "https://esm.sh",  # Do not promote esm.sh to script-src
]

# Swagger UI (/docs) pulls its bundle + stylesheet from jsDelivr and, behind a
# Cloudflare proxy, a Web Analytics beacon. These get a relaxed, docs-ONLY CSP
# (Settings.docs_content_security_policy) applied per-route so the app-wide
# script-src can stay 'self' (pentest MED-001) — never add these to the main CSP.
CSP_SWAGGER_SCRIPT_ORIGINS = [
    "https://cdn.jsdelivr.net",
    "https://static.cloudflareinsights.com",
]
CSP_SWAGGER_STYLE_ORIGINS = ["https://cdn.jsdelivr.net"]


def _format_csp(directives: dict[str, list[str]]) -> str:
    """Render a directive map to a CSP header string, de-duplicating sources."""
    return "; ".join(
        f"{name} {' '.join(dict.fromkeys(values))}"
        for name, values in directives.items()
    )


def _origin_of(url: str) -> str | None:
    """Return the ``scheme://host[:port]`` origin of a URL, or None if unparseable."""
    parts = urlsplit(url.strip())
    if parts.scheme and parts.netloc:
        return f"{parts.scheme}://{parts.netloc}"
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PROJECT_NAME: str = "Initiative API"
    API_V1_STR: str = "/api/v1"

    DATABASE_URL: str = (
        "postgresql+asyncpg://initiative:initiative@localhost:5432/initiative"
    )
    DATABASE_URL_APP: (
        str  # Non-superuser connection for RLS-enforced queries (required)
    )
    DATABASE_URL_ADMIN: str  # Admin connection with BYPASSRLS for migrations (required)

    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    ALGORITHM: str = "HS256"
    COOKIE_NAME: str = "session_token"

    @field_validator("SECRET_KEY")
    @classmethod
    def _validate_secret_key(cls, value: str) -> str:
        # SECRET_KEY signs session JWTs and the OIDC state HMAC, and roots all
        # Fernet field encryption (SMTP password, OIDC client secret, AI keys,
        # refresh tokens) plus the email_hash HMAC. A known placeholder or
        # short key makes every one of those forgeable/decryptable, so fail
        # closed at startup rather than booting with a guessable key.
        known_placeholders = {"change-me", "changeme", "super-secret-key", "secret"}
        normalized = value.strip()
        if not normalized or normalized.lower() in known_placeholders:
            raise ValueError(
                "SECRET_KEY is unset or a known placeholder. Generate a real "
                "key with: openssl rand -hex 32"
            )
        # Reject (rather than silently strip) surrounding whitespace: every
        # byte of this value feeds HMAC/Fernet key derivation, so quietly
        # normalizing it would rotate the effective key out from under a
        # deployment whose env var carried stray whitespace.
        if normalized != value:
            raise ValueError(
                "SECRET_KEY has leading or trailing whitespace. Remove it — "
                "the exact value is used for key derivation."
            )
        if len(normalized) < 32:
            raise ValueError(
                "SECRET_KEY must be at least 32 characters. Generate one "
                "with: openssl rand -hex 32"
            )
        return value

    @property
    def app_url_is_https(self) -> bool:
        """True when the public app origin is served over HTTPS.

        Drives both the ``Secure`` cookie flag and whether the
        ``Strict-Transport-Security`` header is emitted — HSTS over plain HTTP
        is meaningless and would needlessly pin a dev origin to HTTPS.
        """
        return urlsplit(self.APP_URL.strip()).scheme == "https"

    @property
    def cookie_secure(self) -> bool:
        return self.app_url_is_https

    AUTO_APPROVED_EMAIL_DOMAINS: list[str] = Field(default_factory=list)
    # APP_URL should point to the frontend entry so redirect URIs resolve correctly
    APP_URL: str = "http://localhost:5173"
    # Extra browser origins allowed to make credentialed cross-origin requests,
    # beyond APP_URL and the native app (both always allowed — see `cors_origins`).
    # A wildcard is intentionally unsupported.
    CORS_ALLOWED_ORIGINS: list[str] = Field(default_factory=list)

    @property
    def cors_origins(self) -> list[str]:
        """Effective CORS allowlist for credentialed requests — never ``*``.

        ``allow_origins=["*"]`` together with ``allow_credentials=True`` makes
        the server reflect any ``Origin`` and echo
        ``Access-Control-Allow-Credentials: true``, letting any website make
        authenticated cross-origin requests on a logged-in user's behalf
        (pentest CRIT-001). We therefore build an explicit allowlist: the app's
        own ``APP_URL`` and the native mobile origins are always included, plus
        whatever operators add via ``CORS_ALLOWED_ORIGINS``.

        Each value is reduced to its bare ``scheme://host[:port]`` origin: an
        ``Origin`` header never carries a path, so an ``APP_URL`` like
        ``https://host/app`` must match as ``https://host`` or every credentialed
        cross-origin request is silently rejected.
        """
        origins: list[str] = []
        for candidate in [
            self.APP_URL,
            *self.CORS_ALLOWED_ORIGINS,
            *CAPACITOR_NATIVE_ORIGINS,
        ]:
            origin = _origin_of(candidate) if candidate else None
            if origin and origin not in origins:
                origins.append(origin)
        return origins

    @property
    def content_security_policy(self) -> str:
        """Enforced CSP for the served SPA (pentest MED-001).

        Locks down the high-value vectors (``object-src``/``base-uri``/
        ``frame-ancestors``/``form-action``) and confines scripts to
        same-origin — scripts get NO ``'unsafe-inline'``/``'unsafe-eval'`` so
        injected markup can't execute. ``style-src`` does allow
        ``'unsafe-inline'`` because the charting component and some UI libraries
        inject inline ``<style>``. Origins the app genuinely loads (Google
        Fonts, document embeds, and — when configured — the captcha provider and
        advanced-tool iframe) are listed explicitly rather than via a blanket
        ``https:``.
        """
        ws = "wss:" if self.APP_URL.startswith("https") else "ws:"

        script_src = ["'self'"]
        style_src = ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"]
        font_src = ["'self'", "https://fonts.gstatic.com", "data:", *CSP_FONT_ORIGINS]
        img_src = ["'self'", "data:", "blob:", "https:"]
        connect_src = ["'self'", ws, *CSP_CONNECT_ORIGINS]
        frame_src = ["'self'", *CSP_EMBED_FRAME_ORIGINS]
        worker_src = ["'self'", "blob:"]

        provider = self.CAPTCHA_PROVIDER
        if provider in CSP_CAPTCHA_ORIGINS:
            extra = CSP_CAPTCHA_ORIGINS[provider]
            script_src += extra
            style_src += extra
            frame_src += extra
            connect_src += extra

        if self.ADVANCED_TOOL_URL:
            tool_origin = _origin_of(self.ADVANCED_TOOL_URL)
            if tool_origin:
                frame_src.append(tool_origin)
                connect_src.append(tool_origin)

        directives = {
            "default-src": ["'self'"],
            "script-src": script_src,
            "style-src": style_src,
            "font-src": font_src,
            "img-src": img_src,
            "connect-src": connect_src,
            "frame-src": frame_src,
            "worker-src": worker_src,
            "object-src": ["'none'"],
            "base-uri": ["'self'"],
            "form-action": ["'self'"],
            "frame-ancestors": ["'none'"],
        }
        return _format_csp(directives)

    @property
    def docs_content_security_policy(self) -> str:
        """Relaxed CSP for the Swagger ``/docs`` page ONLY (applied per-route).

        Swagger UI loads its bundle/stylesheet from jsDelivr and a Cloudflare
        beacon, which the app-wide ``script-src 'self'`` (pentest MED-001)
        rightly blocks. Rather than weaken the global policy, this scoped policy
        whitelists just those origins for the docs HTML response.

        ``script-src`` also needs ``'unsafe-inline'``: ``get_swagger_ui_html``
        boots the UI from an inline ``<script>`` (FastAPI provides no nonce, and
        a hash would break whenever the title/openapi_url change). ``connect-src``
        allows jsDelivr so the bundle's ``.map`` sourcemap fetch doesn't error;
        Try-It-Out still reaches the same-origin API via ``'self'``. This is
        confined to the dev-only, ``ENABLE_API_DOCS``-gated docs page — the rest
        of the app keeps ``script-src 'self'``, ``object-src 'none'``, and
        ``frame-ancestors 'none'``.
        """
        return _format_csp(
            {
                "default-src": ["'self'"],
                "script-src": [
                    "'self'",
                    "'unsafe-inline'",
                    *CSP_SWAGGER_SCRIPT_ORIGINS,
                ],
                "style-src": ["'self'", "'unsafe-inline'", *CSP_SWAGGER_STYLE_ORIGINS],
                "img-src": ["'self'", "data:", "https:"],
                "font-src": ["'self'", "data:"],
                "connect-src": ["'self'", *CSP_SWAGGER_STYLE_ORIGINS],
                "worker-src": ["'self'", "blob:"],
                "object-src": ["'none'"],
                "base-uri": ["'self'"],
                # form-action does not fall back to default-src (CSP L2+), so set
                # it explicitly to match the global policy's lockdown.
                "form-action": ["'self'"],
                "frame-ancestors": ["'none'"],
            }
        )

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
    FCM_APPLICATION_ID: str | None = (
        None  # Android: 1:123:android:abc, iOS: 1:123:ios:def
    )
    FCM_API_KEY: str | None = None  # Firebase API key (public, safe to expose)
    FCM_SENDER_ID: str | None = None  # FCM sender ID (numeric)
    FCM_SERVICE_ACCOUNT_JSON: str | None = (
        None  # Service account for backend sending (private)
    )

    UPLOADS_DIR: str = "uploads"
    STATIC_DIR: str = "static"

    FIRST_SUPERUSER_EMAIL: EmailStr | None = None
    FIRST_SUPERUSER_PASSWORD: str | None = None
    FIRST_SUPERUSER_FULL_NAME: str | None = None
    DISABLE_GUILD_CREATION: bool = False
    ENABLE_PUBLIC_REGISTRATION: bool = (
        True  # When False, requires invite code to register
    )

    # Prefix for per-guild Postgres ROLE names (not schemas). Roles are
    # cluster-global, so a test suite sharing a cluster with a seeded dev DB would
    # collide on guild_<id> roles. The suite sets this to "test_" so its roles
    # (test_guild_<id>) are distinct; schemas are per-database and stay unprefixed.
    GUILD_ROLE_PREFIX: str = ""

    # Privileged Access Management (PAM): time-bound, per-guild access grants.
    PAM_DEFAULT_DURATION_MINUTES: int = 240  # 4 hours
    PAM_MAX_DURATION_MINUTES: int = 1440  # 24 hours (absolute ceiling on any grant)
    # Per-role maximum grant duration (least privilege: lower-trust roles get
    # shorter windows). Each is clamped to PAM_MAX_DURATION_MINUTES.
    PAM_SUPPORT_MAX_MINUTES: int = 240  # 4 hours
    PAM_MODERATOR_MAX_MINUTES: int = 480  # 8 hours
    PAM_ADMIN_MAX_MINUTES: int = 1440  # 24 hours

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

    BEHIND_PROXY: bool = (
        False  # Set True when behind nginx/load balancer to trust X-Forwarded-For
    )

    # Global per-client default rate limit applied (via SlowAPIMiddleware) to
    # every route that lacks its own ``@limiter.limit(...)`` decorator. Uses the
    # slowapi/limits string syntax (e.g. ``"100/minute"``, or
    # ``"200/minute;2000/hour"`` for several windows). Set to an empty string to
    # turn the global default off entirely — per-route decorated limits still
    # apply. The test suite sets ``limiter.enabled = False`` so this never
    # throttles the hundreds of rapid requests a test makes from one client IP.
    RATE_LIMIT_DEFAULT: str = "100/minute"
    # Storage backend for rate-limit counters. Defaults to in-process memory
    # (``memory://``), which is per-worker — fine for a single process. For a
    # multi-worker / multi-replica deployment that needs a shared, accurate
    # counter, point this at Redis (``redis://host:6379/0``) or Memcached
    # (``memcached://host:11211``) WITHOUT any code change. See the slowapi /
    # limits "storage" docs for the full URI scheme list.
    RATE_LIMIT_STORAGE_URI: str = "memory://"

    # Absolute server-side ceiling on how many rows a single list request may
    # return when it asks for "all" (``page_size=0``/unbounded). Without this an
    # unauthenticated-by-count query could dump an entire guild's table in one
    # response (SEC-14). The "0 = all" convention is preserved for callers (the
    # SPA fetches all tasks for drag-and-drop, all documents for pickers) — the
    # result set is simply capped here. Raise it if a single guild legitimately
    # has more than this many tasks/documents on one board.
    MAX_UNBOUNDED_PAGE_SIZE: int = 1000

    # Expose the interactive API docs (Swagger UI at ``{API_V1_STR}/docs``) and
    # the raw OpenAPI schema (``{API_V1_STR}/openapi.json``). Defaults to True so
    # local development keeps its self-documenting API and the frontend's Orval
    # type generation against a running backend keeps working out of the box.
    # Operators SHOULD set this to ``False`` in production: the schema enumerates
    # every route, parameter, and error shape, handing an attacker a free map of
    # the attack surface (pentest SEC-16). The committed
    # ``frontend/openapi.json`` + ``scripts/export_openapi.py`` path means type
    # generation never needs a live ``/openapi.json`` in CI or prod.
    ENABLE_API_DOCS: bool = True

    # Reject passwords that appear in the HaveIBeenPwned breach corpus
    # when a user sets one (registration, reset, change). Uses the
    # k-anonymity API — only the first 5 hex chars of the SHA-1 hash
    # leave the server. Flip to ``False`` to disable the check (e.g.
    # in air-gapped deployments or when egress is blocked); the length
    # floor in ``app.core.password_policy`` still applies.
    HIBP_CHECK_ENABLED: bool = True

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
            return []
        if isinstance(value, str):
            items = value.split(",")
        else:
            items = value
        # Drop blanks and any "*": a wildcard combined with credentialed CORS is
        # the origin-reflection vuln (CRIT-001). APP_URL and the native origins
        # are always allowed via the `cors_origins` property, so the effective
        # allowlist is never empty even when this is.
        return [
            item.strip()
            for item in items
            if item and item.strip() and item.strip() != "*"
        ]

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
