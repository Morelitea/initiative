import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from functools import lru_cache
from pathlib import Path

from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware, _should_exempt, sync_check_limits
from starlette.routing import Match

from sqlalchemy.exc import DBAPIError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import declines_this_credential, get_upload_user, pinned_elsewhere
from app.api.embed_csp import app_frame_policy
from app.core.body_limit import BodySizeLimitMiddleware
from app.core.csrf import CsrfOriginMiddleware
from app.api.v1.api import api_router
from app.core.messages import CommonMessages, GuildMessages
from app.core.rate_limit import limiter
from app.core.security import (
    billing_support_handoff_enabled,
)
from app.core.config import API_V1_STR, PROJECT_NAME, settings
from app.core.logging_config import configure_logging
from app.core.request_audit import RequestAuditMiddleware
from app.core.version import __version__
from app.db.errors import INSUFFICIENT_PRIVILEGE_SQLSTATE, dbapi_sqlstate
from app.db.frozen import FROZEN_PARENT_CONSTRAINT, frozen_refusal
from app.db.session import SystemSessionLocal, get_system_session
from app.models.platform.user import User
from app.services import background_tasks as background_tasks_service
from app.services import captcha_config
from app.services.platform.users import SeatWouldBeEmptied

# Before anything in this process logs: the served wiring for the application
# stream and the audit stream (see app.core.logging_config).
configure_logging()

logger = logging.getLogger(__name__)

#: Stored types a served upload is rendered inline as. Raster pictures only:
#: an ``<img>`` draws these and nothing about them is markup. Anything else —
#: an SVG, a document file, a type nothing recognizes — is handed over as a
#: download with scripts disabled.
INLINE_UPLOAD_TYPES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/tiff",
        "image/x-icon",
        "image/vnd.microsoft.icon",
    }
)

#: The same question for a row written before the type column existed: its
#: stored name is the only thing that describes it.
NAMED_AS_MARKUP = (".svg", ".html", ".htm")

#: How long a browser may reuse a served upload before asking again.
#:
#: A stored blob is immutable, so this is not about staleness — it is how
#: often access is re-checked. Five minutes: long enough that scrolling a
#: gallery up and down is not a request per picture per pass, short enough to
#: stay close to the current answer.
UPLOAD_CACHE_SECONDS = 300

uploads_path = Path(settings.UPLOADS_DIR)
uploads_path.mkdir(parents=True, exist_ok=True)
static_path = Path("static")
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
    from app.db.init_db import prepare_database
    from app.db.soft_delete_filter import install_soft_delete_filter

    # Surface the effective CORS allowlist so a misconfigured split-origin
    # deployment (SPA served from a host other than APP_URL) is self-diagnosing.
    logger.info("CORS allowed origins: %s", settings.cors_origins)

    install_soft_delete_filter()
    # Everything the database needs before this process serves it: the
    # bootstrap, migrations, the heals and the seeds. The same function is
    # `python -m app.db.init_db`.
    await prepare_database()
    # Passkeys are bound to a named host reached over https, so a deployment
    # addressed any other way is told once at boot rather than per refusal.
    from app.services.auth import passkeys as passkey_service

    site_refusal = passkey_service.site_refusal()
    if site_refusal is not None:
        logger.warning(
            "APP_URL (%s) is %s, so passkey registration will be refused; "
            "serve this deployment from a domain name over https to offer it.",
            settings.APP_URL,
            {
                "ip_host": "an address rather than a domain name",
                "no_host": "not a whole URL, so it names no host",
            }.get(site_refusal, "plain http"),
        )
    if settings.BILLING_URL and not billing_support_handoff_enabled():
        # The Guilds tab shows its billing button whenever a portal URL is set;
        # without the signing pair every click fails closed (503).
        logger.warning(
            "BILLING_URL is set but BILLING_SUPPORT_HANDOFF_SECRET / "
            "BILLING_SUPPORT_HANDOFF_KID are not; the operator billing handoff "
            "will fail closed until both are configured."
        )
    async with SystemSessionLocal() as session:
        # Prime the process-wide storage config snapshot from the DB so the
        # request path uses the saved backend/credentials, not just env vars.
        from app.services import storage_config

        await storage_config.refresh_storage_config(session)
        # The same for the captcha secret and the FCM service account: both are
        # read from paths that hold no usable session (a synchronous predicate,
        # a background dispatch), so each keeps a process-wide snapshot, and it
        # has to be primed here or the first request answers from the env seed.
        from app.services.platform import push_config

        await captcha_config.refresh_captcha_config(session)
        await push_config.refresh_push_config(session)

    app.state.notification_tasks = background_tasks_service.start_background_tasks()

    # The cross-worker nudge bus, and its subscribers. Starting it is
    # fire-and-forget by design: it maintains its own connection in the
    # background and a deployment that cannot reach it still delivers every
    # frame to the sockets this process holds.
    from app.services.platform import notify_bus, user_stream
    from app.services.tenant import room_sink

    notify_bus.register(
        user_stream.CHANNEL,
        user_stream.deliver_remote,
        on_connect=user_stream.on_bus_connected,
    )
    notify_bus.register(
        room_sink.CHANNEL, room_sink.deliver, on_connect=room_sink.on_bus_connected
    )
    await notify_bus.start()

    # Write collaborative documents that have changed on an interval, so what a
    # live editing session has produced does not depend on its last connection
    # closing cleanly to reach the database.
    from app.services.tenant.collaboration import collaboration_manager

    collaboration_manager.ensure_persistence_loop()

    try:
        yield
    finally:
        await collaboration_manager.stop_persistence_loop()
        await notify_bus.stop()
        # Shutdown: cancel the background notification tasks.
        tasks = getattr(app.state, "notification_tasks", [])
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        # Imports the dispatcher started run as tasks of their own.
        from app.services.import_engine.worker import cancel_running_jobs

        await cancel_running_jobs()


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

