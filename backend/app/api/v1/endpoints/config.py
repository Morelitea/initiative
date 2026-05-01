"""Runtime configuration endpoint.

The SPA fetches this on boot to learn deployment-specific settings that
can't be baked into the static build (Vite vars are compile-time). The
response is intentionally narrow — only public-safe values that affect
UI surfacing.

Unauthenticated: the SPA needs this before any user is logged in.
"""

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings

router = APIRouter()


class AdvancedToolConfig(BaseModel):
    """Plug-in slot for an externally-deployed companion app.

    When ``ADVANCED_TOOL_URL`` is unset on the backend, this whole field is
    ``None`` and the SPA hides the per-initiative toggle and panel entirely.
    """

    name: str
    url: str


class AppConfig(BaseModel):
    """Public, runtime-injected configuration consumed by the SPA at boot."""

    advanced_tool: Optional[AdvancedToolConfig] = None


@router.get("/config", response_model=AppConfig)
def get_app_config() -> AppConfig:
    advanced_tool: Optional[AdvancedToolConfig] = None
    if settings.ADVANCED_TOOL_URL:
        advanced_tool = AdvancedToolConfig(
            name=settings.ADVANCED_TOOL_NAME or "Advanced Tool",
            url=settings.ADVANCED_TOOL_URL,
        )
    return AppConfig(advanced_tool=advanced_tool)
