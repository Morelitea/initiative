"""Which response shapes may carry an address, and which may not.

``UserRead`` carries a stored address in full and is served on the ``/users/me``
routes, where the reader is the address's owner. Every other route that returns
an account returns ``AdminUserRead``, which masks it. The shapes that carry an
address field alongside other data — the guild invite, the access grant — mask
it too.

These tests read the OpenAPI schema and hold the app to that split, so a new
route or a new shape has to be a deliberate addition to the lists below rather
than something nobody noticed.
"""

import json
from typing import Any, Iterable

import pytest

from app.main import app

pytestmark = pytest.mark.unit

#: The shape that carries a stored address in full, and the routes that serve
#: it — each of them returning the caller their own account.
SELF_SCHEMA = "UserRead"
SELF_ROUTES = {
    "/api/v1/auth/register",
    "/api/v1/users/me",
    "/api/v1/users/me/username",
    "/api/v1/users/me/age-confirmation",
    "/api/v1/users/me/avatar",
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


def test_the_unmasked_shape_is_served_only_on_the_self_routes() -> None:
    """``UserRead`` reaches a response only where the caller owns the account.

    A route serving somebody else's account uses ``AdminUserRead`` instead; one
    that genuinely belongs on the list is added to it explicitly.
    """
    spec = app.openapi()
    schemas = spec["components"]["schemas"]

    leaked = {
        path
        for path, _method, operation in _operations()
        if SELF_SCHEMA in _reachable(operation.get("responses") or {}, schemas)
        and path not in SELF_ROUTES
    }
    assert not leaked, (
        f"{sorted(leaked)} return {SELF_SCHEMA}, which carries the stored "
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

    unaccounted = carrying - MASKED_SHAPES - {SELF_SCHEMA}
    assert not unaccounted, (
        f"{sorted(unaccounted)} carry an address field in a response without "
        "masking it."
    )