#: Stands in for a request that lands on a mounted sub-app. A mount has no
#: endpoint to read a marker off, which is a different answer from "no route
#: matched" and gets different treatment below.
_MOUNTED = object()


def _route_endpoint(request: Request) -> object | None:
    """The endpoint the router will run for this request.

    Starlette dispatches to the FIRST route that fully matches, so this stops
    there rather than reading on.
    """
    for route in request.app.routes:
        match, _ = route.matches(request.scope)
        if match == Match.FULL:
            endpoint = getattr(route, "endpoint", None)
            return _MOUNTED if endpoint is None else endpoint
    return None


class _DefaultRateLimit(SlowAPIMiddleware):
    """The global default limit, applied against the route that will run.

    Upstream picks a request's handler by scanning every route and keeping the
    LAST one that matches. This app registers 600-odd routes and ends with a
    catch-all serving the SPA, which matches everything — so upstream resolves
    every request to ``serve_spa``, and three things follow from that:

    * ``@limiter.exempt`` is never seen, because the name it registers is not
      the name the middleware looks up.
    * A route's own ``@limiter.limit`` never displaces the default, so one
      set deliberately ABOVE the default is silently held down to it.
    * Every request pays a full scan of all 600 routes — ~430µs, measured.

    Resolving the way the router itself does settles all three, so this
    replaces ``dispatch`` rather than wrapping it: delegating upward would run
    the scan it is here to avoid.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        request_limiter = request.app.state.limiter
        if not request_limiter.enabled:
            return await call_next(request)

        endpoint = _route_endpoint(request)
        if endpoint is _MOUNTED:
            # Nothing to read a marker off, so a mount is limited like any
            # undecorated route — by the URL it was asked for.
            handler = None
        elif _should_exempt(request_limiter, endpoint):
            return await call_next(request)
        else:
            handler = endpoint

        error_response, inject_headers = sync_check_limits(
            request_limiter, request, handler, request.app
        )
        if error_response is not None:
            return error_response
        response = await call_next(request)
        if inject_headers:
            response = request_limiter._inject_headers(
                response, request.state.view_rate_limit
            )
        return response


app.add_middleware(_DefaultRateLimit)


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
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": safe_errors},
    )


@app.exception_handler(SeatWouldBeEmptied)
async def seat_would_be_emptied_handler(
    request: Request, exc: SeatWouldBeEmptied
) -> JSONResponse:
    """A removal that would leave a community without a superadmin.

    Handled here rather than at each deletion route because the refusal is
    raised from the membership drop, which every one of them goes through —
    self-service deactivate and delete, and the operator's versions of both.
    The communities are named by the eligibility call the dialog already
    makes; this says why the action stopped.
    """
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": GuildMessages.CANNOT_VACATE_LAST_SUPERADMIN},
    )


@app.exception_handler(DBAPIError)
async def insufficient_privilege_handler(
    request: Request, exc: DBAPIError
) -> JSONResponse:
    """Map a database-layer refusal to the answer it deserves.

    The lifecycle freeze comes first: the content is archived or in the trash —
    or what it sits inside is — the caller may well be its owner, and the thing
    to do is bring one or the other back. 409, naming which, rather than a
    permission answer.

    Otherwise, map Postgres ``insufficient_privilege`` (42501) to a generic 403.

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
    refusal = frozen_refusal(exc)
    if refusal is not None:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": CommonMessages.PARENT_IS_FROZEN
                if refusal == FROZEN_PARENT_CONSTRAINT
                else CommonMessages.CONTENT_IS_FROZEN
            },
        )
    if dbapi_sqlstate(exc) == INSUFFICIENT_PRIVILEGE_SQLSTATE:
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


