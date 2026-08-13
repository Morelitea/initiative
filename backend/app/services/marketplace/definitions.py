"""What a listing is allowed to publish, per kind.

A listing arriving from anywhere — a shipped data file today, an operator upload
or a signed remote manifest later — carries a definition, and that definition is
stored and later copied into a guild's schema. This module is the one place that
decides whether a body is acceptable, and for a dashboard it does so by handing
off to the *same* validator the guild-scoped API uses: a downloaded dashboard is
normalized by ``normalize_dashboard_definition``, exactly like one authored by
hand.

That reuse is the point: catalog content is held to the same widget and binding
vocabulary as anything authored in the app, by the same code.

The pieces this file leans on live beside it, because a service app's manifest is
too large a vocabulary to read in one sitting:

* ``manifest_values`` — the bounded primitives every value goes through.
* ``widget_meta`` — the server-side reading of the rules the browser applies to
  a widget's own strings.
* ``service_apps`` — the ``app_kind: "service"`` manifest.

Two rules span all of them. **Attribution is required**: a listing states who
wrote it or it is not published. And **``core.*`` belongs to this repository**:
an id in that namespace is only ever claimed by a listing shipped in this build.
"""

from __future__ import annotations

from typing import Any, Optional

from app.services.marketplace.manifest_values import (
    MAX_PUBLISHER_NAME_LENGTH,
    MAX_NAME_LENGTH,
    ListingDefinitionError,
    check_single_line,
    clean_text,
    fail,
)
from app.services.marketplace.service_apps import (
    app_widget_type,
    normalize_service_app_definition,
)
from app.services.tenant.dashboard_definition import (
    DashboardDefinitionError,
    normalize_dashboard_definition,
)

__all__ = [
    "ListingDefinitionError",
    "LISTING_KINDS",
    "LISTING_SOURCES",
    "APP_KINDS",
    "GUILD_INSTALLABLE_APP_KINDS",
    "EMBED_TARGETS",
    "MOUNTABLE_TOOLS",
    "RESERVED_PUBLIC_ID_PREFIX",
    "app_widget_type",
    "normalize_publisher",
    "normalize_listing_definition",
    "reserved_prefix_problem",
]


#: Kinds the catalog can hold.
#:
#: ``auto`` is declared here so the vocabulary is complete — the marketplace can
#: name and filter by it — while nothing installs one yet: a manifest carrying
#: one is refused with a reason rather than stored as something no code can
#: resolve.
LISTING_KINDS: frozenset[str] = frozenset({"dashboard", "app", "auto"})

#: How a listing reached this deployment. Not a trust ranking shown to a reader
#: — every listing is here because an administrator put it here — but the reason
#: a listing shipped in this build is credited to us rather than to whatever its
#: manifest claims.
#:
#: ``builtin`` shipped in this build. ``operator`` was added by whoever runs the
#: deployment. ``registry`` arrived from a remote index this deployment trusts.
LISTING_SOURCES: frozenset[str] = frozenset({"builtin", "operator", "registry"})

#: How an app presents itself.
#:
#: ``tool_instance`` mounts one of the app's own tools at guild scope — the app
#: creates an ordinary row in an ordinary table and the existing UI renders it.
#: ``embed`` hosts an external surface in an iframe, driven by the signed handoff
#: machinery. ``service`` declares features a container the operator runs will
#: serve.
APP_KINDS: frozenset[str] = frozenset({"tool_instance", "embed", "service"})

#: The app kinds the guild install path can mount.
#:
#: All three, now that a ``service`` app has somewhere to land: the deployment's
#: registration supplies the address, the secret and the powers, and the install
#: is the pinned definition plus whatever the guild configures against it. A
#: service app creates no local content, so installing one is the row and
#: nothing else.
#:
#: The set is still separate from :data:`APP_KINDS` because the two answer
#: different questions — what a listing may *declare* versus what this build can
#: *mount* — and a kind added to the vocabulary ahead of its machinery is
#: refused by name rather than half-mounted.
GUILD_INSTALLABLE_APP_KINDS: frozenset[str] = frozenset(
    {"tool_instance", "embed", "service"}
)

