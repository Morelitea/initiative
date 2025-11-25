import asyncio
from contextlib import suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from app.api.v1.api import api_router
from app.core.config import settings
from app.db.session import AsyncSessionLocal, run_migrations
from app.services import app_settings as app_settings_service
from app.services import notifications as notifications_service

app = FastAPI(
    title=settings.PROJECT_NAME,
    docs_url=f"{settings.API_V1_STR}/docs",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Update with frontend URL(s) in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)


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
    await run_migrations()
    async with AsyncSessionLocal() as session:
        await app_settings_service.get_or_create_app_settings(session)
    app.state.notification_tasks = notifications_service.start_background_tasks()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    tasks = getattr(app.state, "notification_tasks", [])
    for task in tasks:
        task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task
