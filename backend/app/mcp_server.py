"""In-app MCP server.

Mounted at ``/api/v1/mcp/`` only when ``settings.ENABLE_MCP`` is set. Tools are
*route-backed*: each call flows through the real FastAPI route, so the PAT
authentication and the six RLS gates apply by reuse — never re-implemented.

The surface is curated and default-deny, so a newly added route can't silently
become a tool:
  * **Reads** — every ``GET`` route for projects, tasks, and initiatives.
  * **Writes** — a small, explicit allow-list of safe mutations (create a task,
    edit a task, move a task, add a comment), each gated client-side by Claude
    Code's per-write permission prompt. Destructive (delete), bulk (archive-all,
    reorder), AI-generation, and property/tag routes are deliberately excluded.

See ``history/mcp-server-design.md``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.providers.openapi import MCPType, RouteMap

from app.core.config import settings

if TYPE_CHECKING:
    from fastapi import FastAPI

# Read surface: every GET route carrying these FastAPI tags becomes a tool.
READ_TAGS = ("projects", "tasks", "initiatives")

# Curated safe writes: an explicit allow-list matched by exact path *shape* so
# only these four mutations are exposed — create a task (``POST /tasks/``), edit a
# task (``PATCH /tasks/{id}``), move a task (``POST /tasks/{id}/move``), and add a
# comment (``POST /comments/``). Everything else (delete, archive-all, reorder,
# duplicate, AI-generation, properties/tags, subtasks) falls through to the
# default-deny catch-all below.
_WRITE_ROUTE_MAPS = [
    RouteMap(methods=["POST"], pattern=r".*/tasks/$", mcp_type=MCPType.TOOL),
    RouteMap(methods=["PATCH"], pattern=r".*/tasks/\{[^}]+\}$", mcp_type=MCPType.TOOL),
    RouteMap(
        methods=["POST"], pattern=r".*/tasks/\{[^}]+\}/move$", mcp_type=MCPType.TOOL
    ),
    RouteMap(methods=["POST"], pattern=r".*/comments/$", mcp_type=MCPType.TOOL),
]

_ROUTE_MAPS = [
    *_WRITE_ROUTE_MAPS,
    *(
        RouteMap(methods=["GET"], tags={tag}, mcp_type=MCPType.TOOL)
        for tag in READ_TAGS
    ),
    # Default-deny: anything not opted in above is excluded.
    RouteMap(pattern=r".*", mcp_type=MCPType.EXCLUDE),
]


async def _forward_authorization(request: httpx.Request) -> None:
    """Forward the caller's PAT to the in-process upstream route call.

    FastMCP strips ``authorization`` from forwarded headers by default; re-add it
    explicitly so the FastAPI route authenticates the caller and RLS scopes the
    request to *their* identity — never a shared or static token.
    """
    auth = get_http_headers(include={"authorization"}).get("authorization")
    if auth:
        request.headers["authorization"] = auth


def build_mcp_server(app: "FastAPI") -> FastMCP:
    """Build the route-backed, read-only MCP server from the FastAPI ``app``.

    The app must already have its routers included so the RouteMap can see them.
    """
    return FastMCP.from_fastapi(
        app=app,
        name=settings.PROJECT_NAME,
        route_maps=_ROUTE_MAPS,
        httpx_client_kwargs={"event_hooks": {"request": [_forward_authorization]}},
    )
