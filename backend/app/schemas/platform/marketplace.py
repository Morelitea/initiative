"""What the marketplace surface sees.

Catalog metadata only. A listing carries no tenant data — no guild ever appears
in these payloads — so they are safe to serve to any authenticated session, and
"who installed this" is answered per-guild by the tool's own endpoints rather
than by anything here.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import ConfigDict

from app.schemas.base import SanitizedBaseModel
from app.services.marketplace.definitions import LISTING_KINDS

# Derived from the validator's own set rather than restated, the way WidgetType
# derives from the widget registry: a new kind reaches the API — and, through
# the generated types, the frontend — without an edit here.
ListingKind = Enum(
    "ListingKind", {name: name for name in sorted(LISTING_KINDS)}, type=str
)
ListingKind.__doc__ = "What a marketplace listing installs as."


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
    source: str
    name: str
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
    versions: List[MarketplaceVersionRead] = []


class MarketplaceListingPage(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[MarketplaceListingSummary]
    total: int
