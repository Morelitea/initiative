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
from app.mcp_server import Base64FilterMiddleware, _redact_base64, build_mcp_server

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
def test_redact_base64_nulls_suffixed_keys_recursively():
    payload = {
        "title": "t",
        "guild": {"id": 3, "name": "g", "icon_base64": "AAAA"},
        "assignees": [
            {"id": 1, "email": "a@example.com", "avatar_base64": "BBBB"},
            {"id": 2, "email": "b@example.com", "avatar_base64": None},
        ],
        "count_base64_ish": "kept",  # only an exact suffix match is redacted
    }
    redacted = _redact_base64(payload)

    # Keys are kept but nulled — so the structured output still satisfies a
    # schema that declares (and may require) these fields.
    assert redacted["guild"] == {"id": 3, "name": "g", "icon_base64": None}
    assert [a["avatar_base64"] for a in redacted["assignees"]] == [None, None]
    # Non-base64 fields (including a lookalike key) keep their values.
    assert redacted["assignees"][0]["email"] == "a@example.com"
    assert redacted["count_base64_ish"] == "kept"
    # Input is not mutated.
    assert payload["guild"]["icon_base64"] == "AAAA"


@pytest.mark.unit
async def test_base64_filter_middleware_redacts_content_and_structured():
    payload = {"guild": {"icon_base64": "AAAA", "name": "g"}}
    result = ToolResult(
        content=[TextContent(type="text", text=json.dumps(payload))],
        structured_content=payload,
    )

    async def call_next(_context):
        return result

    out = await Base64FilterMiddleware().on_call_tool(None, call_next)

    assert out.structured_content == {"guild": {"icon_base64": None, "name": "g"}}
    assert json.loads(out.content[0].text) == {
        "guild": {"icon_base64": None, "name": "g"}
    }


@pytest.mark.unit
async def test_list_tools_expose_conditions_and_sorting_as_json_strings():
    # main._inject_query_schemas retypes these to arrays for the REST/Orval
    # surface; the MCP tool must present them as JSON strings instead, or the
    # request builder serializes an array via Python str() (single-quoted) and
    # the backend's json.loads rejects it. Assert every tool that has them uses
    # a string schema.
    tools = await build_mcp_server(app).list_tools()
    seen = 0
    for tool in tools:
        props = (tool.parameters or {}).get("properties", {})
        for name in ("conditions", "sorting"):
            schema = props.get(name)
            if schema is not None:
                seen += 1
                assert schema.get("type") == "string", (
                    f"{tool.name}.{name} should be a JSON string, got {schema}"
                )
    assert seen, "expected at least one tool exposing conditions/sorting"


@pytest.mark.unit
async def test_base64_filter_middleware_passes_through_non_json_text():
    result = ToolResult(content=[TextContent(type="text", text="plain not json")])

    async def call_next(_context):
        return result

    out = await Base64FilterMiddleware().on_call_tool(None, call_next)

    assert out.content[0].text == "plain not json"
