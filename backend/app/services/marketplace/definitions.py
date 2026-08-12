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
    "normalize_listing_definition",
]


class ListingDefinitionError(ValueError):
    """A listing body this build cannot accept. The message names the reason in
    plain terms — these are read by an operator seeding a catalog, not surfaced
    to an end user."""


#: Kinds the catalog can hold. ``app`` is declared here so a manifest carrying
#: one is rejected with a clear reason rather than silently accepted, until the
#: guild-apps phase gives it a validator.
LISTING_KINDS: frozenset[str] = frozenset({"dashboard", "app"})


def normalize_listing_definition(kind: str, definition: Any) -> dict[str, Any]:
    """Validate and canonicalize a listing's definition for its kind."""
    if kind not in LISTING_KINDS:
        raise ListingDefinitionError(f"unknown listing kind {kind!r}")
    if kind == "app":
        raise ListingDefinitionError(
            "app listings are not installable in this build yet"
        )
    try:
        return normalize_dashboard_definition(definition)
    except DashboardDefinitionError as exc:
        # The tool validator speaks in machine codes meant for the API's 422;
        # here the audience is whoever is publishing, so it is re-raised named.
        raise ListingDefinitionError(f"invalid dashboard definition: {exc}") from exc
