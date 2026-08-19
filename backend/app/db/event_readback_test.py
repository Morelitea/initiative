"""Every resource the bus can name has to be fetchable by that name.

An event envelope carries ``resource: {type, id}`` and nothing else — no parent,
no path. That is what lets it stay content-free: the subscriber reads the state
back through the API, where the gates decide. It only works if the id is a whole
address, so the route for a resource type is derivable from the type itself:

    resource_type -> /g/{guild_id}/<kebab>/{id}

Which is not a convention invented here — it is what the resources that already
worked all do. Sub-resources with an id of their own (``subtasks``,
``comments``) are flat for exactly this reason; a nested path would demand a
parent the envelope never carries.

Anything that is a facet rather than a resource — a project's statuses, a
document's versions, a task's tags — reports against the parent instead (see
``ReportsAs``), so it needs no route of its own and never reaches this test.
Between the two, a new evented table owes no new API surface.
"""

from __future__ import annotations

import pytest

from app.db.base import *  # noqa: F401,F403 — register every model
from app.db.event_capture import build_specs
from app.main import app

pytestmark = pytest.mark.unit


def _detail_paths() -> set[str]:
    """Guild-scoped detail GETs, as ``<segment>`` for ``/<segment>/{id}``."""
    found: set[str] = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if "GET" not in methods or "/g/{guild_id}/" not in path:
            continue
        tail = path.split("/g/{guild_id}/", 1)[1]
        parts = tail.split("/")
        # Exactly "<segment>/{param}" — one hop, then the id.
        if (
            len(parts) == 2
            and not parts[0].startswith("{")
            and parts[1].startswith("{")
        ):
            found.add(parts[0])
    return found


def _named_resources() -> set[str]:
    return {r for spec in build_specs() for r in spec.resource_types}


def test_every_evented_resource_resolves_by_its_own_id():
    paths = _detail_paths()
    missing = sorted(r for r in _named_resources() if r.replace("_", "-") not in paths)
    assert not missing, (
        f"{missing} emit events naming ids nothing can fetch. Either add "
        f"GET /g/{{guild_id}}/<kebab>/{{id}}, or report the table against a "
        "parent that has one (Emit(reports_as=...))."
    )
