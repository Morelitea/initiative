"""Which response shapes may carry an address, and which may not.

Two shapes carry a stored address in full: ``UserRead`` on the ``/users/me``
routes, and ``UserEmailRead`` on the routes listing the addresses an account
holds. Both are served only to the address's owner. Every other route that
returns an account returns ``AdminUserRead``, which masks it, and the shapes
that carry an address field alongside other data — the guild invite, the
access grant — mask it too.

These tests read the OpenAPI schema and hold the app to that split, so a new
route or a new shape has to be a deliberate addition to the lists below rather
than something nobody noticed.
"""

import json
from typing import Any, Iterable

import pytest

from app.main import app

pytestmark = pytest.mark.unit

#: Shapes that carry a stored address in full, each mapped to the routes that
#: serve it — every one of them returning the caller their own account.
SELF_SHAPES = {
    "UserRead": {
        "/api/v1/auth/register",
        "/api/v1/users/me",
        "/api/v1/users/me/username",
        "/api/v1/users/me/age-confirmation",
        "/api/v1/users/me/avatar",
    },
    "UserEmailRead": {
        "/api/v1/users/me/emails",
        "/api/v1/users/me/emails/{address_id}/primary",
    },
}

#: Shapes that carry an address field and mask it. Each has a validator
#: applying ``app.core.email_masking.mask_email``; adding a name here means
#: having added that validator.
MASKED_SHAPES = {"AdminUserRead", "AccessGrantRead", "GuildInviteRead"}


def _operations() -> Iterable[tuple[str, str, dict]]:
    spec = app.openapi()
    for path, methods in spec["paths"].items():
        for method, operation in methods.items():
            if isinstance(operation, dict):
                yield path, method, operation


def _referenced_names(node: Any) -> Iterable[str]:
    """Every ``#/components/schemas/<name>`` appearing anywhere under ``node``."""
    text = json.dumps(node)
    prefix = '"#/components/schemas/'
    start = 0
    while (found := text.find(prefix, start)) != -1:
        end = text.find('"', found + len(prefix))
        yield text[found + len(prefix) : end]
        start = end


def _reachable(node: Any, schemas: dict[str, Any]) -> set[str]:
    """Schemas reachable from ``node``, following references transitively.

    A response usually names one shape, but that shape can hold others — a
    paged envelope whose ``items`` are accounts names only the envelope at the
    top level. Walking the whole graph is what makes the two tests below cover
    those as well as the direct case.
    """
    seen: set[str] = set()
    queue = list(_referenced_names(node))
    while queue:
        name = queue.pop()
        if name in seen or name not in schemas:
            continue
        seen.add(name)
        queue.extend(_referenced_names(schemas[name]))
    return seen


def test_the_walk_reaches_a_nested_shape() -> None:
    """The reachability walk is what the two tests below rest on.

    Without this, a walk that silently found nothing would make both of them
    pass by vacuum rather than by being satisfied.
    """
    schemas = {
        "Envelope": {"properties": {"items": {"$ref": "#/components/schemas/Inner"}}},
        "Inner": {"properties": {"email": {"type": "string"}}},
    }
    node = {"200": {"schema": {"$ref": "#/components/schemas/Envelope"}}}
    assert _reachable(node, schemas) == {"Envelope", "Inner"}


def test_the_unmasked_shapes_are_served_only_on_their_own_routes() -> None:
    """An unmasked shape reaches a response only where the caller owns it.

    A route serving somebody else's account uses ``AdminUserRead`` instead; one
    that genuinely belongs on a list is added to it explicitly.
    """
    spec = app.openapi()
    schemas = spec["components"]["schemas"]

    leaked = {
        (name, path)
        for path, _method, operation in _operations()
        for name, own_routes in SELF_SHAPES.items()
        if name in _reachable(operation.get("responses") or {}, schemas)
        and path not in own_routes
    }
    assert not leaked, (
        f"{sorted(leaked)} — these routes return a shape carrying the stored "
        "address. Serve somebody else's account as AdminUserRead."
    )


def test_every_other_address_field_comes_from_a_masking_shape() -> None:
    """Any other address-shaped response field belongs to a shape that masks.

    Covers what the route check cannot: a new shape with an ``…_email`` field,
    reached directly or nested inside another.
    """
    spec = app.openapi()
    schemas = spec["components"]["schemas"]

    returned: set[str] = set()
    for _path, _method, operation in _operations():
        returned |= _reachable(operation.get("responses") or {}, schemas)

    carrying = {
        name
        for name in returned
        for field in (schemas[name].get("properties") or {})
        if "email" in field.lower() and field != "email_verified"
    }

    unaccounted = carrying - MASKED_SHAPES - set(SELF_SHAPES)
    assert not unaccounted, (
        f"{sorted(unaccounted)} carry an address field in a response without "
        "masking it."
    )
