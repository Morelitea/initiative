"""Payloads for the app service registry.

The shared secret is write-only in every direction: it arrives on create and on
a rotation, and it leaves as ``has_secret`` — a boolean saying one is stored.
Nothing here ever carries the value or its ciphertext, so an admin screen (and
anything that logs a response) sees only whether the app is wired up.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import ConfigDict, Field

from app.schemas.base import RawTextStr, SanitizedBaseModel

__all__ = [
    "AppServiceRegistrationCreate",
    "AppServiceRegistrationRead",
    "AppServiceRegistrationUpdate",
    "AppServiceVerifyRequest",
]


class AppServiceRegistrationRead(SanitizedBaseModel):
    """A registration as the admin surface sees it."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    public_id: str
    listing_uid: Optional[str] = None
    base_url: str
    allowed_origins: List[str] = []
    #: Presence only — the value never leaves the server.
    has_secret: bool = False
    manifest_hash: Optional[str] = None
    protocol_version: Optional[int] = None
    #: Operator-conferred powers. A manifest can never claim one.
    grants: List[str] = []
    #: Installed into every guild and not removable by guild admins.
    mandatory: bool = False
    enabled: bool = True
    status: str
    last_verified_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class AppServiceRegistrationCreate(SanitizedBaseModel):
    """Wire an app service up.

    ``public_id`` is optional: a reachable service names itself in its manifest.
    Supplying it lets a registration be created before the service answers (the
    declarative case), and is checked against the manifest when one arrives.
    """

    base_url: str = Field(max_length=1000)
    #: Opaque shared secret — kept verbatim and never echoed.
    secret: RawTextStr
    public_id: Optional[str] = Field(default=None, max_length=120)
    allowed_origins: Optional[List[str]] = None
    grants: Optional[List[str]] = None
    mandatory: bool = False
    enabled: bool = True


class AppServiceRegistrationUpdate(SanitizedBaseModel):
    """Partial edit. Rotating ``secret`` or repointing ``base_url`` clears the
    recorded verification — the stored manifest hash described the old target."""

    base_url: Optional[str] = Field(default=None, max_length=1000)
    secret: Optional[RawTextStr] = None
    allowed_origins: Optional[List[str]] = None
    grants: Optional[List[str]] = None
    mandatory: Optional[bool] = None
    enabled: Optional[bool] = None


class AppServiceVerifyRequest(SanitizedBaseModel):
    """Re-run the handshake.

    ``accept_manifest_change`` adopts a manifest that no longer hashes to the
    recorded one. It defaults to false so an app changing what it declares is
    surfaced to the operator rather than absorbed.
    """

    accept_manifest_change: bool = False
