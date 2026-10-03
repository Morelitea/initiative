"""The app API's document: the routes an installed app may call, as it calls
them.

The main document marks each operation an app may call with ``x-app-scope``,
read from the route's scope dependency (:func:`mark_app_scopes`). The app's
document (:func:`build_app_openapi`) is cut from it:

- only the marked operations, and the component schemas they reach;
- every identity field (``x-identity``) is a string, the install's reference;
- every shape that draws a person (``x-person``) is ``AppPerson``, which is
  what an install receives in its place;
- every field that mentions people (``x-mentions``) says how it names them;
- paths start after ``/api/v1/c/{guild_id}``, served from ``/api/v1/c/0``: an
  install's community comes from its token;
- each operation is named after its route;
- the one credential is the installation's access token.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from fastapi.routing import APIRoute

from app.api.deps import route_app_scope_declaration
from app.core.config import API_V1_STR
from app.core.identity_boundary import MentionForm
from app.schemas.platform.user import AppPerson

#: The prefix every route an app may call starts with.
COMMUNITY_PREFIX = f"{API_V1_STR}/c/{{guild_id}}"
#: Where the app's document serves from. The ``0`` stands for the install's own
#: community.
APP_SERVER_URL = f"{API_V1_STR}/c/0"

_SCHEMA_REF = "#/components/schemas/"
_APP_PERSON = AppPerson.__name__
_SECURITY_SCHEME = "AppToken"

#: What a field that mentions people says about them, by its ``x-mentions``.
_MENTIONS = {
    MentionForm.markdown.value: (
        "A person is mentioned as `@[Name](<reference>)`, by your reference for "
        "them. The name is empty without `members:read`. Write "
        "`@[](<reference>)`: the person's name is filled in."
    ),
    MentionForm.lexical.value: (
        "A Lexical editor state. A person is mentioned by a node whose "
        "`mentionUserId` is your reference for them; its `mentionName` and "
        "`text` are empty without `members:read`, and filled in when you write "
        "one."
    ),
}


def _scoped_operations(
    openapi_schema: dict[str, Any], routes: Iterable[Any]
) -> Iterator[tuple[APIRoute, str, Any, dict[str, Any]]]:
    """Each operation of a route that declares an app scope, with the route,
    its method and the declaration."""
    paths = openapi_schema["paths"]
    for route in routes:
        if not isinstance(route, APIRoute) or not route.include_in_schema:
            continue
        declaration = route_app_scope_declaration(route)
        if declaration is None:
            continue
        for method in sorted(route.methods):
            yield (
                route,
                method.lower(),
                declaration,
                paths[route.path_format][method.lower()],
            )


def mark_app_scopes(openapi_schema: dict[str, Any], routes: Iterable[Any]) -> None:
    """Set ``x-app-scope`` on each operation an app may call, as its route's
    dependency declares it."""
    for _, _, declaration, operation in _scoped_operations(openapi_schema, routes):
        operation["x-app-scope"] = declaration


def _schema_refs(node: Any) -> Iterator[str]:
    """The component schema names ``node`` refers to."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref":
                if not value.startswith(_SCHEMA_REF):
                    raise ValueError(f"unexpected reference {value}")
                yield value.removeprefix(_SCHEMA_REF)
            else:
                yield from _schema_refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _schema_refs(item)


def _as_app_people(node: Any, people: set[str]) -> Any:
    """``node`` copied, with each reference to a schema in ``people`` a
    reference to ``AppPerson``."""
    if isinstance(node, dict):
        return {
            key: (
                f"{_SCHEMA_REF}{_APP_PERSON}"
                if key == "$ref" and value.removeprefix(_SCHEMA_REF) in people
                else _as_app_people(value, people)
            )
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_as_app_people(item, people) for item in node]
    return node


def _as_references(node: Any) -> Any:
    """``node`` copied, with each identity field a string and each field that
    mentions people described: what an install sends and receives."""
    if isinstance(node, dict):
        identity = node.get("x-identity")
        if identity is not None:
            kept = {key: node[key] for key in ("title", "description") if key in node}
            return {**kept, "type": "string", "x-identity": identity}
        copied = {key: _as_references(value) for key, value in node.items()}
        mentions = node.get("x-mentions")
        if mentions is not None:
            copied.setdefault("description", _MENTIONS[mentions])
        return copied
    if isinstance(node, list):
        return [_as_references(item) for item in node]
    return node


def build_app_openapi(
    openapi_schema: dict[str, Any], routes: Iterable[Any]
) -> dict[str, Any]:
    """The app's document, cut from the main one (``openapi_schema``, already
    marked by :func:`mark_app_scopes`). Raises on a route an app may call
    outside a community, or on two such routes with one name."""
    paths: dict[str, dict[str, Any]] = {}
    named: dict[str, str] = {}
    for route, method, _, operation in _scoped_operations(openapi_schema, routes):
        if not route.path_format.startswith(f"{COMMUNITY_PREFIX}/"):
            raise RuntimeError(f"{route.path_format} is not a community route")
        path = route.path_format.removeprefix(COMMUNITY_PREFIX)
        where = f"{method.upper()} {path}"
        if route.name in named:
            raise RuntimeError(
                f"two app routes are named {route.name}: {named[route.name]} and {where}"
            )
        named[route.name] = where
        parameters = [
            parameter
            for parameter in operation.get("parameters", ())
            if not (parameter["in"] == "path" and parameter["name"] == "guild_id")
        ]
        rewritten = {
            **operation,
            "operationId": route.name,
            "security": [{_SECURITY_SCHEME: []}],
        }
        rewritten.pop("parameters", None)
        if parameters:
            rewritten["parameters"] = parameters
        paths.setdefault(path, {})[method] = rewritten

    schemas = {
        **openapi_schema["components"]["schemas"],
        _APP_PERSON: AppPerson.model_json_schema(mode="serialization"),
    }
    people = {name for name, schema in schemas.items() if schema.get("x-person")}
    paths = _as_app_people(paths, people)
    reached: dict[str, Any] = {}
    pending = list(_schema_refs(paths))
    while pending:
        name = pending.pop()
        if name not in reached:
            reached[name] = _as_app_people(schemas[name], people)
            pending.extend(_schema_refs(reached[name]))

    info = openapi_schema["info"]
    return _as_references(
        {
            "openapi": openapi_schema["openapi"],
            "info": {"title": "Initiative app API", "version": info["version"]},
            "servers": [{"url": APP_SERVER_URL}],
            "paths": paths,
            "components": {
                "schemas": dict(sorted(reached.items())),
                "securitySchemes": {
                    _SECURITY_SCHEME: {
                        "type": "http",
                        "scheme": "bearer",
                        "description": "The installation's access token.",
                    }
                },
            },
        }
    )
