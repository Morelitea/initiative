import asyncio
from contextlib import suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.v1.api import api_router
from app.core.rate_limit import limiter
from app.core.config import settings
from app.core.version import __version__
from app.db.session import AdminSessionLocal, run_migrations
from app.services import app_settings as app_settings_service
from app.services import background_tasks as background_tasks_service

uploads_path = Path(settings.UPLOADS_DIR)
uploads_path.mkdir(parents=True, exist_ok=True)
static_path = Path(settings.STATIC_DIR)
static_path.mkdir(parents=True, exist_ok=True)
static_index_path = static_path / "index.html"
static_root = static_path.resolve()
reserved_prefixes = [
    prefix.strip("/")
    for prefix in {settings.API_V1_STR, "/uploads"}
    if prefix and prefix.strip("/")
]

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=__version__,
    docs_url=f"{settings.API_V1_STR}/docs",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    redoc_url=None,
)

# Initialize rate limiter (uses shared limiter from app.core.rate_limit)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Update with frontend URL(s) in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def svg_security_headers(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/uploads/") and request.url.path.lower().endswith(".svg"):
        response.headers["Content-Disposition"] = "attachment"
        response.headers["Content-Security-Policy"] = "script-src 'none'"
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response

app.mount("/uploads", StaticFiles(directory=str(uploads_path), check_dir=False), name="uploads")
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
        return FileResponse(static_file)
    if static_index_path.is_file():
        return FileResponse(static_index_path)
    raise HTTPException(status_code=404, detail="SPA bundle not found")


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

    for path_item in openapi_schema.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            security = operation.get("security")
            if not security:
                continue
            has_api_key = any(isinstance(item, dict) and "ApiKeyAuth" in item for item in security)
            if not has_api_key:
                security.append({"ApiKeyAuth": []})

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


@app.on_event("startup")
async def on_startup() -> None:
    from app.db.init_db import check_pre_baseline_db
    await check_pre_baseline_db()
    await run_migrations()
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
