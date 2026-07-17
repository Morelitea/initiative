import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_upload_user
from app.core.body_limit import BodySizeLimitMiddleware
from app.api.v1.api import api_router
from app.core.messages import GuildMessages
from app.core.rate_limit import limiter
from app.core.config import API_V1_STR, PROJECT_NAME, settings
from app.core.version import __version__
from app.db.session import AdminSessionLocal, get_admin_session, run_migrations
from app.models.platform.user import User
from app.services.platform import app_settings as app_settings_service
from app.services import background_tasks as background_tasks_service

logger = logging.getLogger(__name__)

uploads_path = Path(settings.UPLOADS_DIR)
uploads_path.mkdir(parents=True, exist_ok=True)
static_path = Path(settings.STATIC_DIR)
static_path.mkdir(parents=True, exist_ok=True)
static_index_path = static_path / "index.html"
static_root = static_path.resolve()
reserved_prefixes = [
    prefix.strip("/") for prefix in {API_V1_STR} if prefix and prefix.strip("/")
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown.

    Modern replacement for the deprecated ``@app.on_event`` handlers. When the
    MCP server is mounted (``ENABLE_MCP``), its Streamable-HTTP session-manager
    lifespan is combined with this one via ``combine_lifespans`` in the mount
    block after ``include_router`` — so the MCP server boots alongside the API.
    """
    from app.db.init_db import check_pre_baseline_db, init_owner
    from app.db.soft_delete_filter import install_soft_delete_filter

    # Surface the effective CORS allowlist so a misconfigured split-origin
    # deployment (SPA served from a host other than APP_URL) is self-diagnosing.
    logger.info("CORS allowed origins: %s", settings.cors_origins)

    install_soft_delete_filter()
    await check_pre_baseline_db()
    await run_migrations()
    # Re-run the idempotent per-guild provisioning for every guild so any
    # table/column/index/grant the live guild_template gained since a guild was
    # provisioned is back-filled, and any guild left without a schema (e.g. a
    # crash mid-provision) is healed. One broken guild is logged and skipped;
    # guilds stamped with the current artifact version are skipped entirely.
    from app.db.schema_provisioning import (
        backfill_guild_schemas,
        ensure_shared_table_grants,
        ensure_system_engine_bypassrls,
        warn_if_privileged_database_url,
    )

    # Before anything touches the system engine: a policy-bound admin login
    # (restored database, hand-created role) reads shared tables as empty and
    # the seeding below would die with an opaque RLS violation (issue #835).
    await ensure_system_engine_bypassrls()
    # One gate deeper: a restored/recreated role can bypass RLS yet be missing
    # the per-table GRANTs (cluster state a stamped DB never re-applies), so
    # seeding dies on "permission denied for table guilds" instead. Re-assert
    # the audited shared-table grants from the registry (issue #835 follow-up).
    await ensure_shared_table_grants()
    await warn_if_privileged_database_url()
    backfill = await backfill_guild_schemas()
    if backfill.failed:
        # WARNING so partial failure survives INFO-filtered logs (per-guild
        # tracebacks were already logged inside the back-fill).
        logger.warning(
            "guild schema back-fill: %d provisioned, %d FAILED (of %d) — guilds %s",
            backfill.provisioned,
            backfill.failed,
            backfill.total,
            backfill.failed_guild_ids,
        )
    else:
        logger.info(
            "guild schema back-fill: %d provisioned, %d up-to-date (of %d)",
            backfill.provisioned,
            backfill.skipped,
            backfill.total,
        )
    # Relocate any legacy flat local uploads into per-guild dirs (guild_<id>/),
    # matching the object-store layout. Local-only, idempotent, self-disabling —
    # a no-op once converted, so packaged deploys convert themselves on boot.
    from app.db.local_upload_migration import migrate_local_uploads_to_guild_prefix

    await migrate_local_uploads_to_guild_prefix()
    # Rotate SECRET_KEY-derived data (encrypted fields + email_hash) when
    # PREVIOUS_SECRET_KEY names a prior key. Runs after guild schemas exist and
    # before traffic is served, so a packaged deploy rotates itself on boot.
    # Idempotent — a no-op once rotated (then unset PREVIOUS_SECRET_KEY).
    from app.db.secret_key_rotation import maybe_rotate_at_startup

    await maybe_rotate_at_startup()
    # First-owner bootstrap (FIRST_OWNER_EMAIL / FIRST_OWNER_PASSWORD): create
    # the owner and their guild on first boot so a self-hosted instance is
    # usable straight from `docker run` with two env vars.
    # No-op when the env vars are unset (the /auth/bootstrap first-user
    # flow still applies) or the owner already exists.)
    try:
        await init_owner()
    except IntegrityError:
        # Unique violation on the owner's email_hash: a concurrent replica won
        # the first-boot race and created the owner between our existence check
        # and commit.
        logger.info("first-owner bootstrap: created by a concurrent replica")
    async with AdminSessionLocal() as session:
        await app_settings_service.ensure_defaults(session)
        # Prime the process-wide storage config snapshot from the DB so the
        # request path uses the saved backend/credentials, not just env vars.
        from app.services import storage_config

        await storage_config.refresh_storage_config(session)
    # Migrate the single platform OIDC config into the provider registry +
    # identity links, and copy the per-user refresh token + sync stamp onto
    # those links (operator-global; idempotent, self-healing). Runs after
    # ensure_defaults so the settings singleton exists. Additive — the legacy
    # app_settings.oidc_* / users.oidc_* columns stay (unread) until the final
    # cutover phase drops them.
    from app.services.auth.oidc_backfill import backfill_oidc_identity

    oidc = await backfill_oidc_identity()
    if (
        oidc.provider_created
        or oidc.identities_linked
        or oidc.secret_migrated
        or oidc.refresh_tokens_copied
    ):
        logger.info(
            "OIDC identity back-fill: provider %s, %d identities linked (of %d), "
            "%d refresh token(s) copied, secret %s",
            "created" if oidc.provider_created else "existing",
            oidc.identities_linked,
            oidc.oidc_users,
            oidc.refresh_tokens_copied,
            "migrated" if oidc.secret_migrated else "unchanged",
        )
    app.state.notification_tasks = background_tasks_service.start_background_tasks()

    try:
        yield
    finally:
        # Shutdown: cancel the background notification tasks.
        tasks = getattr(app.state, "notification_tasks", [])
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task


# Gate the interactive docs + raw OpenAPI schema behind a setting (pentest
# SEC-16). When disabled, FastAPI serves no /docs and no /openapi.json, so the
# full route/parameter/error map isn't handed out. Defaults to on for dev
# ergonomics; recommend ENABLE_API_DOCS=False in production.
# docs_url is left None even when docs are enabled: the default route would
# inherit the app-wide CSP and the jsDelivr-hosted Swagger assets get blocked.
# A custom route below serves the same UI with a docs-scoped CSP instead.
app = FastAPI(
    title=PROJECT_NAME,
    version=__version__,
    lifespan=lifespan,
    docs_url=None,
    openapi_url=(f"{API_V1_STR}/openapi.json" if settings.ENABLE_API_DOCS else None),
    redoc_url=None,
)

if settings.ENABLE_API_DOCS:
    from fastapi.openapi.docs import get_swagger_ui_html

    _DOCS_CSP = settings.docs_content_security_policy

    @app.get(f"{API_V1_STR}/docs", include_in_schema=False)
    async def swagger_ui_html() -> Response:
        # get_swagger_ui_html returns the Swagger HTML that loads its JS/CSS from
        # jsDelivr; attach the docs-scoped CSP so only this response permits them.
        # The middleware uses setdefault, so this explicit header wins.
        response = get_swagger_ui_html(
            openapi_url=f"{API_V1_STR}/openapi.json",
            title=f"{PROJECT_NAME} - Swagger UI",
        )
        response.headers["Content-Security-Policy"] = _DOCS_CSP
        return response


# Initialize rate limiter (uses shared limiter from app.core.rate_limit)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
# Register the middleware so the limiter's `default_limits` actually apply to
# *every* route, not just the handful with an explicit `@limiter.limit(...)`
# decorator (SEC-14). Without this the global default was inert. The middleware
# short-circuits when `limiter.enabled` is False (the test suite sets that), and
# routes that already carry a decorator are exempted from the default here.
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Strip the echoed ``input`` (and the pydantic docs ``url``) from 422
    bodies so a failed validation can't leak the submitted value — e.g. a
    password or client secret on an auth/settings endpoint (pentest LOW-001).
    Field locations and messages are kept: they're already public via the
    OpenAPI schema and the SPA surfaces them.
    """
    safe_errors = [
        {key: value for key, value in error.items() if key in ("type", "loc", "msg")}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": safe_errors},
    )


_INSUFFICIENT_PRIVILEGE_SQLSTATE = "42501"


def _dbapi_sqlstate(exc: DBAPIError) -> str | None:
    """Best-effort SQLSTATE off a wrapped DBAPI error (asyncpg adapter nests
    the real exception one level down as ``orig.__cause__``)."""
    orig = getattr(exc, "orig", None)
    for candidate in (orig, getattr(orig, "__cause__", None)):
        code = getattr(candidate, "sqlstate", None) or getattr(
            candidate, "pgcode", None
        )
        if code:
            return code
    return None


@app.exception_handler(DBAPIError)
async def insufficient_privilege_handler(
    request: Request, exc: DBAPIError
) -> JSONResponse:
    """Map Postgres ``insufficient_privilege`` (42501) to a generic 403.

    Denials enforced at the role layer — e.g. a write attempted while routed
    into the SELECT-only ``guild_<id>_ro`` role (PAM read grants, guilds in
    ``read_only`` status) — surface as asyncpg errors, not app-layer checks.
    They ARE authorization denials, so answer 403 with the same generic code
    the resolver uses; deliberately no status-specific detail (a member of a
    read-only-suspended guild learns nothing about why). Everything else
    re-raises to the default 500 path.

    Always logged server-side: 42501 is expected only on the read-only-role
    write paths, so any other occurrence (a missing SET ROLE, a revoked table
    grant, a misconfigured login role) must be findable in the logs — the
    client body is deliberately too generic to debug from.
    """
    if _dbapi_sqlstate(exc) == _INSUFFICIENT_PRIVILEGE_SQLSTATE:
        logger.warning(
            "insufficient_privilege mapped to 403: %s %s orig=%s",
            request.method,
            request.url.path,
            getattr(exc, "orig", exc),
        )
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": GuildMessages.GUILD_ACCESS_DENIED},
        )
    raise exc