@lru_cache(maxsize=8)
def _content_security_policy(captcha_provider: str | None) -> str:
    """The app-wide CSP (pentest MED-001), built once per captcha provider.

    The provider lives in the settings row, so it can change while the process
    runs; everything else in the header is fixed for the process lifetime.
    """
    return settings.content_security_policy_with_frames(
        (), captcha_provider=captcha_provider
    )


# The three WebAssembly workers — the dashboard widget sandbox, the direct
# message ratchet and the PDF viewer's pdf.js worker — and only they, are served
# with a policy that admits WebAssembly. Vite emits worker bundles into
# `assets/workers/` with a content hash (see `worker.rolldownOptions` in
# frontend/vite.config.ts) and the pdfjs plugin there puts pdf.js beside them
# under its version, so the match is by directory + stem; the literals are
# pinned by tests on both sides.
_WASM_WORKER_ASSET_PREFIXES = (
    "assets/workers/sandbox.worker-",
    "assets/workers/ratchet.worker-",
    "assets/workers/pdf.worker-",
)
# The first two are bundled by Vite as classic `.js`; pdf.js ships an ES module
# and is emitted under its own name.
_WASM_WORKER_ASSET_SUFFIXES = (".js", ".mjs")
_WASM_WORKER_CSP = settings.wasm_worker_content_security_policy


def _is_wasm_worker_asset(path: str) -> bool:
    """True for the built files that carry the WebAssembly worker policy.

    The hash varies per build, so the tail is open — but only as far as the one
    filename: anything nested below that name is an ordinary asset.
    """
    if not path.endswith(_WASM_WORKER_ASSET_SUFFIXES):
        return False
    return any(
        path.startswith(prefix) and "/" not in path[len(prefix) :]
        for prefix in _WASM_WORKER_ASSET_PREFIXES
    )


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
        response.headers.setdefault(
            "Content-Security-Policy",
            _content_security_policy(captcha_config.current_captcha_config().provider),
        )
        if _STRICT_TRANSPORT_SECURITY is not None:
            # Unconditional (not setdefault): unlike CSP there is no legitimate
            # per-route reason to weaken HSTS, so the middleware always wins.
            response.headers["Strict-Transport-Security"] = _STRICT_TRANSPORT_SECURITY
        return response


app.add_middleware(SecurityHeadersMiddleware)

# Body-size bounds for every request — a route's own where it has one, a
# default otherwise — enforced at the ASGI seam so an oversized (or chunked,
# length-less) request is refused before its body is buffered, not after
# FastAPI has already parsed it.
app.add_middleware(BodySizeLimitMiddleware)

# Origin checking for cookie-authenticated writes; see app/core/csrf.py.
#
# Added BEFORE CORSMiddleware. Starlette applies middleware in reverse order of
# addition, so CORS ends up outermost and answers a preflight before this runs.
# A refusal from here carries no Access-Control-Allow-Origin, so a caller whose
# origin is not on the allowlist reads it as a CORS error rather than as the
# 403 body -- which is why the body is a code for logs and same-origin clients.
app.add_middleware(CsrfOriginMiddleware)

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

# Added last, so it sits outside the rest: every request gets its id here,
# whatever answers it, and a request served through a privileged-access grant
# is written down once its response is finished. See app/core/request_audit.py.
app.add_middleware(RequestAuditMiddleware)


