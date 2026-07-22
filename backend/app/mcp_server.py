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

import json
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.server.providers.openapi import MCPType, RouteMap
from fastmcp.tools.base import ToolResult
from mcp.types import TextContent

from app.core.config import PROJECT_NAME

if TYPE_CHECKING:
    import mcp.types as mt
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


# Base64 image blobs (avatar/guild icons) can dwarf the useful part of a
# payload — a single guild ``icon_base64`` is often larger than the rest of a
# task read combined. They're never actionable to an MCP client, so strip any
# ``*_base64`` field before the result reaches the caller, keeping the context
# they consume for the fields that matter.
_BASE64_SUFFIX = "_base64"


def _strip_base64(value: Any) -> Any:
    """Recursively drop any dict key ending in ``_base64``.

    Returns a new structure; the input is left untouched. Matching by suffix
    (not a fixed name list) means a future base64 field is filtered by
    construction, without another edit here.
    """
    if isinstance(value, dict):
        return {
            k: _strip_base64(v)
            for k, v in value.items()
            if not (isinstance(k, str) and k.endswith(_BASE64_SUFFIX))
        }
    if isinstance(value, list):
        return [_strip_base64(v) for v in value]
    return value


class Base64FilterMiddleware(Middleware):
    """Strip ``*_base64`` fields from every tool result.

    Route-backed tools return the raw route JSON, which carries avatar/guild
    icon data URIs. Filtering here — after the route (and its RLS gates) have
    run — is purely cosmetic to the payload: it removes only inert image blobs,
    never anything a caller acts on.
    """

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        result = await call_next(context)

        structured = result.structured_content
        if structured is not None:
            structured = _strip_base64(structured)

        content: list[Any] = []
        for block in result.content:
            # Text blocks hold the JSON body for route-backed tools; strip the
            # parsed form and re-serialize. Non-JSON text and non-text blocks
            # pass through untouched.
            if isinstance(block, TextContent):
                try:
                    parsed = json.loads(block.text)
                except (ValueError, TypeError):
                    content.append(block)
                    continue
                content.append(
                    TextContent(
                        type="text",
                        text=json.dumps(_strip_base64(parsed), default=str),
                    )
                )
            else:
                content.append(block)

        return ToolResult(
            content=content,
            structured_content=structured,
            meta=result.meta,
            is_error=result.is_error,
        )


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
    server = FastMCP.from_fastapi(
        app=app,
        name=PROJECT_NAME,
        route_maps=_ROUTE_MAPS,
        httpx_client_kwargs={"event_hooks": {"request": [_forward_authorization]}},
    )
    server.add_middleware(Base64FilterMiddleware())
    return server
