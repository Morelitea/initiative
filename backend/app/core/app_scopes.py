"""The scopes an app can be granted in a community — the one vocabulary.

A scope is ``<resource>:<access>``: ``projects:write``, ``comments:read``. The
resources are derived from the registries that already define the things they
name, so a new tool is a new scope the moment it joins ``Tool``:

- one resource per tool, spelled as the tool's plural;
- ``comments``, ``relationships`` and ``tags``, the surfaces that span tools;
- ``sharing``, a resource's grants: reading who has access, and changing it
  where the app's own rung on the resource would let a person;
- ``members`` and ``initiatives``, which are read-only.

Writing implies reading. :func:`expand` applies that once, so no later check
has to ask twice.

Beside that fixed vocabulary sits one open family: ``apps:<public_id>``, which
lets an app call another app's public endpoints through Initiative. It names
no resource of the community's, so :func:`expand` gives it nothing; it is
parsed by its prefix and the public-id characters (:func:`app_scope_target`)
rather than listed, and a grant holds it by exact name.

Dependency-free apart from ``Tool``, so ``app.db``'s registry layer can import
it.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum

from app.core.tools import Tool

#: The resources that span tools, and the read-only ones. Everything else is a
#: tool.
_SHARED_RESOURCES: tuple[str, ...] = ("comments", "relationships", "tags", "sharing")
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


#: The prefix of the scope family that lets an app call another app.
APP_SCOPE_PREFIX = "apps:"

#: What a public id is drawn from, and how long one may be: the contract's
#: ``publicId`` character set and ``publicIdLength`` cap, restated here so this
#: module stays free of the marketplace package (``app_scopes_test`` holds the
#: two equal).
PUBLIC_ID_CHARS: frozenset[str] = frozenset("-.0123456789_abcdefghijklmnopqrstuvwxyz")
MAX_PUBLIC_ID_LENGTH = 120


def app_scope(public_id: str) -> str:
    """The scope that lets an app call the app ``public_id``."""
    return f"{APP_SCOPE_PREFIX}{public_id}"


def app_scope_target(scope: str) -> str | None:
    """The public id an ``apps:`` scope names, or ``None`` when ``scope`` is
    not one: the prefix, then a ``<publisher>.<slug>`` id of the public-id
    characters."""
    if not isinstance(scope, str) or not scope.startswith(APP_SCOPE_PREFIX):
        return None
    public_id = scope[len(APP_SCOPE_PREFIX) :]
    if not public_id or len(public_id) > MAX_PUBLIC_ID_LENGTH or "." not in public_id:
        return None
    for character in public_id:
        if character not in PUBLIC_ID_CHARS:
            return None
    return public_id


def is_known_scope(scope: str) -> bool:
    """Whether ``scope`` is in the vocabulary or the ``apps:`` family."""
    return scope in _ALL_SCOPES or app_scope_target(scope) is not None


def ordered_scopes(scopes: Iterable[str]) -> list[str]:
    """The known scopes among ``scopes``, each once: the vocabulary's in its
    order, then the ``apps:`` family sorted."""
    asked = {scope for scope in scopes if isinstance(scope, str)}
    return [scope for scope in ALL_SCOPES if scope in asked] + sorted(
        scope for scope in asked if app_scope_target(scope) is not None
    )


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
    that is neither in the vocabulary nor in the ``apps:`` family."""
    checked = frozenset(scopes)
    for scope in sorted(checked):
        if not is_known_scope(scope):
            raise UnknownAppScope(scope)
    return checked


def expand(
    scopes: Iterable[str],
) -> tuple[frozenset[AppScopeResource], frozenset[AppScopeResource]]:
    """The resources ``scopes`` let an app read and write.

    Writing implies reading, so every written resource is in the read set too.
    An ``apps:`` scope names no resource and adds nothing.
    """
    read: set[AppScopeResource] = set()
    write: set[AppScopeResource] = set()
    for scope in scopes:
        if app_scope_target(scope) is not None:
            continue
        resource, access = parse_scope(scope)
        read.add(resource)
        if access is AppScopeAccess.write:
            write.add(resource)
    return frozenset(read), frozenset(write)
