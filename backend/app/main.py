import asyncio
import logging
from contextlib import suppress
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

from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_upload_user
from app.api.v1.api import api_router
from app.core.rate_limit import limiter
from app.core.config import settings
from app.core.version import __version__
from app.db.session import AdminSessionLocal, get_admin_session, run_migrations
from app.models.user import User
from app.services import app_settings as app_settings_service
from app.services import background_tasks as background_tasks_service

logger = logging.getLogger(__name__)

uploads_path = Path(settings.UPLOADS_DIR)
uploads_path.mkdir(parents=True, exist_ok=True)
static_path = Path(settings.STATIC_DIR)
static_path.mkdir(parents=True, exist_ok=True)
static_index_path = static_path / "index.html"
static_root = static_path.resolve()
reserved_prefixes = [
    prefix.strip("/")
    for prefix in {settings.API_V1_STR}
    if prefix and prefix.strip("/")
]

# Gate the interactive docs + raw OpenAPI schema behind a setting (pentest
# SEC-16). When disabled, FastAPI serves no /docs and no /openapi.json, so the
# full route/parameter/error map isn't handed out. Defaults to on for dev
# ergonomics; recommend ENABLE_API_DOCS=False in production.
# docs_url is left None even when docs are enabled: the default route would
# inherit the app-wide CSP and the jsDelivr-hosted Swagger assets get blocked.
# A custom route below serves the same UI with a docs-scoped CSP instead.
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=__version__,
    docs_url=None,
    openapi_url=(
        f"{settings.API_V1_STR}/openapi.json" if settings.ENABLE_API_DOCS else None
    ),
    redoc_url=None,
)

if settings.ENABLE_API_DOCS:
    from fastapi.openapi.docs import get_swagger_ui_html

    _DOCS_CSP = settings.docs_content_security_policy

    @app.get(f"{settings.API_V1_STR}/docs", include_in_schema=False)
    async def swagger_ui_html() -> Response:
        # get_swagger_ui_html returns the Swagger HTML that loads its JS/CSS from
        # jsDelivr; attach the docs-scoped CSP so only this response permits them.
        # The middleware uses setdefault, so this explicit header wins.
        response = get_swagger_ui_html(
            openapi_url=f"{settings.API_V1_STR}/openapi.json",
            title=f"{settings.PROJECT_NAME} - Swagger UI",
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

app.add_middleware(
    CORSMiddleware,
    # Explicit allowlist (never "*"): wildcard + allow_credentials reflects any
    # origin and would let any site make authenticated requests (CRIT-001).
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/uploads/{guild_id}/{filename:path}", include_in_schema=False)
@limiter.limit("600/minute")
async def serve_upload_file(
    request: Request,
    guild_id: int,
    filename: str,
    current_user: Annotated[User, Depends(get_upload_user)],
    session: Annotated[AsyncSession, Depends(get_admin_session)],
) -> FileResponse:
    """Serve an uploaded file — requires authentication and an Upload row in
    the path-addressed guild."""
    from pathlib import Path as FilePath

    from sqlalchemy import text

    try:
        file_path = (uploads_path / filename).resolve()
        file_path.relative_to(uploads_path.resolve())
    except ValueError:
        raise HTTPException(status_code=404)
    if not file_path.is_file():
        raise HTTPException(status_code=404)

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
    from app.services import access_grants as access_grants_service
    from app.services import guilds as guilds_service

    membership = await guilds_service.get_membership(
        session, guild_id=guild_id, user_id=current_user.id
    )
    if membership is None:
        grant = await access_grants_service.get_live_grant(
            session, user_id=current_user.id, guild_id=guild_id
        )
        if grant is None:
            raise HTTPException(status_code=404)

    # The admin login role has NO table grants on a guild schema, so SET ROLE
    # into the guild role (``set_rls_context``) before reading its ``uploads``
    # — and only if the schema actually exists (pg_namespace is readable by
    # any role; SET ROLE into a missing role would error).
    fname = FilePath(filename).name
    schema = guild_schema_name(int(guild_id))
    exists = (
        await session.execute(
            text("SELECT 1 FROM pg_namespace WHERE nspname = :ns"),
            {"ns": schema},
        )
    ).first()
    if exists is None:
        raise HTTPException(status_code=404)
    await set_rls_context(session, guild_id=int(guild_id), is_superadmin=True)
    hit = (
        await session.execute(
            text("SELECT 1 FROM uploads WHERE filename = :fn LIMIT 1"),
            {"fn": fname},
        )
    ).first()
    if hit is None:
        raise HTTPException(status_code=404)

    headers: dict[str, str] = {}
    if filename.lower().endswith((".svg", ".html", ".htm")):
        headers["Content-Disposition"] = "attachment"
        headers["Content-Security-Policy"] = "script-src 'none'"
        headers["X-Content-Type-Options"] = "nosniff"
    logger.info("upload_served filename=%s user=%d", filename, current_user.id)
    return FileResponse(file_path, headers=headers)


app.include_router(api_router, prefix=settings.API_V1_STR)


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
    sf_ref = {"$ref": "#/components/schemas/SortField"}
    for path_item in openapi_schema.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            for param in operation.get("parameters", []):
                if param.get("name") == "conditions" and param.get("in") == "query":
                    param["schema"] = {"type": "array", "items": fc_ref}
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


app.openapi = custom_openapi


@app.on_event("startup")
async def on_startup() -> None:
    from app.db.init_db import check_pre_baseline_db
    from app.db.soft_delete_filter import install_soft_delete_filter

    # Surface the effective CORS allowlist so a misconfigured split-origin
    # deployment (SPA served from a host other than APP_URL) is self-diagnosing.
    logger.info("CORS allowed origins: %s", settings.cors_origins)

    install_soft_delete_filter()
    await check_pre_baseline_db()
    await run_migrations()
    # Move any pre-cutover guild data from public into per-guild schemas. Idempotent
    # — a no-op once converted — so packaged deploys convert themselves on boot.
    from app.db.guild_conversion import convert_public_to_guild_schemas

    await convert_public_to_guild_schemas()
    # Re-run the idempotent per-guild provisioning for every guild so any
    # table/column/index/grant added to guild_schema.sql since a guild was
    # provisioned is back-filled, and any guild left without a schema (e.g. a
    # crash mid-provision) is healed. One broken guild is logged and skipped.
    from app.db.schema_provisioning import backfill_guild_schemas

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
            "guild schema back-fill: %d provisioned (of %d)",
            backfill.provisioned,
            backfill.total,
        )
    async with AdminSessionLocal() as session:
        await app_settings_service.ensure_defaults(session)
    app.state.notification_tasks = background_tasks_service.start_background_tasks()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    tasks = getattr(app.state, "notification_tasks", [])
    for task in tasks:
        task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task
