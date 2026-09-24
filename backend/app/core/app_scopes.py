"""The scopes an app can be granted in a community — the one vocabulary.

A scope is ``<resource>:<access>``: ``projects:write``, ``comments:read``. The
resources are derived from the registries that already define the things they
name, so a new tool is a new scope the moment it joins ``Tool``:

- one resource per tool, spelled as the tool's plural;
- ``comments``, ``relationships`` and ``tags``, the surfaces that span tools;
- ``members`` and ``initiatives``, which are read-only.

Writing implies reading. :func:`expand` applies that once, so no later check
has to ask twice.

Dependency-free apart from ``Tool``, so ``app.db``'s registry layer can import
it.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum

from app.core.tools import Tool

#: The resources that span tools, and the read-only ones. Everything else is a
#: tool.
_SHARED_RESOURCES: tuple[str, ...] = ("comments", "relationships", "tags")
_READ_ONLY_RESOURCES: tuple[str, ...] = ("members", "initiatives")

# What a scope names: one member per tool, plus the surfaces that span tools.
AppScopeResource = Enum(
    "AppScopeResource",
    [
        (name, name)
        for name in (
            *(tool.plural for tool in Tool),
            *_SHARED_RESOURCES,
            *_READ_ONLY_RESOURCES,
        )
    ],
    type=str,
)


class AppScopeAccess(str, Enum):
    read = "read"
    write = "write"


#: Resources a scope may only read.
READ_ONLY_RESOURCES: frozenset[AppScopeResource] = frozenset(
    AppScopeResource(name) for name in _READ_ONLY_RESOURCES
)


def tool_resource(tool: Tool) -> AppScopeResource:
    """The resource a tool's scopes name."""
    return AppScopeResource(tool.plural)


def scope_name(resource: AppScopeResource, access: AppScopeAccess) -> str:
    """The scope string for ``resource`` at ``access``."""
    return f"{resource.value}:{access.value}"


#: Every scope an app can be granted, in a stable order.
ALL_SCOPES: tuple[str, ...] = tuple(
    scope_name(resource, access)
    for resource in AppScopeResource
    for access in AppScopeAccess
    if not (access is AppScopeAccess.write and resource in READ_ONLY_RESOURCES)
)
_ALL_SCOPES = frozenset(ALL_SCOPES)


class UnknownAppScope(ValueError):
    """A string that is not a scope in this vocabulary."""

    def __init__(self, scope: str) -> None:
        super().__init__(scope)
        self.scope = scope


def parse_scope(scope: str) -> tuple[AppScopeResource, AppScopeAccess]:
    """Split ``scope`` into its resource and access, or raise
    :class:`UnknownAppScope`."""
    if scope not in _ALL_SCOPES:
        raise UnknownAppScope(scope)
    resource, _, access = scope.partition(":")
    return AppScopeResource(resource), AppScopeAccess(access)


def validate_scopes(scopes: Iterable[str]) -> frozenset[str]:
    """``scopes`` as a set, raising :class:`UnknownAppScope` on the first one
    that is not in the vocabulary."""
    checked = frozenset(scopes)
    for scope in sorted(checked):
        parse_scope(scope)
    return checked


def expand(
    scopes: Iterable[str],
) -> tuple[frozenset[AppScopeResource], frozenset[AppScopeResource]]:
    """The resources ``scopes`` let an app read and write.

    Writing implies reading, so every written resource is in the read set too.
    """
    read: set[AppScopeResource] = set()
    write: set[AppScopeResource] = set()
    for scope in scopes:
        resource, access = parse_scope(scope)
        read.add(resource)
        if access is AppScopeAccess.write:
            write.add(resource)
    return frozenset(read), frozenset(write)