# Computed once — Settings are fixed for the process lifetime (pentest MED-001).
_CONTENT_SECURITY_POLICY = settings.content_security_policy

# Emit HSTS only when the public origin is HTTPS (pentest SEC-16): the header is
# inert over plain HTTP and pinning a dev http:// origin to HTTPS would break it.
# Two years + includeSubDomains is the preload-eligible baseline; computed once
# since Settings are immutable for the process lifetime.
_STRICT_TRANSPORT_SECURITY = (
    "max-age=63072000; includeSubDomains" if settings.app_url_is_https else None
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        # setdefault: preserve any stricter per-response CSP (e.g. the upload
        # route's `script-src 'none'`) instead of overriding it.
        response.headers.setdefault("Content-Security-Policy", _CONTENT_SECURITY_POLICY)
        if _STRICT_TRANSPORT_SECURITY is not None:
            # Unconditional (not setdefault): unlike CSP there is no legitimate
            # per-route reason to weaken HSTS, so the middleware always wins.
            response.headers["Strict-Transport-Security"] = _STRICT_TRANSPORT_SECURITY
        return response


app.add_middleware(SecurityHeadersMiddleware)

# Body-size bounds for upload-shaped routes — enforced at the ASGI seam so an
# oversized (or chunked, length-less) request is refused before its body is
# buffered, not after FastAPI has already parsed it.
app.add_middleware(BodySizeLimitMiddleware)

app.add_middleware(
    CORSMiddleware,
    # Explicit allowlist (never "*"): wildcard + allow_credentials reflects any
    # origin and would let any site make authenticated requests (CRIT-001).
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Export downloads name the file server-side (Content-Disposition); the
    # SPA reads it to name the blob it saves — expose it for the native
    # (cross-origin) app, web is same-origin and sees it regardless.
    expose_headers=["Content-Disposition"],
)


@app.get("/uploads/{guild_id}/{filename:path}", include_in_schema=False)
@limiter.limit("600/minute")
async def serve_upload_file(
    request: Request,
    guild_id: int,
    filename: str,
    current_user: Annotated[User, Depends(get_upload_user)],
    session: Annotated[AsyncSession, Depends(get_admin_session)],
) -> Response:
    """Serve an uploaded file — requires authentication and an Upload row in
    the path-addressed guild."""
    from pathlib import Path as FilePath

    from sqlalchemy import text

    from app.services.storage import build_upload_response, get_guild_storage

    # Guild authorization via the ``/uploads/{guild_id}/…`` path: media is
    # referenced by pages inside a guild, and ``<img>``/iframe can't send headers,
    # so the guild rides in the URL (and a cookie is per-browser, not per-tab).
    # Validate access (membership or live PAM grant) against the path guild →
    # route into that ONE guild schema and look the filename up there. Fail
    # closed: no access, no schema, or no Upload row in that guild all 404
    # without confirming the blob exists. The frozen ``public.uploads`` backup
    # is never read.
    from app.db.session import set_rls_context
    from app.db.schema_provisioning import guild_schema_name
    from app.models.platform.guild import GuildStatus
    from app.services.platform import access_grants as access_grants_service
    from app.services.platform import guilds as guilds_service

    membership = await guilds_service.get_membership(
        session, guild_id=guild_id, user_id=current_user.id
    )
    if membership is None:
        grant = await access_grants_service.get_live_grant(
            session, user_id=current_user.id, guild_id=guild_id
        )
        if grant is None:
            raise HTTPException(status_code=404)
    else:
        # A suspended guild is unreadable to its members (mirrors the resolver
        # gate in deps._load_guild_context; this route resolves access inline).
        # The grant branch above deliberately skips the status — PAM overrides
        # suspension. read_only needs nothing here: serving a file is a read.
        guild = await guilds_service.get_guild(session, guild_id=guild_id)
        if guild.status == GuildStatus.suspended.value:
            raise HTTPException(status_code=404)

    # The admin login role has NO table grants on a guild schema, so SET ROLE
    # into the guild role (``set_rls_context``) before reading its ``uploads``
    # — and only if the schema actually exists (pg_namespace is readable by
    # any role; SET ROLE into a missing role would error).
    fname = FilePath(filename).name
    schema = guild_schema_name(int(guild_id))
    exists = (
        await session.exec(
            text("SELECT 1 FROM pg_namespace WHERE nspname = :ns"),
            params={"ns": schema},
        )
    ).first()
    if exists is None:
        raise HTTPException(status_code=404)
    await set_rls_context(session, guild_id=int(guild_id))
    hit = (
        await session.exec(
            text("SELECT 1 FROM uploads WHERE filename = :fn LIMIT 1"),
            params={"fn": fname},
        )
    ).first()
    if hit is None:
        raise HTTPException(status_code=404)

    # Storage is touched only after authorization passes. open_readable returns
    # None for a missing/traversal key -> 404 (same fail-closed shape as before).
    blob = get_guild_storage(guild_id).open_readable(filename)
    if blob is None:
        raise HTTPException(status_code=404)

    headers: dict[str, str] = {}
    if filename.lower().endswith((".svg", ".html", ".htm")):
        headers["Content-Disposition"] = "attachment"
        headers["Content-Security-Policy"] = "script-src 'none'"
        headers["X-Content-Type-Options"] = "nosniff"
    logger.info("upload_served filename=%s user=%d", filename, current_user.id)
    return build_upload_response(blob, headers=headers)


app.include_router(api_router, prefix=API_V1_STR)


def _inject_query_schemas(openapi_schema: dict) -> None:
    """Inject shared query filter/sort schemas into OpenAPI components.

    These schemas (FilterCondition, FilterOp, FilterGroup, SortField, SortDir)
    are defined in ``app.schemas.query`` and used by list endpoints that accept
    a ``conditions`` JSON query parameter.  Injecting them here lets Orval
    auto-generate TypeScript types so the frontend never hand-defines them.
    """
    from app.schemas.query import (
        FilterCondition,
        FilterGroup,
        FilterOp,
        SortDir,
        SortField,
    )

    schemas = openapi_schema.setdefault("components", {}).setdefault("schemas", {})

    for model in (FilterCondition, FilterGroup, SortField):
        full = model.model_json_schema(
            ref_template="#/components/schemas/{model}",
        )
        defs = full.pop("$defs", {})
        # For self-referencing models (e.g. FilterGroup) the top level is
        # just {"$ref": "..."} and the real schema lives in $defs.
        if "$ref" in full and not full.get("properties"):
            real = defs.pop(model.__name__, full)
            schemas[model.__name__] = real
        else:
            schemas[model.__name__] = full
        for name, sub_schema in defs.items():
            schemas.setdefault(name, sub_schema)

    # Enums as standalone schemas (may already be added via $defs above)
    for enum_cls in (FilterOp, SortDir):
        schemas.setdefault(
            enum_cls.__name__,
            {
                "title": enum_cls.__name__,
                "type": "string",
                "enum": [e.value for e in enum_cls],
            },
        )

    # Override query parameters to expose their real types instead of the raw
    # ``string`` that FastAPI infers from the endpoint signature.  The Axios
    # paramsSerializer on the frontend JSON-encodes arrays of objects automatically.
    fc_ref = {"$ref": "#/components/schemas/FilterCondition"}
    fg_ref = {"$ref": "#/components/schemas/FilterGroup"}
    sf_ref = {"$ref": "#/components/schemas/SortField"}
    for path_item in openapi_schema.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            for param in operation.get("parameters", []):
                if param.get("name") == "conditions" and param.get("in") == "query":
                    # An item is either a leaf comparison or an AND/OR group.
                    param["schema"] = {
                        "type": "array",
                        "items": {"anyOf": [fc_ref, fg_ref]},
                    }
                    param.pop("anyOf", None)
                if param.get("name") == "sorting" and param.get("in") == "query":
                    param["schema"] = {"type": "array", "items": sf_ref}
                    param.pop("anyOf", None)


def custom_openapi() -> dict:
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    components = openapi_schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    security_schemes.setdefault(
        "ApiKeyAuth",
        {
            "type": "http",
            "scheme": "bearer",
            "description": "Paste an admin API key issued from Settings → API Keys.",
        },
    )

    _inject_query_schemas(openapi_schema)

    for path_item in openapi_schema.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            security = operation.get("security")
            if not security:
                continue
            has_api_key = any(
                isinstance(item, dict) and "ApiKeyAuth" in item for item in security
            )
            if not has_api_key:
                security.append({"ApiKeyAuth": []})

    app.openapi_schema = openapi_schema
    return app.openapi_schema


# Attach the custom OpenAPI generator now — BEFORE the MCP server is built below.
# ``build_mcp_server(app)`` calls ``app.openapi()`` to derive its tools; if the
# override isn't in place yet, FastAPI's default generator runs and caches a spec
# without the ``_inject_query_schemas`` upgrades, which then leaks into the frontend
# type generation (conditions/sorting collapse back to ``string``). The SPA catch-all
# registered later is ``include_in_schema=False``, so the spec is already complete here.
app.openapi = custom_openapi  # ty: ignore[invalid-assignment]

if settings.ENABLE_MCP:
    # Build the route-backed MCP server from the fully-routed app and mount it at
    # /api/v1/mcp (before the SPA catch-all below, so it wins that path). Build
    # order matters: the routers above must already be included so the read-only
    # RouteMap can see them. ``combine_lifespans`` runs the MCP session-manager
    # lifespan alongside the app's own startup/shutdown (see ``lifespan``).
    from fastmcp.utilities.lifespan import combine_lifespans

    from app.mcp_server import build_mcp_server

    _mcp_app = build_mcp_server(app).http_app(path="/")
    app.mount(f"{API_V1_STR}/mcp", _mcp_app)
    app.router.lifespan_context = combine_lifespans(lifespan, _mcp_app.lifespan)


def _is_reserved_path(path: str) -> bool:
    normalized = path.strip("/")
    for prefix in reserved_prefixes:
        if not prefix:
            continue
        if normalized == prefix or normalized.startswith(f"{prefix}/"):
            return True
    return False


def _resolve_static_file(path: str) -> Path | None:
    try:
        candidate = (static_path / path).resolve()
        candidate.relative_to(static_root)
    except ValueError:
        return None
    if candidate.is_file():
        return candidate
    return None


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_spa(full_path: str) -> FileResponse:
    if _is_reserved_path(full_path):
        raise HTTPException(status_code=404)
    static_file = _resolve_static_file(full_path) if full_path else None
    if static_file:
        if full_path.startswith("assets/"):
            return FileResponse(
                static_file,
                headers={"Cache-Control": "public, max-age=31536000, immutable"},
            )
        return FileResponse(
            static_file,
            headers={"Cache-Control": "public, max-age=3600"},
        )
    if static_index_path.is_file():
        return FileResponse(
            static_index_path,
            headers={"Cache-Control": "no-cache"},
        )
    raise HTTPException(status_code=404, detail="SPA bundle not found")
