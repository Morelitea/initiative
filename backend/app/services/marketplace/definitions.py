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
    "EMBED_TARGETS",
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
#: resolve.
LISTING_KINDS: frozenset[str] = frozenset({"dashboard", "app", "auto"})

#: How an app presents itself.
#:
#: ``tool_instance`` mounts one of the app's own tools at guild scope — the app
#: creates an ordinary row in an ordinary table and the existing UI renders it.
#: ``embed`` hosts an external surface in an iframe, driven by the signed handoff
#: machinery.
APP_KINDS: frozenset[str] = frozenset({"tool_instance", "embed"})

#: Where an embed's target comes from.
#:
#: ``advanced_tool`` means the deployment's own configuration supplies it — the
#: URL, the origin allowlist, the audience and the display name all come from
#: the operator's ``ADVANCED_TOOL_*`` settings, and the listing carries none of
#: them. An install without that configuration has nothing to open, which is why
#: the listing is served only where it is set.
#:
#: A listing that names its *own* target belongs to the signed remote registry:
#: an embed URL decides where a member's browser goes and which origin may talk
#: back to the app, so it may only arrive from a source whose signature has been
#: verified. Until that exists, a definition carrying one is refused by name.
EMBED_TARGETS: frozenset[str] = frozenset({"advanced_tool"})

#: Tools an app may mount at guild scope. A tool qualifies when its content is
#: meaningful without an initiative — a calendar of the guild's own events is;
#: a dashboard, which binds to one initiative's data, is not (and is not
#: planned to be).
MOUNTABLE_TOOLS: frozenset[str] = frozenset({"calendar"})


def _normalize_app_definition(definition: Any) -> dict[str, Any]:
    """An app's body: which kind it is, and what that kind needs.

    Deliberately narrow. An app definition names a *kind* and then one thing:
    which of this build's tools to mount, or which configured embed target to
    open. It never carries code, and it never carries a URL — the only embed
    target this build accepts is one the operator configured, so nothing a
    manifest says is ever dereferenced. Unknown keys are dropped rather than
    stored, so a definition always has canonical shape.
    """
    if not isinstance(definition, dict):
        raise ListingDefinitionError("app definition must be an object")

    app_kind = definition.get("app_kind")
    if app_kind not in APP_KINDS:
        raise ListingDefinitionError(f"unknown app kind {app_kind!r}")

    cleaned: dict[str, Any] = {"app_kind": app_kind}
    if app_kind == "embed":
        target = definition.get("embed_target")
        if target not in EMBED_TARGETS:
            raise ListingDefinitionError(
                f"unknown embed target {target!r}; this build serves only "
                f"{sorted(EMBED_TARGETS)}"
            )
        cleaned["embed_target"] = target
    else:
        tool = definition.get("tool")
        if tool not in MOUNTABLE_TOOLS:
            raise ListingDefinitionError(f"{tool!r} cannot be mounted at guild scope")
        cleaned["tool"] = tool

    # A starting name for what the install produces; the guild renames it
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
