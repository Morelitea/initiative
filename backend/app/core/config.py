import hashlib
import hmac
import logging
import re
from collections.abc import Sequence
from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import (
    AliasChoices,
    EmailStr,
    Field,
    PrivateAttr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


# App identity/shape — deliberately constants, not settings: the SPA, the
# docs-CSP route, and the OpenAPI export all assume this prefix, so making it
# configurable only creates ways to break them.
PROJECT_NAME = "Initiative API"
API_V1_STR = "/api/v1"

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


# How an operator safely changes the encryption root. Appended to SECRET_KEY
# validation failures (rotation_hint=True) so the boot-crash message points at the
# rotation path instead of inviting the destructive "just generate a new one" fix.
# It must travel in the ValueError text itself: pydantic validators run at settings
# load, before logging is configured, so there's nowhere else for it to surface.
_SECRET_KEY_ROTATION_HINT = (
    " To CHANGE SECRET_KEY on an existing deployment, do NOT swap it directly — it "
    "encrypts stored data (emails, OIDC/SMTP/AI secrets) and roots email lookup, so a "
    "bare swap locks out every user and orphans those secrets. Instead set the old "
    "value as PREVIOUS_SECRET_KEY, set SECRET_KEY to the new key, and restart — the "
    "server re-encrypts the stored data automatically on startup. Once the logs report "
    "the rotation is complete, UNSET PREVIOUS_SECRET_KEY. (Advanced: you can instead "
    "run `python -m app.db.secret_key_rotation` from the backend/ directory to rotate "
    "out-of-band, but a restart is all that's required.)"
)


def _validate_strong_key(value: str, var_name: str, *, rotation_hint: bool) -> str:
    """Enforce the shared strength rules for SECRET_KEY / JWT_SIGNING_KEY: non-empty,
    not a known placeholder, no surrounding whitespace, >= 32 chars. ``rotation_hint``
    appends the safe-change instructions for keys that encrypt stored data."""
    hint = _SECRET_KEY_ROTATION_HINT if rotation_hint else ""
    known_placeholders = {"change-me", "changeme", "super-secret-key", "secret"}
    normalized = value.strip()
    if not normalized or normalized.lower() in known_placeholders:
        raise ValueError(
            f"{var_name} is unset or a known placeholder. Generate a real key "
            f"with: openssl rand -hex 32{hint}"
        )
    # Reject (rather than silently strip) surrounding whitespace: every byte of this
    # value feeds HMAC/Fernet key derivation, so quietly normalizing it would rotate
    # the effective key out from under a deployment whose env var carried whitespace.
    if normalized != value:
        raise ValueError(
            f"{var_name} has leading or trailing whitespace. Remove it — the exact "
            f"value is used for key derivation.{hint}"
        )
    if len(normalized) < 32:
        raise ValueError(
            f"{var_name} must be at least 32 characters. Generate one with: "
            f"openssl rand -hex 32{hint}"
        )
    return value


#: Settings whose environment variable is only a FIRST-BOOT SEED.
#:
#: Each of these is stored in the database on first start and edited in
#: Settings → Platform from then on, so the env var is read once and the row wins
#: afterwards. ``app/services/platform/app_settings.py`` (``_seed_from_env``) is
#: the mechanism; the credential-bearing ones are encrypted at rest under a salt
#: registered in ``app/db/secret_key_rotation.py``, so they rotate with
#: SECRET_KEY.
#:
#: Declared here so the deployment contract can say so out loud: an operator
#: does not need any of these to bring the app up, and a deployment tool does
#: not need to carry them as deploy-time secrets. See ``env-contract.json``.
RUNTIME_SEEDED_SETTINGS = frozenset(
    {
        # Outbound mail.
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_SECURE",
        "SMTP_REJECT_UNAUTHORIZED",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_FROM_ADDRESS",
        "SMTP_TEST_RECIPIENT",
        # Object storage.
        "STORAGE_BACKEND",
        "S3_BUCKET",
        "S3_REGION",
        "S3_ENDPOINT_URL",
        "S3_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY",
        "S3_USE_PATH_STYLE",
        "S3_KMS_KEY_ID",
        "S3_LOCAL_FALLBACK",
        # The platform OIDC provider. Seeded into the provider row by
        # app/services/auth/platform_provider.py; after that the row holds the
        # secret, which is why rotating it upstream needs a paste in Settings.
        "OIDC_ENABLED",
        "OIDC_ISSUER",
        "OIDC_CLIENT_ID",
        "OIDC_CLIENT_SECRET",
        "OIDC_PROVIDER_NAME",
        "OIDC_SCOPES",
        # The registration captcha (0368). Provider and site key are public;
        # the verification secret is encrypted on app_setting_secrets.
        "CAPTCHA_PROVIDER",
        "CAPTCHA_SITE_KEY",
        "CAPTCHA_SECRET_KEY",
        # Push notifications (0368). Everything but the service-account JSON
        # reaches a device or a page; that one is encrypted at rest.
        "FCM_ENABLED",
        "FCM_PROJECT_ID",
        "FCM_APPLICATION_ID",
        "FCM_API_KEY",
        "FCM_SENDER_ID",
        "FCM_SERVICE_ACCOUNT_JSON",
    }
)

#: Operator-supplied credentials with no database path, and so no way to set
#: them after deployment. The environment would be the only place they could
#: live, which makes them the only reason a deployment tool needs a free-form
#: secret passthrough.
#:
#: **Empty since 0368**, when the captcha secret and the FCM service account --
#: the last two -- moved onto the settings singleton. Kept rather than deleted
#: because it is a claim worth being able to check: anything added here is a
#: setting an operator can never change without a redeploy, and a deployment
#: tool has to carry it as a secret. Prefer the seeded set above.
ENV_ONLY_FEATURE_CREDENTIALS: frozenset[str] = frozenset()

#: The app's three logins: the setting whose URL connects as each, and the
#: login's canonical name — what the app calls it when it makes the login
#: itself, and what a URL naming no user is read as.
DATABASE_LOGINS: tuple[tuple[str, str], ...] = (
    ("DATABASE_URL", "app_provisioner"),
    ("DATABASE_URL_APP", "app_user"),
    ("DATABASE_URL_ADMIN", "app_admin"),
)


def derive_database_password(secret_key: str, role: str) -> str:
    """The password a derived login is given: one per role, from SECRET_KEY.

    The bootstrap sets it on every start, so it follows SECRET_KEY through a
    rotation without anything else to change.
    """
    return hmac.new(
        secret_key.encode(), b"database-login:" + role.encode(), hashlib.sha256
    ).hexdigest()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # The database, in one of two shapes.
    #
    # Usually the database owner, with DATABASE_URL_APP and DATABASE_URL_ADMIN
    # left unset. The app then makes its three logins itself (see
    # DATABASE_LOGINS), with passwords derived from SECRET_KEY, and
    # `_resolve_database_logins` rewrites these four settings into the second
    # shape, so nothing that reads them needs to know which one was given.
    #
    # Or the app_provisioner login, with DATABASE_URL_APP (app_user, the request
    # path) and DATABASE_URL_ADMIN (app_admin, the system engine) set beside it,
    # for a deployment that names its logins and passwords itself.
    DATABASE_URL: str = (
        "postgresql+asyncpg://initiative:initiative@localhost:5432/initiative"
    )
    DATABASE_URL_APP: str = ""
    DATABASE_URL_ADMIN: str = ""
    # The database owner, used once at startup to apply the prerequisites the
    # three logins above cannot create for themselves: the logins themselves,
    # and the guild-search match operator (see app.db.bootstrap). The
    # connection is opened, used and disposed before the app serves anything.
    # Unset it and the app verifies those prerequisites instead of applying
    # them; a deployment that provisions its database out of band never sets it.
    # Only set it beside DATABASE_URL_APP and DATABASE_URL_ADMIN: otherwise
    # DATABASE_URL is already the owner, and this is filled in from it.
    DATABASE_URL_BOOTSTRAP: str | None = None
    # Where to hold the realtime signal channel's own connection. ``LISTEN`` is
    # session state and so wants a connection of its own, apart from the pooled
    # engines above. Unset (the common case) it uses ``DATABASE_URL``; set it
    # where the app reaches Postgres through something that pools per
    # transaction, which cannot hold a subscription open.
    DATABASE_URL_LISTEN: str | None = None
    # Where reads that may trail the primary by a moment go: dashboard widgets'
    # SQL and export renders. Point it at a read replica. It connects as the
    # same login as DATABASE_URL_APP; when DATABASE_URL names the owner, give
    # only the host and database and the app fills in that login. Unset, those
    # reads use DATABASE_URL_APP.
    DATABASE_URL_QUERY: str | None = None
    # How long a pooled connection may live before it is retired and replaced.
    #
    # A backend permanently caches catalog entries for every table it touches
    # and Postgres never shrinks CacheMemoryContext, so under schema-per-guild
    # a long-lived connection's private memory grows with the number of guild
    # schemas it has served. Only closing it gives that back. Postgres-side
    # idle timeouts do not reach these: a pooled connection is handed out
    # again long before it has been idle long enough to trip one, so age is
    # the only bound that actually applies. 0 disables recycling.
    DB_POOL_RECYCLE_SECONDS: int = 1800
    # Connections each request and system pool keeps open, and how many more it
    # may open under load. With DB_COHORTS above 1 these size every cohort's
    # request pool, not their total.
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    # How many groups ("cohorts") communities are divided into. Each cohort has
    # a request pool of its own, and a connection only ever serves its own
    # cohort's communities, so the catalog each database connection caches is
    # a K-th of the whole. 1 is one shared pool.
    DB_COHORTS: int = 1
    # The database name each cohort's connections ask for, with ``{cohort}``
    # standing for its number: ``initiative_c{cohort}`` behind a pooler that
    # gives each cohort an alias of its own. Unset, every cohort connects to
    # the database DATABASE_URL_APP names.
    DB_COHORT_DATABASE: str | None = None

    SECRET_KEY: str
    # Optional: the *previous* SECRET_KEY, set only while rotating the encryption
    # root. Read verbatim (NO validation/normalization) so it reproduces the old
    # effective key exactly — it may be the weak/whitespaced key being escaped, and
    # the legacy code never stripped it. Consumed by app.db.secret_key_rotation;
    # remove it once the rotation has run.
    PREVIOUS_SECRET_KEY: str | None = None
    # Optional: dedicated JWT signing key. When set, session/upload/handoff JWTs are
    # signed and verified with this instead of SECRET_KEY (see ``jwt_signing_key``),
    # so it can be rotated freely — the only cost is forcing every user to re-login,
    # with no impact on encrypted-at-rest data. Falls back to SECRET_KEY when unset.
    JWT_SIGNING_KEY: str | None = None

    # The JWT algorithm and cookie names are constants in app.core.security
    # (JWT_ALGORITHM, SESSION_COOKIE_NAME, REFRESH_COOKIE_NAME) — a settable
    # JWT algorithm is an alg-confusion hazard, and the cookie names are part
    # of the auth contract, not deployment configuration.

    # New login model (auth rewrite, Phase 0 — history/auth-detailed-design.md §3).
    # The access token is short-lived + stateless: verified locally with no
    # per-request DB read (the 10k+ win), so a leak is stale within one TTL. The
    # refresh token is long, opaque, rotating, and revocable via ``auth_sessions``.
    #
    # Together these are how long somebody stays signed in: the browser renews
    # silently every AUTH_ACCESS_TTL_MINUTES and keeps the session for
    # AUTH_REFRESH_TTL_DAYS of not using the app. They are the whole of that
    # setting now — they replaced ``ACCESS_TOKEN_EXPIRE_MINUTES``, which is
    # gone.
    AUTH_ACCESS_TTL_MINUTES: int = 15
    AUTH_REFRESH_TTL_DAYS: int = 30

    @field_validator("DB_COHORTS", "DB_POOL_SIZE")
    @classmethod
    def _at_least_one(cls, value: int) -> int:
        if value < 1:
            raise ValueError("must be at least 1")
        return value

    @field_validator("DB_MAX_OVERFLOW")
    @classmethod
    def _not_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("must not be negative")
        return value

    @field_validator("DB_COHORT_DATABASE")
    @classmethod
    def _names_the_cohort(cls, value: str | None) -> str | None:
        if not value:
            return None
        if "{cohort}" not in value:
            raise ValueError(
                "DB_COHORT_DATABASE must contain {cohort}, which stands for the "
                "cohort's number"
            )
        try:
            value.format(cohort=0)
        except (KeyError, IndexError, ValueError) as exc:
            raise ValueError(
                "DB_COHORT_DATABASE may contain {cohort} and nothing else in braces"
            ) from exc
        return value

    @field_validator("SECRET_KEY")
    @classmethod
    def _validate_secret_key(cls, value: str) -> str:
        # SECRET_KEY signs the OIDC state HMAC and roots all Fernet field encryption
        # (SMTP password, OIDC client secret, AI keys, refresh tokens) plus the
        # email_hash HMAC. A known placeholder or short key makes every one of those
        # forgeable/decryptable, so fail closed at startup rather than booting with a
        # guessable key. The hint points at the safe rotation path because the naive
        # fix — "just set a new key" — silently orphans all encrypted data.
        return _validate_strong_key(value, "SECRET_KEY", rotation_hint=True)

    @field_validator("JWT_SIGNING_KEY")
    @classmethod
    def _validate_jwt_signing_key(cls, value: str | None) -> str | None:
        # Optional, but when present it signs JWTs, so hold it to the same strength
        # bar as SECRET_KEY. No rotation hint: rotating it only forces re-login, so a
        # bare swap is the correct fix.
        if value is None:
            return None
        return _validate_strong_key(value, "JWT_SIGNING_KEY", rotation_hint=False)

    @field_validator("GUILD_ROLE_PREFIX", "PLATFORM_ROLE_PREFIX")
    @classmethod
    def _validate_role_prefix(cls, value: str) -> str:
        # These prefixes are interpolated into Postgres ROLE-name DDL and into
        # every request's SET ROLE. Pin them to an unquoted-identifier-safe
        # shape once at load time (fail closed) so no name-builder or migration
        # has to re-check: empty (the production default), or a leading letter/
        # underscore followed by letters, digits, and underscores. A
        # digit-leading prefix would yield a role name Postgres rejects.
        if value and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError(
                "must be empty or start with a letter or underscore and contain "
                "only ASCII letters, digits, and underscores (it becomes part of "
                "Postgres role names)"
            )
        return value

    _database_logins_derived: bool = PrivateAttr(default=False)

    @model_validator(mode="after")
    def _resolve_database_logins(self) -> "Settings":
        has_app, has_admin = bool(self.DATABASE_URL_APP), bool(self.DATABASE_URL_ADMIN)
        if has_app != has_admin:
            given, missing = (
                ("DATABASE_URL_APP", "DATABASE_URL_ADMIN")
                if has_app
                else ("DATABASE_URL_ADMIN", "DATABASE_URL_APP")
            )
            raise ValueError(
                f"{given} is set but {missing} is not. Set both, with DATABASE_URL "
                f"as app_provisioner, to name the app's logins yourself; or set "
                f"neither, with DATABASE_URL as the database owner, and the app "
                f"makes them."
            )
        if has_app:
            self._check_query_login()
            return self
        if self.DATABASE_URL_BOOTSTRAP:
            raise ValueError(
                "DATABASE_URL_BOOTSTRAP is set without DATABASE_URL_APP and "
                "DATABASE_URL_ADMIN. Without those two, DATABASE_URL is the "
                "database owner and the app makes its own logins, so remove "
                "DATABASE_URL_BOOTSTRAP. To name the logins yourself instead, set "
                "DATABASE_URL (as app_provisioner), DATABASE_URL_APP and "
                "DATABASE_URL_ADMIN."
            )
        owner = make_url(self.DATABASE_URL)
        self.DATABASE_URL_BOOTSTRAP = self.DATABASE_URL
        for setting, role in DATABASE_LOGINS:
            login = owner.set(
                username=role,
                password=derive_database_password(self.SECRET_KEY, role),
            )
            setattr(self, setting, login.render_as_string(hide_password=False))
        if self.DATABASE_URL_QUERY:
            request_login = make_url(self.DATABASE_URL_APP)
            self.DATABASE_URL_QUERY = (
                make_url(self.DATABASE_URL_QUERY)
                .set(username=request_login.username, password=request_login.password)
                .render_as_string(hide_password=False)
            )
        self._database_logins_derived = True
        return self

    def _check_query_login(self) -> None:
        """DATABASE_URL_QUERY connects as DATABASE_URL_APP's login, the one
        the query roles are granted to."""
        if not self.DATABASE_URL_QUERY:
            return
        query_login = make_url(self.DATABASE_URL_QUERY).username
        request_login = make_url(self.DATABASE_URL_APP).username
        if query_login != request_login:
            raise ValueError(
                f"DATABASE_URL_QUERY connects as {query_login!r}, but it must use "
                f"the same login as DATABASE_URL_APP ({request_login!r})."
            )

    @property
    def database_logins_derived(self) -> bool:
        """Whether DATABASE_URL named the owner and the app made its logins."""
        return self._database_logins_derived

    def database_login(self, setting: str) -> tuple[str, str | None]:
        """The (name, password) one of the DATABASE_LOGINS settings connects as.

        A deployment may name its logins anything; this is the name its URL
        gives, or the canonical one when the URL gives none.
        """
        canonical = dict(DATABASE_LOGINS)[setting]
        try:
            url = make_url(getattr(self, setting))
        except ArgumentError:
            return canonical, None
        return url.username or canonical, url.password or None

    @property
    def jwt_signing_key(self) -> str:
        """Key used to sign/verify JWTs. Prefers the dedicated JWT_SIGNING_KEY so it
        can be rotated without touching encrypted-at-rest data; falls back to
        SECRET_KEY for deployments that haven't set one."""
        return self.JWT_SIGNING_KEY or self.SECRET_KEY

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
        """Enforced CSP for the served SPA (pentest MED-001), with the env's
        captcha provider -- what a process that has not read its settings row
        yet serves."""
        return self.content_security_policy_with_frames(
            (), captcha_provider=self.CAPTCHA_PROVIDER
        )

    def content_security_policy_with_frames(
        self, app_frame_origins: Sequence[str], *, captcha_provider: str | None
    ) -> str:
        """The app-wide CSP, optionally admitting the registered frame origins.

        Locks down the high-value vectors (``object-src``/``base-uri``/
        ``frame-ancestors``/``form-action``) and confines scripts to
        same-origin — scripts get NO ``'unsafe-inline'``/``'unsafe-eval'`` so
        injected markup can't execute. ``style-src`` does allow
        ``'unsafe-inline'`` because the charting component and some UI libraries
        inject inline ``<style>``. Origins the app genuinely loads (Google
        Fonts, document embeds, and — when configured — the captcha provider and
        app embeds) are listed explicitly rather than via a blanket
        ``https:``.

        ``app_frame_origins`` is how a marketplace app's embedded surface gets
        framed. It holds the origins of the app services this deployment has
        registered — the operator's trusted-site list, passed in by
        ``app.api.embed_csp`` on the documents where ``frame-src`` applies, and
        empty here so the app-wide default names none. ``connect-src`` is
        untouched: an app's data reaches the browser same-origin through the
        proxy.
        """
        ws = "wss:" if self.APP_URL.startswith("https") else "ws:"

        script_src = ["'self'"]
        style_src = ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"]
        font_src = ["'self'", "https://fonts.gstatic.com", "data:", *CSP_FONT_ORIGINS]
        img_src = ["'self'", "data:", "blob:", "https:"]
        connect_src = ["'self'", ws, *CSP_CONNECT_ORIGINS]
        frame_src = ["'self'", *CSP_EMBED_FRAME_ORIGINS]
        worker_src = ["'self'", "blob:"]

        if captcha_provider in CSP_CAPTCHA_ORIGINS:
            extra = CSP_CAPTCHA_ORIGINS[captcha_provider]
            script_src += extra
            style_src += extra
            frame_src += extra
            connect_src += extra

        # The landing page reads the public pricing catalog straight from the
        # billing portal, so its origin joins connect-src only on a deployment
        # that has one. Reduced to an origin the same way as the app frames.
        billing_origin = _origin_of(self.BILLING_URL) if self.BILLING_URL else None
        if billing_origin:
            connect_src.append(billing_origin)

        # Only the surface being opened. Already canonical origins by the time
        # they are stored on a registration, and re-reduced here so a value that
        # somehow carried a path cannot widen the directive.
        for candidate in app_frame_origins:
            origin = _origin_of(candidate) if candidate else None
            if origin:
                frame_src.append(origin)

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
    def wasm_worker_content_security_policy(self) -> str:
        """CSP for the WebAssembly worker bundles ONLY (applied per-response).

        Three workers run WebAssembly: the dashboard widget sandbox, which
        evaluates widget code with QuickJS
        (``frontend/src/lib/widgets/runtime/sandbox.worker.ts``); the direct
        message ratchet, which runs vodozemac
        (``frontend/src/crypto/ratchet.worker.ts``); and the PDF viewer's pdf.js
        worker, which decodes JBIG2, CCITT fax and JPEG 2000 images that way.
        A worker takes its policy from the response that served its script
        rather than from the document that started it, so the WebAssembly source
        expression is named here — on those built assets — and the app-wide
        policy above needs no mention of it.

        Each worker is given the three things it uses and nothing else: its own
        script, WebAssembly compilation, and a same-origin fetch for the
        ``.wasm`` file. None has a DOM, loads styles, images, or fonts, or
        talks to anybody but the page that started it.
        """
        return _format_csp(
            {
                "default-src": ["'none'"],
                "script-src": ["'self'", "'wasm-unsafe-eval'"],
                "connect-src": ["'self'"],
            }
        )

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
    OIDC_PROVIDER_NAME: str | None = None
    OIDC_SCOPES: list[str] | str | None = None
    # Which ways in the deployment permits, seeded into ``app_settings`` on
    # the first boot only — the same rule as the OIDC_* five above, and the
    # same owner afterwards: Settings -> Platform -> Authentication, which the
    # env never overwrites. Comma- or space-separated values of
    # ``app.core.login_methods.LoginMethod``; unset keeps the app's default.
    AUTH_LOGIN_METHODS: list[str] | str | None = None
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
    # Blob storage backend. "local" = filesystem under UPLOADS_DIR (FOSS/self-host/
    # dev default). "s3" = any S3-compatible object store (a self-hosted Garage
    # instance, AWS S3, R2, etc.) — see the S3_* settings below.
    STORAGE_BACKEND: str = "local"
    # --- S3 / S3-compatible object storage (only used when STORAGE_BACKEND="s3") ---
    # Point at your own object store (e.g. a self-hosted Garage instance): set
    # S3_BUCKET + S3_ENDPOINT_URL + S3_REGION, S3_USE_PATH_STYLE=true (Garage and
    # most non-AWS stores), and the access/secret keys (or leave them unset to use
    # the ambient credential chain). See docs/en/running-a-server/object-storage.md.
    S3_BUCKET: str | None = None
    S3_REGION: str = "us-east-1"
    S3_ENDPOINT_URL: str | None = None
    S3_ACCESS_KEY_ID: str | None = None
    S3_SECRET_ACCESS_KEY: str | None = None
    S3_USE_PATH_STYLE: bool = False
    S3_KMS_KEY_ID: str | None = None
    # Migration safety net: while cutting a deployment over from "local" to "s3",
    # set true so a read that misses in S3 falls back to the local filesystem
    # (serves blobs not yet copied by the backfill). Turn off once the backfill is
    # verified complete. Only consulted when STORAGE_BACKEND="s3".
    S3_LOCAL_FALLBACK: bool = False

    # --- Marketplace ------------------------------------------------------
    # A directory of listing manifests (*.json) this deployment publishes as
    # its own. Mount a volume, drop files in, and they appear in the
    # marketplace alongside the ones this build ships — publishing needs no
    # change to the application. Scanned at boot and on demand from
    # Settings → Platform; a file that is removed retires its listing.
    # Unset (the default) means no directory is read and nothing is published
    # beyond the built-ins.
    MARKETPLACE_EXTRA_CATALOG_DIR: str | None = None

    # --- Data export engine ---
    # The engine's own row, job and byte bounds are constants in
    # ``app.services.export.limits``; these are the deployment's choices.
    #
    # The line between an archive the app hands back over HTTP and one it
    # writes to the operator's destination. A download is served by this
    # process for as long as the client's connection lasts, so this is a bound
    # on how long one request may hold a worker, not on anything about size in
    # itself. Past it the archive is delivered instead.
    EXPORT_MAX_DOWNLOAD_BYTES: int = 2_147_483_648  # 2 GiB
    # Where a delivered archive is written: an absolute directory on this
    # host, which may be any mount the operator can write to. Unset (the
    # default) means delivery is not configured, and an archive over the
    # download bound is refused rather than produced with nowhere to go.
    EXPORT_DESTINATION_DIR: str | None = None
    # How long a community must wait between whole-community exports. The one
    # control that actually bounds what this costs a deployment: a community's
    # entire content is not a thing to re-read on a loop.
    EXPORT_GUILD_COOLDOWN_HOURS: int = 48
    # Hand a finished export's download off to the object store: the endpoint
    # redirects to a signed URL and the bytes travel from the store to the
    # client instead of through this process for the whole download.
    #
    # Off by default, and opt-in rather than automatic, because the browser
    # fetches the download with XHR: the bucket has to allow this app's origin
    # in its CORS rules for the redirected request to be readable. A
    # deployment that has not set that up would see downloads start failing
    # the moment it switched storage over. Filesystem storage signs nothing,
    # so this does nothing there whatever it is set to.
    EXPORT_PRESIGNED_DOWNLOADS: bool = False
    # First/bootstrap user — becomes the platform `owner` tier (there is no
    # superuser concept). The legacy FIRST_SUPERUSER_* env names are accepted
    # as aliases so existing deployments keep working.
    FIRST_OWNER_EMAIL: EmailStr | None = Field(
        default=None,
        validation_alias=AliasChoices("FIRST_OWNER_EMAIL", "FIRST_SUPERUSER_EMAIL"),
    )
    FIRST_OWNER_PASSWORD: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "FIRST_OWNER_PASSWORD", "FIRST_SUPERUSER_PASSWORD"
        ),
    )
    FIRST_OWNER_FULL_NAME: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "FIRST_OWNER_FULL_NAME", "FIRST_SUPERUSER_FULL_NAME"
        ),
    )
    DISABLE_GUILD_CREATION: bool = False
    # Boot back-fill normally skips guild schemas stamped with the current
    # provisioning-artifact version; set true to force a full sweep once.
    FORCE_GUILD_BACKFILL: bool = False
    ENABLE_PUBLIC_REGISTRATION: bool = (
        True  # When False, requires invite code to register
    )

    # Prefix for per-guild Postgres ROLE names (not schemas). Roles are
    # cluster-global, so a test suite sharing a cluster with a seeded dev DB would
    # collide on guild_<id> roles. The suite sets this to "test_" so its roles
    # (test_guild_<id>) are distinct; schemas are per-database and stay unprefixed.
    GUILD_ROLE_PREFIX: str = ""

    # Prefix for the platform-ladder Postgres ROLE names (platform_member …
    # platform_owner + platform_base). Like the guild roles these are
    # cluster-global, so the suite sets this to "test_" (test_platform_<tier>) to
    # avoid colliding with a co-located dev DB's unprefixed platform roles. The
    # creating migration and the routing role-name helper read the SAME setting,
    # so a SET ROLE always targets the role the migration actually created.
    PLATFORM_ROLE_PREFIX: str = ""

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
    # RSA private key (PEM) for signing handoff JWTs. Handoff tokens cross a
    # trust boundary — the receiving service verifies them with the matching
    # public key — so signing is always RS256 and no secret is shared across
    # that boundary. Required by whichever handoff a deployment uses: unset,
    # those mint endpoints fail closed (503).
    # Generate a 2048-bit keypair with ``openssl genrsa -out private.pem 2048``
    # and feed the PEM here.
    HANDOFF_SIGNING_PRIVATE_KEY_PEM: str | None = None
    # Key id stamped on the JWT header. The proprietary side reads ``kid``
    # to pick the right verifying key — useful when rotating.
    HANDOFF_SIGNING_KEY_ID: str | None = None

    # --- App platform (external app services; default OFF) ----------------
    # An app service is an external container this deployment has wired up
    # (see the app service registry). Everything below is unset on a default
    # install, and with it unset the platform simply has no app services: the
    # registry lists nothing, and the endpoints that would mint credentials for
    # one fail closed rather than improvising.
    #
    # RSA private key (PEM) signing Initiative -> app context JWTs. This is a
    # DEDICATED keypair with no fallback: an app verifies these against the
    # published public half, so borrowing another service's key would put two
    # unrelated trust boundaries on one rotation schedule. Generate one with
    # ``openssl genrsa -out app-platform.pem 2048``. Unset ⇒ registering and
    # verifying app services refuse with APP_SERVICE_SIGNING_NOT_CONFIGURED.
    APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM: str | None = None
    # Key id stamped on the JWT header so an app can pick the right verifying
    # key out of the published JWKS while a rotation is in flight.
    APP_PLATFORM_SIGNING_KEY_ID: str | None = None
    # Path to a mounted file of app service registrations, reconciled into the
    # database at startup so a chart can wire approved apps with no owner
    # clicks. JSON (or a JSON array in a .json file):
    #   [{"public_id": "acme.shopify", "base_url": "http://shopify:9100",
    #     "embed_origin": "https://shopify.example.com",
    #     "secret_env": "SHOPIFY_APP_SECRET", "allowed_origins": ["…"],
    #     "grants": [], "mandatory": false}]
    # ``base_url`` is where this deployment's server calls the app, so it may be
    # an address only the cluster resolves; ``embed_origin`` is where a browser
    # loads its iframes and connection pages, and is omitted when the app
    # answers both at one address.
    # The secret is named, never inlined, so the file can be a plain ConfigMap.
    # Unset (the default) ⇒ no reconciliation runs. Reconciliation never
    # re-enables a registration an operator disabled, and never blocks boot.
    APP_SERVICES_CONFIG: str | None = None
    # How often enabled registrations are re-verified in the background, so an
    # app that went away (or changed what it claims) is marked rather than
    # discovered by a member clicking it. 0 turns the sweep off; it also does
    # not run at all without the signing keypair, since the app platform is
    # inert without one.
    APP_SERVICE_VERIFY_INTERVAL_SECONDS: int = Field(default=3600, ge=0)

    # --- Billing (hosted deployments only; default OFF) -------------------
    # Billing is an optional EXTERNAL service. Every BILLING_* setting below
    # is unset on a self-hosted install, and with them unset the app behaves
    # exactly as if billing did not exist: the /billing endpoints answer 503,
    # the membership ping is a no-op, and guild caps/status are governed
    # solely by what the operator sets (PATCH /settings/guilds/{id}).
    #
    # Inbound calls from the billing service (initiative-billing). Requests
    # carry an RS256 service JWT (verified against this public key) plus an
    # HMAC-SHA256 over METHOD\nPATH\nTIMESTAMP\nsha256(body) keyed by the
    # shared secret. Both must be configured or the /billing endpoints
    # refuse every request.
    #
    # The public key accepts more than one key, as concatenated PEM blocks, so
    # billing can rotate its signing key without downtime: append the new key,
    # let billing start signing with it, then drop the old block. A token is
    # accepted if any block verifies it. The HMAC has a second accepted value
    # for the same staged rotation protocol.
    # --- A bundled service's own channel ----------------------------------
    # An app this deployment ships rather than installs from the marketplace,
    # named by the ``public_id`` its registration carries, plus the secret it
    # signs its calls on that channel with.
    #
    # What it is for: a reference is minted per sector, so one party's name for
    # a guild is unrelated to another's and only this deployment holds both. A
    # bundled service that has to reconcile two of them asks here.
    #
    # Named rather than inferred from a grant: ``delegation`` says an app may
    # act for a member, which is a different question. Either value unset ⇒ the
    # channel answers 503 and nothing on it is reachable.
    BUNDLED_SERVICE_PUBLIC_ID: str | None = None
    BUNDLED_SERVICE_SHARED_SECRET: str | None = None

    BILLING_PUBLIC_KEY_PEM: str | None = None
    BILLING_HMAC_SECRET: str | None = None
    # Second accepted HMAC value during a staged rotation. It may hold the next
    # value before the cutover or the old value afterwards; clear it only once
    # every billing instance signs with BILLING_HMAC_SECRET.
    BILLING_HMAC_SECRET_PREVIOUS: str | None = None
    # Outbound base URL of the billing service, for the fire-and-forget
    # membership-change ping (guild id + event id only — no member data).
    # The ping is dispatched only when this AND BILLING_HMAC_SECRET are set.
    BILLING_SERVICE_URL: str | None = None
    # Public base URL of an external billing portal, surfaced to the SPA via
    # /config. Unset (the default) ⇒ the SPA shows NO tier label, upgrade, or
    # manage-billing UI; the usage panel still shows caps/usage (operator-set
    # numbers). Set ⇒ the link-out buttons appear: the OSS core defers to an
    # external service.
    BILLING_URL: str | None = None
    # Signing material for the operator handoff into the billing portal's
    # support console, shared with that service. Unset (the default) ⇒ the
    # Guilds tab renders no billing button and the mint endpoint 503s. The
    # key id selects which of the receiver's keys to verify against, so the
    # pair can be rotated without downtime.
    BILLING_SUPPORT_HANDOFF_SECRET: str | None = None
    BILLING_SUPPORT_HANDOFF_KID: str | None = None
    BILLING_OPERATOR_HANDOFF_SECRET: str | None = None
    BILLING_OPERATOR_HANDOFF_KID: str | None = None

    # --- Marketplace registry (optional; default OFF) ---------------------
    # A registry is not a service: it is a signed JSON index plus the manifest
    # and artwork files it names by digest, on any static host. Only the client
    # below runs. Both the URL and the key set are operator-supplied, so a
    # self-hoster or a community can publish their own index with their own key
    # and point a deployment at it.
    #
    # ``MARKETPLACE_REGISTRY_URL`` is the index document's URL; its detached
    # signature is read from the same URL with ``.sig`` appended, and every
    # artifact the index names resolves relative to it and must stay on the
    # same origin.
    #
    # ``MARKETPLACE_REGISTRY_PUBLIC_KEYS`` is a JWKS-shaped JSON document of the
    # keys this deployment trusts — ``{"keys": [{"kty": "OKP", "crv":
    # "Ed25519", "kid": "...", "x": "<base64url>", "publisher_prefixes":
    # ["acme"]}]}``. Several keys may be listed at once so a registry can
    # rotate: add the new key in one release, sign with it, drop the old one
    # later. ``publisher_prefixes`` states which listing namespaces that key may
    # publish under (``["*"]`` for any); ``core.*`` is reserved for listings
    # shipped in this repo and is never accepted from a registry.
    #
    # URL and keys are BOTH required, or the remote provider is simply absent:
    # no background refresh starts, the refresh endpoints answer 503, and the
    # catalog holds only what this build ships.
    MARKETPLACE_REGISTRY_URL: str | None = None
    MARKETPLACE_REGISTRY_PUBLIC_KEYS: str | None = None
    # How often the background refresh re-fetches the index. ~15 minutes keeps a
    # withdrawal reaching deployments promptly without polling a static host.
    MARKETPLACE_REGISTRY_TTL_SECONDS: int = Field(default=900, ge=60)
    # Operator kill switch. False stops the background refresh and the
    # "refresh now" endpoint without unsetting the URL or the keys, so a
    # deployment can pause ingestion and resume with its trust settings intact.
    MARKETPLACE_REGISTRY_ENABLED: bool = True

    # Local-dev only: when true, outbound webhook / custom-AI targets may
    # use http and resolve to private/loopback addresses, for round-tripping
    # with a locally run initiative-auto (its receiver at
    # ``http://localhost:8201``). Default false; production keeps the
    # https + public-address policy. The connection is pinned to the
    # resolved address regardless of this setting.
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
    # Master on/off switch for ALL rate limiting — the global default *and* every
    # per-route ``@limiter.limit(...)`` cap (e.g. login's ``5/15minutes``). Leave
    # True in any shared/production environment; set ``RATE_LIMIT_ENABLED=false``
    # in a local ``.env`` to stop throttling yourself while testing auth flows.
    # This is the same lever the test suite pulls (``limiter.enabled = False``),
    # surfaced as config; it is evaluated at startup, not per request.
    RATE_LIMIT_ENABLED: bool = True
    # Storage backend for rate-limit counters. Defaults to in-process memory
    # (``memory://``), which is per-worker — fine for a single process. For a
    # multi-worker / multi-replica deployment that needs a shared, accurate
    # counter, point this at Redis (``redis://host:6379/0``) or Memcached
    # (``memcached://host:11211``) WITHOUT any code change. See the slowapi /
    # limits "storage" docs for the full URI scheme list.
    RATE_LIMIT_STORAGE_URI: str = "memory://"

    # Expose the interactive API docs (Swagger UI at ``{API_V1_STR}/docs``) and
    # the raw OpenAPI schema (``{API_V1_STR}/openapi.json``). Defaults to True so
    # local development keeps its self-documenting API and the frontend's Orval
    # type generation against a running backend keeps working out of the box.
    # Operators SHOULD set this to ``False`` in production. The committed
    # ``frontend/openapi.json`` + ``scripts/export_openapi.py`` path means type
    # generation never needs a live ``/openapi.json`` in CI or prod.
    ENABLE_API_DOCS: bool = True

    # How much the application says about itself on stderr: one of the
    # standard Python level names (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    # The audit stream on stdout is not governed by this; it always emits.
    LOG_LEVEL: str = "INFO"

    @field_validator("LOG_LEVEL")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level == "NOTSET" or level not in logging.getLevelNamesMapping():
            raise ValueError(
                "LOG_LEVEL must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL; "
                f"got {value!r}"
            )
        return level

    # The bearer token a Prometheus scrape presents to read
    # ``{API_V1_STR}/metrics``. Unset (the default), that route answers 404.
    METRICS_TOKEN: str | None = None

    @field_validator("METRICS_TOKEN", mode="before")
    @classmethod
    def _blank_metrics_token_is_unset(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    # Mount the in-app MCP server at ``/api/v1/mcp/`` (route-backed). Off by
    # default; enable per-environment via env / .env. Tools ride the real auth +
    # RLS rails, so a caller only ever sees their own data, and a read-only API
    # key can't write.
    ENABLE_MCP: bool = False

    # Reject passwords that appear in the HaveIBeenPwned breach corpus
    # when a user sets one (registration, reset, change). Uses the
    # k-anonymity API — only the first 5 hex chars of the SHA-1 hash
    # leave the server. Flip to ``False`` to disable the check (e.g.
    # in air-gapped deployments or when egress is blocked); the length
    # floor in ``app.core.password_policy`` still applies.
    HIBP_CHECK_ENABLED: bool = True

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

    @field_validator("AUTH_LOGIN_METHODS", mode="before")
    @classmethod
    def parse_auth_login_methods(
        cls, value: str | list[str] | None
    ) -> list[str] | None:
        """Blank and unset read the same: the app's own default."""
        if value is None:
            return None
        items = value.replace(",", " ").split() if isinstance(value, str) else value
        normalized: list[str] = []
        for item in items:
            cleaned = item.strip().lower()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized or None


@lru_cache
# Use caching to avoid re-reading the env file over and over
# (FastAPI startup imports Config many times).
def get_settings() -> Settings:
    # The required field (SECRET_KEY) is loaded from the environment by
    # pydantic-settings, which ty can't see.
    return Settings()  # ty: ignore[missing-argument]


settings = get_settings()
