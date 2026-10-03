"""The app API's document, held to the routes it is cut from."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from httpx import AsyncClient

from app.api.app_openapi import COMMUNITY_PREFIX, build_app_openapi
from app.api.deps import ActorContext, app_scope, route_app_scope_declaration
from app.main import app, app_openapi

_APP_DIR = Path(__file__).resolve().parent.parent

#: Where a person is written for an installed app.
_APP_PERSON_WRITES = {
    # Every shape the app API's document types as ``AppPerson``.
    "schemas/platform/user.py:PersonShape._as_app_person",
    # ``value`` holds whatever the property's type stores; a person for a
    # ``user_reference`` property, which the field's description states.
    "schemas/tenant/property.py:PropertySummary._value_out",
}

#: What says who a person is, beside the reference that names them.
_PERSON_DETAILS = {
    "username",
    "discriminator",
    "display_name",
    "avatar_url",
    "name",
    "full_name",
    "email",
}


def _nodes(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from _nodes(item)


@pytest.mark.always
def test_every_app_route_is_in_the_app_document_once_with_its_scope():
    main = app.openapi()
    expected: dict[str, tuple[str, str, Any]] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.include_in_schema:
            continue
        declaration = route_app_scope_declaration(route)
        for method in route.methods:
            operation = main["paths"][route.path_format][method.lower()]
            assert operation.get("x-app-scope") == declaration, route.path_format
            if declaration is not None:
                path = route.path_format.removeprefix(COMMUNITY_PREFIX)
                expected[route.name] = (method.lower(), path, declaration)

    published = [
        (operation["operationId"], (method, path, operation["x-app-scope"]))
        for path, item in app_openapi()["paths"].items()
        for method, operation in item.items()
    ]
    assert dict(published) == expected
    assert len(published) == len(expected)
    shapes = {type(scope).__name__ for _, _, scope in expected.values()}
    assert shapes == {"str", "dict"}


@pytest.mark.always
def test_the_app_document_names_no_community_and_no_row_id():
    document = app_openapi()
    assert document["servers"] == [{"url": "/api/v1/c/0"}]
    for item in document["paths"].values():
        for operation in item.values():
            names = {p["name"] for p in operation.get("parameters", ())}
            assert "guild_id" not in names, operation["operationId"]
    identities = [node for node in _nodes(document) if "x-identity" in node]
    assert identities
    assert all(node["type"] == "string" for node in identities)


@pytest.mark.always
def test_every_reference_in_the_app_document_resolves_in_it():
    document = app_openapi()
    schemas = document["components"]["schemas"]
    refs = {node["$ref"] for node in _nodes(document) if "$ref" in node}
    assert refs
    prefix = "#/components/schemas/"
    unresolved = {
        ref
        for ref in refs
        if not (ref.startswith(prefix) and ref.removeprefix(prefix) in schemas)
    }
    assert not unresolved


def test_two_app_routes_with_one_name_fail_the_build():
    probe = FastAPI()

    async def handler(
        actor: Annotated[ActorContext, Depends(app_scope("projects:read"))],
    ) -> None:
        return None

    probe.add_api_route(f"{COMMUNITY_PREFIX}/a", handler, name="same")
    probe.add_api_route(f"{COMMUNITY_PREFIX}/b", handler, name="same")
    with pytest.raises(RuntimeError, match="GET /a and GET /b"):
        build_app_openapi(probe.openapi(), probe.routes)


def _names_a_person(field: Any) -> bool:
    return any(node.get("x-identity") == "person" for node in _nodes(field))


def _draws_a_person(properties: dict[str, Any]) -> bool:
    """Whether an object with ``properties`` names a person and says who they
    are. ``name`` beside an ``id`` of the object's own is the object's name."""
    details = _PERSON_DETAILS & set(properties)
    if "id" in properties and not _names_a_person(properties["id"]):
        details.discard("name")
    return bool(details) and any(map(_names_a_person, properties.values()))


@pytest.mark.always
def test_every_person_in_the_app_document_is_an_app_person():
    schemas = app_openapi()["components"]["schemas"]
    drawn = {
        name
        for name, schema in schemas.items()
        for node in _nodes(schema)
        if _draws_a_person(node.get("properties", {}))
    }
    assert drawn == {"AppPerson"}
    assert not [name for name, schema in schemas.items() if schema.get("x-person")]


def _app_person_writes(node: ast.AST, scope: tuple[str, ...] = ()) -> Iterator[str]:
    """Where under ``node`` ``for_install`` is called, by the names of the
    classes and functions around each call."""
    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        scope = (*scope, node.name)
    if isinstance(node, ast.Call):
        called = node.func
        name = called.attr if isinstance(called, ast.Attribute) else None
        if isinstance(called, ast.Name):
            name = called.id
        if name == "for_install":
            yield ".".join(scope)
    for child in ast.iter_child_nodes(node):
        yield from _app_person_writes(child, scope)


@pytest.mark.always
def test_every_app_person_write_is_listed():
    found = {
        f"{path.relative_to(_APP_DIR).as_posix()}:{where}"
        for path in _APP_DIR.rglob("*.py")
        if not path.name.endswith("_test.py")
        for where in _app_person_writes(ast.parse(path.read_text()))
    }
    assert found == _APP_PERSON_WRITES


async def test_the_app_document_and_its_page_are_served(client: AsyncClient):
    document = await client.get("/api/v1/app-platform/openapi.json")
    assert document.status_code == 200
    assert document.json() == app_openapi()
    page = await client.get("/api/v1/app-platform/docs")
    assert page.status_code == 200
    assert "/api/v1/app-platform/openapi.json" in page.text
    assert "https://cdn.jsdelivr.net" in page.headers["content-security-policy"]
