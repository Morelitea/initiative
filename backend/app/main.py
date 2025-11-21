from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.api import api_router
from app.core.config import settings
from app.db.session import AsyncSessionLocal, run_migrations
from app.services import app_settings as app_settings_service

app = FastAPI(title=settings.PROJECT_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Update with frontend URL(s) in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)


@app.on_event("startup")
async def on_startup() -> None:
    await run_migrations()
    async with AsyncSessionLocal() as session:
        await app_settings_service.get_or_create_app_settings(session)
