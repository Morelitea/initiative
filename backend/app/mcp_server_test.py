"""The in-app MCP server exposes only a curated surface.

Builds the route-backed server from the real app (no DB/network needed) and
asserts the RouteMap curation holds: tools cover only projects/tasks/initiatives
(+ adding a comment), and the *write* surface is exactly the safe allow-list —
no destructive, bulk, AI-generation, or property/tag mutations leak through.
"""

import json

import pytest
from fastmcp.tools.base import ToolResult
from mcp.types import TextContent

from app.main import app
from app.mcp_server import Base64FilterMiddleware, _strip_base64, build_mcp_server

# A tool is a "write" if its operationId begins with one of these verbs.
_WRITE_PREFIXES = (
    "create_",
    "update_",
    "move_",
    "delete_",
    "archive_",
    "duplicate_",
    "reorder_",
    "set_",
    "batch_",
    "generate_",
    "put_",
    "patch_",
    "post_",
    "remove_",
)

# The only mutations the MCP server is allowed to expose (operationId prefixes).
_SAFE_WRITES = {"create_task", "update_task", "move_task", "create_comment"}


def _operation(name: str) -> str:
    """Return the FastAPI handler name from a route-backed operationId.

    operationIds are ``{function}_api_v1_{path}``; splitting on the route
    boundary yields the *exact* function name (e.g. ``create_task``) without
    collapsing multi-word resources — so a hypothetical ``create_task_template``
    leak can't masquerade as the allowed ``create_task``. Returns the whole name
    unchanged if the boundary is absent (then it simply won't match the safe set).
    """
    return name.split("_api_v1_", 1)[0]


@pytest.mark.unit
async def test_mcp_tools_are_curated():
    tools = await build_mcp_server(app).list_tools()
    names = [t.name.lower() for t in tools]

    assert names, "expected the curated tools to be present"

    # Every tool is for an allowed resource (projects / tasks / initiatives, plus
    # adding a comment). Excluded surfaces (admin, auth, settings, documents,
    # queues, users, uploads, grants, …) carry none of these words, so this also
    # proves none of them leaked through.
    allowed = ("project", "task", "initiative", "comment")
    off_list = [n for n in names if not any(a in n for a in allowed)]
    assert not off_list, f"tools outside the allow-list: {off_list}"


@pytest.mark.unit
async def test_mcp_write_tools_are_the_curated_safe_set():
    # Lowercase consistently so a differently-cased operationId can't dodge the
    # write-prefix check.
    names = [t.name.lower() for t in await build_mcp_server(app).list_tools()]

    writes = {_operation(n) for n in names if n.startswith(_WRITE_PREFIXES)}
    # Exactly the safe set — no delete/archive-all/reorder/duplicate/AI/property
    # mutation may appear.
    assert writes == _SAFE_WRITES, f"write surface changed: {sorted(writes)}"


@pytest.mark.unit
def test_strip_base64_removes_suffixed_keys_recursively():
    payload = {
        "title": "t",
        "guild": {"id": 3, "name": "g", "icon_base64": "AAAA"},
        "assignees": [
            {"id": 1, "email": "a@example.com", "avatar_base64": "BBBB"},
            {"id": 2, "email": "b@example.com", "avatar_base64": None},
        ],
        "count_base64_ish": "kept",  # only an exact suffix match is stripped
    }
    stripped = _strip_base64(payload)

    assert "icon_base64" not in stripped["guild"]
    assert all("avatar_base64" not in a for a in stripped["assignees"])
    # Non-base64 fields (including a lookalike key) are preserved.
    assert stripped["guild"] == {"id": 3, "name": "g"}
    assert stripped["assignees"][0] == {"id": 1, "email": "a@example.com"}
    assert stripped["count_base64_ish"] == "kept"
    # Input is not mutated.
    assert "icon_base64" in payload["guild"]


@pytest.mark.unit
async def test_base64_filter_middleware_strips_content_and_structured():
    payload = {"guild": {"icon_base64": "AAAA", "name": "g"}}
    result = ToolResult(
        content=[TextContent(type="text", text=json.dumps(payload))],
        structured_content=payload,
    )

    async def call_next(_context):
        return result

    out = await Base64FilterMiddleware().on_call_tool(None, call_next)

    assert out.structured_content == {"guild": {"name": "g"}}
    assert json.loads(out.content[0].text) == {"guild": {"name": "g"}}


@pytest.mark.unit
async def test_base64_filter_middleware_passes_through_non_json_text():
    result = ToolResult(content=[TextContent(type="text", text="plain not json")])

    async def call_next(_context):
        return result

    out = await Base64FilterMiddleware().on_call_tool(None, call_next)

    assert out.content[0].text == "plain not json"
