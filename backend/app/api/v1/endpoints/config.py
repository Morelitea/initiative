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


# Default ports the WHATWG URL spec strips from origin strings. If the
# operator includes ``:443`` or ``:80`` explicitly in ADVANCED_TOOL_URL,
# we drop it here so the allowlist matches what the browser will compare
# ``event.origin`` against (browsers normalize default ports out).
_DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443}


def _origin_from_url(url: str) -> str:
    """Extract the ``scheme://host[:port]`` origin from a full URL.

    Mirrors what ``new URL(url).origin`` returns in the browser, including
    the WHATWG default-port normalization (``:443`` for ``https`` and
    ``:80`` for ``http`` are stripped from the origin), so the allowlist
    we hand to the SPA always matches the values the browser will produce
    for inbound postMessage events.
    """
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port
    if port is not None and port != _DEFAULT_PORTS.get(parts.scheme):
        return f"{parts.scheme}://{host}:{port}"
    return f"{parts.scheme}://{host}"


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