@app.get("/uploads/{guild_id}/{filename:path}", include_in_schema=False)
@limiter.limit("600/minute")
async def serve_upload_file(
    request: Request,
    guild_id: int,
    filename: str,
    current_user: Annotated[User, Depends(get_upload_user)],
    session: Annotated[AsyncSession, Depends(get_system_session)],
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
    # without confirming the blob exists.
    from app.db.session import set_rls_context
    from app.db.schema_provisioning import guild_schema_name
    from app.models.platform.guild import LIVE_STATUS_VALUES
    from app.services.platform import access_grants as access_grants_service
    from app.services.platform import guilds as guilds_service

    # A key limited to another guild reaches nothing here, and is told so the
    # way somebody with no access is.
    if pinned_elsewhere(guild_id):
        raise HTTPException(status_code=404)
    membership = await guilds_service.get_membership(
        session, guild_id=guild_id, user_id=current_user.id
    )
    if membership is None:
        grant = await access_grants_service.get_live_grant(
            session, user_id=current_user.id, guild_id=guild_id
        )
        if grant is None:
            raise HTTPException(status_code=404)

    guild = await guilds_service.get_guild(session, guild_id=guild_id)
    if membership is not None and guild.status not in LIVE_STATUS_VALUES:
        # A guild that is not live is unreadable to its members (mirrors the
        # resolver gate in deps._load_guild_context; this route resolves access
        # inline). The grant branch above deliberately skips the status — PAM
        # overrides it. read_only needs nothing here: serving a file is a read.
        raise HTTPException(status_code=404)
    # And the same resolver's question about the credential, which binds
    # members and grantees alike. Asked once access is settled, so it is
    # answered only to somebody who reaches the guild.
    if declines_this_credential(guild):
        raise HTTPException(
            status_code=403, detail=GuildMessages.GUILD_API_KEYS_REFUSED
        )

    # The system login role has NO table grants on a guild schema, so SET ROLE
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
            text("SELECT content_type FROM uploads WHERE filename = :fn LIMIT 1"),
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

    # A stored file never changes under its name — every write, including a
    # new version of a picture, gets a fresh UUID — so the bytes behind a URL
    # are safe to reuse. The decision above them is re-made per request, so
    # the window is short rather than a year: long enough for the repeat
    # requests one session of scrolling a gallery makes, and short enough that
    # access is re-checked while somebody is still reading. ``private`` keeps
    # shared caches out of it, and ``must-revalidate`` bounds the entry to
    # that window.
    headers: dict[str, str] = {
        "Cache-Control": f"private, max-age={UPLOAD_CACHE_SECONDS}, must-revalidate",
        "X-Content-Type-Options": "nosniff",
    }
    # What the file is, as the server recorded it when it was written — so a
    # local blob and an S3 one describe themselves the same way, rather than
    # each backend answering from what it happens to have. A row from before
    # the column existed carries nothing; its name is read instead, and the
    # backend keeps naming the type as it always has.
    stored_type = hit[0]
    inline = (
        stored_type in INLINE_UPLOAD_TYPES
        if stored_type is not None
        else not fname.lower().endswith(NAMED_AS_MARKUP)
    )
    if not inline:
        headers["Content-Disposition"] = "attachment"
        headers["Content-Security-Policy"] = "script-src 'none'"
    logger.info("upload_served filename=%s user=%d", filename, current_user.id)
    return build_upload_response(blob, media_type=stored_type, headers=headers)


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
            "description": "Paste a personal API key issued from Settings → API Keys.",
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


class McpBarePathMiddleware:
    """Serve ``/api/v1/mcp`` as ``/api/v1/mcp/``.

    A Starlette ``Mount`` matches only the trailing-slash spelling, and MCP
    clients differ over which one they send. Rewriting the path in place serves
    both from the one mount, with nothing for the client to follow. Plain ASGI
    rather than ``BaseHTTPMiddleware``, so the streamed body passes through.
    """

    def __init__(self, app: ASGIApp, prefix: str) -> None:
        self.app = app
        self.prefix = prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] == self.prefix:
            scope = {**scope, "path": f"{self.prefix}/"}
        await self.app(scope, receive, send)


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
    app.add_middleware(McpBarePathMiddleware, prefix=f"{API_V1_STR}/mcp")
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
            headers = {"Cache-Control": "public, max-age=31536000, immutable"}
            # The middleware sets the app-wide policy with setdefault, so this
            # per-asset one wins where it applies.
            if _is_wasm_worker_asset(full_path):
                headers["Content-Security-Policy"] = _WASM_WORKER_CSP
            return FileResponse(static_file, headers=headers)
        return FileResponse(
            static_file,
            headers={"Cache-Control": "public, max-age=3600"},
        )
    if static_index_path.is_file():
        # A document is where `frame-src` means anything, so the registered app
        # origins are named here rather than on every response (see
        # app.api.embed_csp). The middleware sets the app-wide policy with
        # setdefault, so this one wins.
        headers = {
            "Cache-Control": "no-cache",
            "Content-Security-Policy": await app_frame_policy(),
        }
        return FileResponse(static_index_path, headers=headers)
    raise HTTPException(status_code=404, detail="SPA bundle not found")
