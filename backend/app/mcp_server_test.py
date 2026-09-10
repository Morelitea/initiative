"""The in-app MCP server exposes only a curated surface.

Builds the route-backed server from the real app (no DB/network needed) and
asserts the RouteMap curation holds: tools cover initiatives and the tools they
hold (+ the shared comment surface), and the *write* surface is exactly the
allow-list — create and edit each of those, and nothing destructive, bulk,
AI-generating, sharing, or property/tag.
"""

import json

import pytest
from fastmcp.tools.base import ToolResult
from mcp.types import TextContent

from app.core.tools import Tool
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
    "add_",
    "increment_",
    "decrement_",
    "reset_",
    "upload_",
    "import_",
    "copy_",
    "vote_",
    "start_",
    "stop_",
    "sort_",
    "advance_",
    "hold_",
    "release_",
    "upgrade_",
)

# The only mutations the MCP server is allowed to expose (handler names).
_SAFE_WRITES = {
    # Every tool an initiative holds: author it and edit it.
    "create_project",
    "update_project",
    "create_document",
    "update_document",
    "create_queue",
    "update_queue",
    "create_counter_group",
    "update_counter_group",
    "create_calendar",
    "update_calendar",
    "create_dashboard",
    "update_dashboard",
    "create_post",
    "update_post",
    # A gallery is authored and renamed here, and filled elsewhere: putting a
    # picture in one is a multipart upload, which no RouteMap matches, so the
    # write surface stops at the wall itself.
    "create_gallery",
    "update_gallery",
    # And what those tools hold: a project's tasks, a queue's items, a counter
    # group's counters, a calendar's events, and the comments on any of them.
    "create_task",
    "update_task",
    "move_task",
    "add_queue_item",
    "update_queue_item",
    "add_counter",
    "update_counter",
    "create_calendar_event",
    "update_calendar_event",
    "create_comment",
    "update_comment",
    # A counter's count, which its update schema doesn't carry.
    "set_counter_count",
    "increment_counter",
    "decrement_counter",
}


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

    # Every tool is for an initiative, one of the tools an initiative holds, or
    # the comment surface they share. Everything else (admin, auth, settings,
    # users, uploads, grants, …) carries none of these words, so this also
    # proves none of them leaked through.
    allowed = (
        "initiative",
        "comment",
        # The things a tool holds, which the enum names only their parent of:
        # a task belongs to a project, a counter to a counter group.
        "task",
        "counter",
        "backlink",
        "widget",
        *(tool.value for tool in Tool),
        *(tool.plural for tool in Tool),
    )
    off_list = [n for n in names if not any(a in n for a in allowed)]
    assert not off_list, f"tools outside the allow-list: {off_list}"

    # And every tool an initiative holds is readable. Derived from the enum
    # rather than listed, so a seventh kind arrives here as a failure rather
    # than as a surface nobody remembered to open.
    for tool in Tool:
        stem = tool.value.replace("_", "")
        assert any(stem in n.replace("_", "") for n in names), (
            f"no MCP tool reads {tool.value}"
        )

    # Join requests sit on the initiatives router and would otherwise ride in on
    # its tag, but they name who asked to be let in and quote their note — a
    # manager's queue, not a working surface. Carved out explicitly.
    assert not [n for n in names if "join_request" in n]


@pytest.mark.unit
async def test_the_tool_reads_stop_short_of_these():
    """What riding in on a tag would have brought, and why each stays out.

    Opening a tool's tag exposes every GET it carries, and a few of those are
    not the working surface the rest are. Named here so removing one is a
    decision somebody makes rather than a line that quietly stops matching.
    """
    names = [t.name.lower() for t in await build_mcp_server(app).list_tools()]

    # Bytes rather than an answer: a document, one of its versions, a calendar
    # file. None is something a tool result carries usefully.
    assert not [n for n in names if "download" in n or "export" in n]
    # People rather than work: who voted which way, who has read a notice.
    assert not [n for n in names if "voter" in n or n.endswith("_reads")]
    # The dashboard editor's own vocabulary, not anything a dashboard shows.
    assert not [n for n in names if "widget_catalog" in n or "installed_listing" in n]

    # The one that has to be present, because it is the whole point of reading
    # a dashboard: what a tile on it currently says.
    assert any("run_widget_query" in n for n in names)


@pytest.mark.unit
async def test_comment_reads_are_exposed():
    """The two reads that pair with the comment write, and only those.

    ``comments`` is deliberately not a READ_TAG: the router's other two GETs
    (the guild-wide ``recent`` activity feed and the @-mention picker's search)
    are matched by no RouteMap and fall through the default-deny catch-all.
    """
    names = {
        _operation(t.name.lower()) for t in await build_mcp_server(app).list_tools()
    }

    assert "list_comments" in names
    assert "read_comment" in names
    assert "recent_comments" not in names
    assert "search_mentionables" not in names


