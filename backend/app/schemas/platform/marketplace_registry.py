"""What an operator sees of the signed-registry client.

Deployment bookkeeping, not catalog content: whether a registry is configured,
what this deployment last accepted from it, and what a refresh just did. No
guild appears here, and neither does any key material — the configured key set
is read from configuration and never echoed back.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import ConfigDict

from app.schemas.base import SanitizedBaseModel


class RegistrySkippedListing(SanitizedBaseModel):
    """One listing a verified index carried that this deployment did not take."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    public_id: str
    #: A ``MarketplaceRegistryMessages`` code naming why.
    code: str


class RegistryRefreshRead(SanitizedBaseModel):
    """The outcome of one refresh."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: The index counter that was applied.
    serial: Optional[int] = None
    #: Which trusted key signed it.
    key_id: Optional[str] = None
    upserted: int = 0
    withdrawn: int = 0
    #: True when the index was byte-identical to the one already applied, so
    #: there was nothing to do.
    unchanged: bool = False
    skipped: List[RegistrySkippedListing] = []


class RegistryStatusRead(SanitizedBaseModel):
    """Where this deployment stands with its registry."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: False when no registry is configured, or ingestion is switched off. The
    #: rest of the fields are then empty and no refresh runs.
    configured: bool = False
    registry_url: Optional[str] = None
    key_id: Optional[str] = None
    last_serial: Optional[int] = None
    last_generated_at: Optional[datetime] = None
    last_fetched_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    #: A ``MarketplaceRegistryMessages`` code, or null after a clean refresh.
    last_error: Optional[str] = None
    listing_count: int = 0
