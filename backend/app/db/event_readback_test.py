"""Every resource the bus can name has to be fetchable by that name.

An event envelope carries ``resource: {type, id}`` and nothing else — no parent,
no path. That is what lets it stay content-free: the subscriber reads the state
back through the API, where the gates decide. It only works if the id is a whole
address, so the route for a resource type is derivable from the type itself:

    resource_type -> /g/{guild_id}/<kebab>/{id}

Which is not a convention invented here — it is what the thirteen resources that
already worked all do. Sub-resources with an id of their own (``subtasks``,
``comments``) are flat for exactly this reason; a nested path would demand a
parent the envelope never carries.

This test is the drift guard. A new evented table starts naming ids immediately,
and without something asserting it, the route to resolve them is easy to forget —
which is how four of them shipped unresolvable.
"""

from __future__ import annotations

import pytest

from app.db.base import *  # noqa: F401,F403 — register every model
from app.db.event_capture import build_specs
from app.main import app

pytestmark = pytest.mark.unit


#: Evented resources with no detail route yet, and why. Stated as an exclusion
#: so the default is "a new resource must be resolvable": adding one to
#: INITIATIVE_PATHS makes this test fail until it has a route or an entry here.
#:
#: Each of these is arguably a facet of its parent rather than a resource in its
#: own right — a project's statuses, an initiative's roles, a document's version
#: history, a resource's sharing — and reporting them against that parent (the
#: way junction tables already are) would suit a subscriber better than a route
#: each. Left as-is deliberately until someone wants them.
UNRESOLVABLE: dict[str, str] = {
    "task_statuses": "a project's workflow; better reported against the project",
    "initiative_roles": "an initiative's role set; better reported against it",
    "document_file_versions": "a document's history; better reported against it",
    "resource_grants": "a resource's sharing; better reported against that resource",
}


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


def test_every_evented_resource_resolves_by_its_own_id():
    resources = {spec.resource_type for spec in build_specs()}
    paths = _detail_paths()

    missing = sorted(
        r
        for r in resources
        if r.replace("_", "-") not in paths and r not in UNRESOLVABLE
    )
    assert not missing, (
        f"{missing} emit events naming ids nothing can fetch. Add "
        f"GET /g/{{guild_id}}/<kebab>/{{id}} for each, or record it in "
        "UNRESOLVABLE with the reason."
    )


def test_the_unresolvable_list_has_not_gone_stale():
    """An entry that grew a route should leave the list, or it reads as a
    standing gap when it is not one."""
    paths = _detail_paths()
    now_resolvable = sorted(r for r in UNRESOLVABLE if r.replace("_", "-") in paths)
    assert not now_resolvable, (
        f"{now_resolvable} have detail routes now — drop them from UNRESOLVABLE"
    )


def test_unresolvable_names_are_real_resources():
    """Guards the other direction: a typo'd or renamed entry would silently
    excuse a resource that is actually unresolvable."""
    resources = {spec.resource_type for spec in build_specs()}
    unknown = sorted(set(UNRESOLVABLE) - resources)
    assert not unknown, f"{unknown} are not evented resource types"
