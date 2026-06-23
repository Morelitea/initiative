"""The in-app MCP server exposes only a curated surface.

Builds the route-backed server from the real app (no DB/network needed) and
asserts the RouteMap curation holds: tools cover only projects/tasks/initiatives
(+ adding a comment), and the *write* surface is exactly the safe allow-list —
no destructive, bulk, AI-generation, or property/tag mutations leak through.
"""

import pytest

from app.main import app
from app.mcp_server import build_mcp_server

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
    "post_",
    "remove_",
)

# The only mutations the MCP server is allowed to expose (operationId prefixes).
_SAFE_WRITES = {"create_task", "update_task", "move_task", "create_comment"}


def _base(name: str) -> str:
    """``create_task_api_v1_g…`` -> ``create_task`` (verb + resource)."""
    return "_".join(name.split("_")[:2])


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
    tools = await build_mcp_server(app).list_tools()
    names = [t.name for t in tools]

    writes = {_base(n) for n in names if n.startswith(_WRITE_PREFIXES)}
    # Exactly the safe set — no delete/archive-all/reorder/duplicate/AI/property
    # mutation may appear.
    assert writes == _SAFE_WRITES, f"write surface changed: {sorted(writes)}"
