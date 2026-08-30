"""What the marketplace surface sees.

Catalog metadata only. A listing carries no tenant data — no guild ever appears
in these payloads — and "who installed this" is answered per-guild by the tool's
own endpoints rather than by anything here.

Which listings a guild is *offered* is a different question, decided by the
guild-addressed shelf; these payloads describe a listing the same way wherever
it is served from, which is what keeps a card and the page it opens in
agreement.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from pydantic import ConfigDict

from app.schemas.base import RawTextStr, SanitizedBaseModel
from app.services.marketplace.definitions import LISTING_KINDS, LISTING_SOURCES

if TYPE_CHECKING:
    from app.models.platform.marketplace import (
        MarketplaceListing,
        MarketplaceListingVersion,
    )

# Derived from the validator's own set rather than restated, the way WidgetType
# derives from the widget registry: a new kind reaches the API — and, through
# the generated types, the frontend — without an edit here.
ListingKind = Enum(
    "ListingKind", {name: name for name in sorted(LISTING_KINDS)}, type=str
)
ListingKind.__doc__ = "What a marketplace listing installs as."

# Derived the same way. The client branches on it — listings shipped in this
# build are credited to us rather than to whatever their manifest claims — so
# the closed vocabulary belongs in the schema the client is generated from
# rather than arriving as a bare string it has to guess at.
ListingSource = Enum(
    "ListingSource", {name: name for name in sorted(LISTING_SOURCES)}, type=str
)
ListingSource.__doc__ = "How a listing reached this deployment."


class MarketplaceVersionRead(SanitizedBaseModel):
    """One published version of a listing."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    version: str
    release_notes: Optional[str] = None
    min_app_version: Optional[str] = None
    published_at: datetime
    #: Whether this deployment is new enough to install it. A version needing a
    #: newer app is shown, not hidden, so the reason is legible.
    compatible: bool = True


class MarketplaceListingSummary(SanitizedBaseModel):
    """A listing as it appears on a browse card."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    uid: str
    public_id: str
    kind: ListingKind  # type: ignore[valid-type]
    #: How the listing reached this deployment. The client credits listings
    #: shipped in this build to us rather than to whatever a manifest claims.
    source: ListingSource  # type: ignore[valid-type]
    name: str
    #: Who publishes it. Required in the catalog, so this is always present.
    publisher: str
    description: str
    avatar_url: str
    images: List[str] = []
    installs_count: int = 0
    available: bool = True
    latest_version: Optional[MarketplaceVersionRead] = None
    #: False when nothing about this listing can be installed on this build —
    #: withdrawn, or its only versions need a newer app.
    installable: bool = True
    updated_at: datetime


class MarketplaceListingDetail(MarketplaceListingSummary):
    """A listing's full page, including what it would install."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    long_description: Optional[str] = None
    #: The reference definition at the latest version — the preview the detail
    #: page renders. Installing does not send this back; the server re-reads the
    #: catalog, so nothing a client holds decides what gets stored.
    definition: Optional[Dict[str, Any]] = None


class MarketplaceListingPage(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[MarketplaceListingSummary]
    total: int


def serialize_version(
    version: Optional["MarketplaceListingVersion"],
) -> Optional[MarketplaceVersionRead]:
    # Local import avoids a schema -> service import cycle.
    from app.services.marketplace.catalog import version_is_compatible

    if version is None:
        return None
    return MarketplaceVersionRead(
        version=version.version,
        release_notes=version.release_notes,
        min_app_version=version.min_app_version,
        published_at=version.published_at,
        compatible=version_is_compatible(version.min_app_version),
    )


def serialize_listing_summary(
    listing: "MarketplaceListing",
    latest: Optional["MarketplaceListingVersion"],
) -> MarketplaceListingSummary:
    """One browse card. Shared by every surface that lists or reads a listing,
    so a card and the page it opens describe the same thing."""
    version = serialize_version(latest)
    return MarketplaceListingSummary(
        uid=listing.uid,
        public_id=listing.public_id,
        kind=listing.kind,
        source=listing.source,
        name=listing.name,
        publisher=listing.publisher,
        # Attribution travels with the provenance that bounds it: a card, the
        # detail page and the install dialog all answer "who wrote this?" from
        # these two fields together, so neither is served without the other.
        description=listing.description,
        avatar_url=listing.avatar_url,
        images=list(listing.images or []),
        installs_count=listing.installs_count or 0,
        available=listing.available,
        latest_version=version,
        # Everything that has to be true for the install button to do anything:
        # still offered, has a version, and that version runs on this build.
        installable=bool(listing.available and version and version.compatible),
        updated_at=listing.updated_at,
    )


class OperatorCatalogProblem(SanitizedBaseModel):
    """A manifest the scan would not publish, named so it can be fixed."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: The file's name inside the catalog directory.
    file: str
    #: Why it was skipped, in the words the validator used. Carried verbatim
    #: and length-bounded at the source: a diagnostic quoting the offending
    #: character is only useful if it still says which character.
    reason: RawTextStr


class OperatorCatalogScanResult(SanitizedBaseModel):
    """What a rescan of the operator's catalog directory did.

    Read by the person who just dropped a file in, so it reports the skipped
    files as well as the count: a listing that did not appear should say why
    without a trip to the server log.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    published: int = 0
    #: Listings retired because no manifest in the directory publishes them.
    withdrawn: int = 0
    skipped: int = 0
    problems: List[OperatorCatalogProblem] = []
