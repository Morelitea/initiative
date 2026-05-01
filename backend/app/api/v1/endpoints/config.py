"""Runtime configuration endpoint.

The SPA fetches this on boot to learn deployment-specific settings that
can't be baked into the static build (Vite vars are compile-time). The
response is intentionally narrow — only public-safe values that affect
UI surfacing.

Unauthenticated: the SPA needs this before any user is logged in.
"""

from typing import List, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings

router = APIRouter()


class AdvancedToolConfig(BaseModel):
    """Plug-in slot for an externally-deployed companion app.

    When ``ADVANCED_TOOL_URL`` is unset on the backend, this whole field is
    ``None`` and the SPA hides the per-initiative toggle and panel entirely.

    ``allowed_origins`` is the SPA's inbound postMessage allowlist.
    Defaults to the single origin derived from ``url`` so deployments
    work without extra config. Operators can override via
    ``ADVANCED_TOOL_ALLOWED_ORIGINS`` when the embed sits behind a CDN
    that surfaces multiple origins (e.g. region-sharded subdomains).
    Outbound postMessage is always scoped to the iframe's actual origin
    (derived from ``url``), never to anything in this list.
    """

    name: str
    url: str
    allowed_origins: List[str]


class AppConfig(BaseModel):
    """Public, runtime-injected configuration consumed by the SPA at boot."""

    advanced_tool: Optional[AdvancedToolConfig] = None


def _origin_from_url(url: str) -> str:
    """Extract the ``scheme://host[:port]`` origin from a full URL.

    Mirrors what ``new URL(url).origin`` returns in the browser, so the
    default allowlist matches the SPA's existing inbound check.
    """
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


@router.get("/config", response_model=AppConfig)
def get_app_config() -> AppConfig:
    advanced_tool: Optional[AdvancedToolConfig] = None
    if settings.ADVANCED_TOOL_URL:
        configured = settings.ADVANCED_TOOL_ALLOWED_ORIGINS or []
        # Always include the iframe's own origin so a misconfigured
        # ALLOWED_ORIGINS list can't lock the SPA out of its own embed.
        url_origin = _origin_from_url(settings.ADVANCED_TOOL_URL)
        allowed = list(dict.fromkeys([url_origin, *configured]))  # de-dup, preserve order
        advanced_tool = AdvancedToolConfig(
            name=settings.ADVANCED_TOOL_NAME or "Advanced Tool",
            url=settings.ADVANCED_TOOL_URL,
            allowed_origins=allowed,
        )
    return AppConfig(advanced_tool=advanced_tool)
