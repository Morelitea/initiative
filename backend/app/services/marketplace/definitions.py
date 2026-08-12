"""What a listing is allowed to publish, per kind.

A listing arriving from anywhere — a shipped data file today, a signed remote
manifest later — carries a definition, and that definition is stored and later
copied into a guild's schema. This module is the one place that decides whether
a body is acceptable, and it does so by handing off to the *same* validator the
guild-scoped API uses: a downloaded dashboard is normalized by
``dashboard_definition``, exactly like one authored by hand.

That reuse is the point: catalog content is held to the same widget and binding
vocabulary as anything authored in the app, by the same code.
"""

from __future__ import annotations

from typing import Any

from app.services.tenant.dashboard_definition import (
    DashboardDefinitionError,
    normalize_dashboard_definition,
)

__all__ = [
    "ListingDefinitionError",
    "LISTING_KINDS",
    "APP_KINDS",
    "MOUNTABLE_TOOLS",
    "normalize_listing_definition",
]


class ListingDefinitionError(ValueError):
    """A listing body this build cannot accept. The message names the reason in
    plain terms — these are read by an operator seeding a catalog, not surfaced
    to an end user."""


#: Kinds the catalog can hold.
#:
#: ``auto`` is declared here so the vocabulary is complete — the marketplace can
#: name and filter by it — while nothing installs one yet: a manifest carrying
#: one is refused with a reason rather than stored as something no code can
#: resolve. Same treatment ``embed`` apps get.
LISTING_KINDS: frozenset[str] = frozenset({"dashboard", "app", "auto"})

#: How an app presents itself.
#:
#: ``tool_instance`` mounts one of the app's own tools at guild scope — the app
#: creates an ordinary row in an ordinary table and the existing UI renders it.
#: ``embed`` hosts an external surface in an iframe; it is declared here so a
#: manifest naming it is refused with a reason rather than silently accepted,
#: and gets its validator with the machinery that serves it.
APP_KINDS: frozenset[str] = frozenset({"tool_instance", "embed"})

#: Tools an app may mount at guild scope. A tool qualifies when its content is
#: meaningful without an initiative — a calendar of the guild's own events is;
#: a dashboard, which binds to one initiative's data, is not (and is not
#: planned to be).
MOUNTABLE_TOOLS: frozenset[str] = frozenset({"calendar"})


def _normalize_app_definition(definition: Any) -> dict[str, Any]:
    """An app's body: which kind it is, and what that kind needs.

    Deliberately narrow. An app definition names a *kind* and, for a tool
    instance, which of this build's tools to mount — it never carries code, a
    URL a guild could type, or anything that would be dereferenced. Unknown keys
    are dropped rather than stored, so a definition always has canonical shape.
    """
    if not isinstance(definition, dict):
        raise ListingDefinitionError("app definition must be an object")

    app_kind = definition.get("app_kind")
    if app_kind not in APP_KINDS:
        raise ListingDefinitionError(f"unknown app kind {app_kind!r}")
    if app_kind == "embed":
        raise ListingDefinitionError("embed apps are not installable in this build yet")

    tool = definition.get("tool")
    if tool not in MOUNTABLE_TOOLS:
        raise ListingDefinitionError(f"{tool!r} cannot be mounted at guild scope")

    cleaned: dict[str, Any] = {"app_kind": app_kind, "tool": tool}
    # A starting name for the content the install creates; the guild renames it
    # afterwards like anything else.
    default_name = definition.get("default_name")
    if isinstance(default_name, str) and default_name.strip():
        cleaned["default_name"] = default_name.strip()[:255]
    return cleaned


def normalize_listing_definition(kind: str, definition: Any) -> dict[str, Any]:
    """Validate and canonicalize a listing's definition for its kind."""
    if kind not in LISTING_KINDS:
        raise ListingDefinitionError(f"unknown listing kind {kind!r}")
    if kind == "auto":
        raise ListingDefinitionError(
            "automation listings are not installable in this build yet"
        )
    if kind == "app":
        return _normalize_app_definition(definition)
    try:
        return normalize_dashboard_definition(definition)
    except DashboardDefinitionError as exc:
        # The tool validator speaks in machine codes meant for the API's 422;
        # here the audience is whoever is publishing, so it is re-raised named.
        raise ListingDefinitionError(f"invalid dashboard definition: {exc}") from exc