@pytest.mark.unit
async def test_mcp_write_tools_are_the_curated_safe_set():
    # Lowercase consistently so a differently-cased operationId can't dodge the
    # write-prefix check.
    names = [t.name.lower() for t in await build_mcp_server(app).list_tools()]

    writes = {_operation(n) for n in names if n.startswith(_WRITE_PREFIXES)}
    # Exactly the allow-list — no delete/archive/reset/reorder/duplicate/batch,
    # no AI generation, no grants, no property or tag mutation.
    assert writes == _SAFE_WRITES, f"write surface changed: {sorted(writes)}"

    # Every tool is writable, derived from the enum rather than read back off
    # the set above, so an eighth tool arrives here as a failure rather than as
    # a tool nobody remembered to make writable.
    for tool in Tool:
        assert f"create_{tool.value}" in writes, f"no MCP tool creates {tool.value}"
        assert f"update_{tool.value}" in writes, f"no MCP tool edits {tool.value}"


@pytest.mark.unit
async def test_the_tool_writes_stop_short_of_these():
    """What create-and-edit deliberately doesn't reach.

    Named here so removing one is a decision somebody makes rather than a line
    that quietly stops matching. The equality assertion above covers all of it;
    these spell out the categories that were weighed.
    """
    names = [t.name.lower() for t in await build_mcp_server(app).list_tools()]
    writes = {_operation(n) for n in names if n.startswith(_WRITE_PREFIXES)}

    # Nothing that removes or empties: delete, trash, archive, reset a counter
    # or a queue, discard the done column.
    assert not [w for w in writes if w.startswith(("delete_", "archive_", "reset_"))]
    # Nothing that acts on a whole collection at once.
    assert not [
        w for w in writes if w.startswith(("reorder_", "batch_", "sort_", "duplicate_"))
    ]
    # Sharing is a decision about people, made in the app: no grants, no
    # publishing a dashboard figure, no pinning a notice guild-wide.
    assert not [w for w in writes if w.endswith("_grants")]
    assert "set_published_view" not in writes
    assert "set_post_pin" not in writes
    # Speaking for somebody: voting in a poll, marking a notice read, RSVPing.
    assert not [w for w in writes if w.startswith("vote_") or w.endswith("_rsvp")]
    assert "mark_posts_read" not in writes
    assert "set_attendees" not in writes
    # Whole-set replacements and generated prose stay out, as they were.
    assert not [w for w in writes if w.endswith(("_tags", "_properties"))]
    assert not [w for w in writes if w.startswith("generate_")]
    # A project's status columns are its shape, set up in the app; a task is
    # placed into one by reading them.
    assert "create_task_status" not in writes
    assert "update_task_status" not in writes


@pytest.mark.unit
def test_redact_base64_nulls_suffixed_keys_recursively():
    payload = {
        "title": "t",
        "guild": {"id": 3, "name": "g", "avatar_base64": "AAAA"},
        "assignees": [
            {"id": 1, "email": "a@example.com", "avatar_base64": "BBBB"},
            {"id": 2, "email": "b@example.com", "avatar_base64": None},
        ],
        "count_base64_ish": "kept",  # only an exact suffix match is redacted
    }
    redacted = _redact_base64(payload)

    # Keys are kept but nulled — so the structured output still satisfies a
    # schema that declares (and may require) these fields.
    assert redacted["guild"] == {"id": 3, "name": "g", "avatar_base64": None}
    assert [a["avatar_base64"] for a in redacted["assignees"]] == [None, None]
    # Non-base64 fields (including a lookalike key) keep their values.
    assert redacted["assignees"][0]["email"] == "a@example.com"
    assert redacted["count_base64_ish"] == "kept"
    # Input is not mutated.
    assert payload["guild"]["avatar_base64"] == "AAAA"


@pytest.mark.unit
async def test_base64_filter_middleware_redacts_content_and_structured():
    payload = {"guild": {"avatar_base64": "AAAA", "name": "g"}}
    result = ToolResult(
        content=[TextContent(type="text", text=json.dumps(payload))],
        structured_content=payload,
    )

    async def call_next(_context):
        return result

    out = await Base64FilterMiddleware().on_call_tool(None, call_next)

    assert out.structured_content == {"guild": {"avatar_base64": None, "name": "g"}}
    assert json.loads(out.content[0].text) == {
        "guild": {"avatar_base64": None, "name": "g"}
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