#: Where an embed's target comes from.
#:
#: ``advanced_tool`` means the deployment's own configuration supplies it — the
#: URL, the origin allowlist, the audience and the display name all come from
#: the operator's ``ADVANCED_TOOL_*`` settings, and the listing carries none of
#: them. An install without that configuration has nothing to open, which is why
#: the listing is served only where it is set.
#:
#: Targets supplied by a listing itself arrive with the signed remote registry.
#: Until then a definition naming one is refused by name.
EMBED_TARGETS: frozenset[str] = frozenset({"advanced_tool"})

#: Tools an app may mount at guild scope. A tool qualifies when its content is
#: meaningful without an initiative — a calendar of the guild's own events is;
#: a dashboard, which binds to one initiative's data, is not (and is not
#: planned to be).
MOUNTABLE_TOOLS: frozenset[str] = frozenset({"calendar"})

#: The namespace this repository's own listings publish under.
RESERVED_PUBLIC_ID_PREFIX = "core."

#: Sources allowed to claim it.
RESERVED_PREFIX_SOURCES: frozenset[str] = frozenset({"builtin"})


# --- attribution ------------------------------------------------------------


def normalize_publisher(raw: Any) -> str:
    """The name a listing publishes under, required on every ingestion path.

    One name, not a person and a distributor kept apart: whoever publishes is
    who a reader is trusting, whether that is the individual who wrote it or an
    organisation shipping someone else's work. A listing that states none is
    refused rather than published as anonymous.

    What the publisher *claims* is bounded here; the catalog separately records
    how the listing arrived.
    """
    if raw is None:
        fail("publisher is required: a listing states who publishes it")
    name = clean_text(raw, what="publisher", limit=MAX_PUBLISHER_NAME_LENGTH)
    check_single_line(name or "", what="publisher")
    return name or ""


def reserved_prefix_problem(public_id: str, *, source: str) -> Optional[str]:
    """Why this source may not publish under this id, or ``None``.

    ``core.*`` names listings shipped in this repository, so the id itself
    carries the same answer the provenance badge does. Anything arriving from an
    operator upload or a registry publishes under its own publisher prefix.
    """
    if not public_id.startswith(RESERVED_PUBLIC_ID_PREFIX):
        return None
    if source in RESERVED_PREFIX_SOURCES:
        return None
    return (
        f"the {RESERVED_PUBLIC_ID_PREFIX!r} prefix is reserved for listings "
        f"shipped with this build; a {source!r} listing publishes under its "
        "own publisher prefix"
    )


# --- definitions ------------------------------------------------------------


def _normalize_app_definition(definition: Any) -> dict[str, Any]:
    """An app's body: which kind it is, and what that kind needs.

    ``tool_instance`` and ``embed`` are deliberately narrow — a kind and one
    thing, either which of this build's tools to mount or which configured embed
    target to open. Neither carries code or a URL: an embed target names a slot
    in the deployment's own configuration, which is where the address comes from.

    ``service`` is the wide one, and it keeps the same rule (see
    ``service_apps``): paths, never addresses. Unknown keys are dropped rather
    than stored, so a definition always has canonical shape.
    """
    if not isinstance(definition, dict):
        raise ListingDefinitionError("app definition must be an object")

    app_kind = definition.get("app_kind")
    if app_kind not in APP_KINDS:
        raise ListingDefinitionError(f"unknown app kind {app_kind!r}")

    if app_kind == "service":
        return normalize_service_app_definition(definition)

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
    default_name = clean_text(
        definition.get("default_name"),
        what="default_name",
        limit=MAX_NAME_LENGTH,
        required=False,
    )
    if default_name is not None:
        cleaned["default_name"] = default_name
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
