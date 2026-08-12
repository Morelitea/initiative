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

from dataclasses import dataclass
from typing import Any, Optional

from app.services.marketplace.manifest_values import (
    MAX_AUTHOR_NAME_LENGTH,
    MAX_CONTACT_LENGTH,
    MAX_NAME_LENGTH,
    ListingDefinitionError,
    check_single_line,
    check_url,
    clean_text,
    fail,
    require_mapping,
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
    "ListingAuthor",
    "ListingDefinitionError",
    "LISTING_KINDS",
    "LISTING_SOURCES",
    "APP_KINDS",
    "GUILD_INSTALLABLE_APP_KINDS",
    "EMBED_TARGETS",
    "MOUNTABLE_TOOLS",
    "RESERVED_PUBLIC_ID_PREFIX",
    "app_widget_type",
    "normalize_author",
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

#: How a listing reached this deployment. This is the provenance shown beside an
#: author's name, and the reason a name alone never has to be taken on faith.
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

#: The app kinds the guild install path can mount **today**.
#:
#: A ``service`` app's definition is publishable and storable — that is what this
#: module validates — but installing one needs the registration, connection and
#: proxy machinery that arrives with the app platform. Until then the install
#: endpoint refuses it by name rather than half-mounting something it cannot
#: serve.
GUILD_INSTALLABLE_APP_KINDS: frozenset[str] = frozenset({"tool_instance", "embed"})

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


@dataclass(frozen=True)
class ListingAuthor:
    """Who wrote a listing, as the catalog records it."""

    name: str
    url: Optional[str] = None
    contact: Optional[str] = None


def normalize_author(raw: Any) -> ListingAuthor:
    """The author block, required on every ingestion path.

    Attribution is a trust signal people act on before installing, so a listing
    that states none is refused rather than published as anonymous. What the
    author *claims* is bounded here; the catalog separately records how the
    listing arrived, and the two are shown together — a name never stands in for
    provenance.
    """
    if raw is None:
        fail("author is required: a listing states who wrote it")
    author = require_mapping(raw, "author")

    name = clean_text(
        author.get("name"), what="author.name", limit=MAX_AUTHOR_NAME_LENGTH
    )
    check_single_line(name or "", what="author.name")

    url = author.get("url")
    contact = clean_text(
        author.get("contact"),
        what="author.contact",
        limit=MAX_CONTACT_LENGTH,
        required=False,
    )
    if contact is not None:
        check_single_line(contact, what="author.contact")

    return ListingAuthor(
        name=name or "",
        url=check_url(url, what="author.url") if url is not None else None,
        contact=contact,
    )


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
