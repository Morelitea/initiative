"""No response hands somebody else's address back in full.

An address is the one identifier here that also reaches a person off the
platform, and the one worth most to whoever compromises a staff account.
Masking it in the SPA would be theatre — the response is a keystroke away in
the network tab — so it is reduced server-side, by the response *shapes*
(``app.core.email_masking``), and this is the test that keeps it that way.

The rule is not "no address anywhere": you are entitled to your own, and
``/users/me`` is where the account screen reads it. So the invariant is about
*whose* address a route can return, and it is enforced by which schema the
route declares.
"""

import json

import pytest

from app.main import app

pytestmark = pytest.mark.unit

#: The only schema allowed to carry a full address, and the only routes allowed
#: to return it — every one of them serves the caller their own account.
SELF_SCHEMA = "UserRead"
SELF_ROUTES = {
    "/api/v1/auth/register",
    "/api/v1/users/me",
    "/api/v1/users/me/username",
    "/api/v1/users/me/age-confirmation",
    "/api/v1/users/me/avatar",
}


def _response_schemas(operation: dict) -> str:
    return json.dumps(operation.get("responses") or {})


def _operations():
    spec = app.openapi()
    for path, methods in spec["paths"].items():
        for method, operation in methods.items():
            if isinstance(operation, dict):
                yield path, method, operation


def test_full_addresses_are_confined_to_self_routes() -> None:
    """``UserRead`` is the unmasked shape; only your own account is served it.

    A new endpoint that returns ``UserRead`` for anybody but the caller shows
    up here rather than in production. If one belongs on the list, adding it
    is a deliberate act — which is the point.
    """
    leaked = {
        path
        for path, _method, operation in _operations()
        if f'"#/components/schemas/{SELF_SCHEMA}"' in _response_schemas(operation)
        and path not in SELF_ROUTES
    }
    assert not leaked, (
        f"{sorted(leaked)} return the unmasked {SELF_SCHEMA}. Serve somebody "
        "else's account as AdminUserRead, which masks the address."
    )


def test_every_other_address_field_is_declared_on_a_masking_shape() -> None:
    """Any *other* address-shaped response field must come from a masked shape.

    Catches the case the route-level check can't: a brand-new schema with an
    ``…_email`` field on it, which would sail through unmasked.
    """
    spec = app.openapi()
    schemas = spec["components"]["schemas"]

    returned: set[str] = set()
    for _path, _method, operation in _operations():
        body = _response_schemas(operation)
        returned.update(
            name for name in schemas if f'"#/components/schemas/{name}"' in body
        )

    # Shapes that mask every address they carry, each with a validator that
    # runs ``mask_email``. Adding a name here means having added that
    # validator.
    masked_shapes = {"AdminUserRead", "AccessGrantRead", "GuildInviteRead"}

    carrying = {
        name
        for name in returned
        for field in (schemas[name].get("properties") or {})
        if "email" in field.lower() and field != "email_verified"
    }

    assert carrying <= masked_shapes | {SELF_SCHEMA}, (
        f"{sorted(carrying - masked_shapes - {SELF_SCHEMA})} carry an address "
        "field in a response without masking it."
    )
