"""Payloads for the app service registry and its publishers.

A registration's listing, addresses and the public half of its keys are shown
as they are. Its vendor values are the one thing it holds that is secret: a
secret one is written and never read back, and the screen is told only that it
is set. A request writes deployment facts only; what the app is and may do
comes from its listing.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import ConfigDict, Field, model_validator

from app.core.messages import AppServiceMessages
from app.models.platform.app_service_registration import LISTING_STATED_FIELDS
from app.schemas.base import RawTextStr, SanitizedBaseModel

__all__ = [
    "AppPublisherCreate",
    "AppPublisherRead",
    "AppPublisherUpdate",
    "AppServiceRegistrationCreate",
    "AppServiceRegistrationRead",
    "AppServiceRegistrationUpdate",
    "AppVendorFieldRead",
]


class AppVendorFieldRead(SanitizedBaseModel):
    """One value an operator supplies for the app's vendor client, as the
    listing's manifest declares it."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    key: str
    #: ``string``, ``secret`` or ``url``. A secret is write-only.
    type: str
    required: bool = False
    label: Dict[str, str] = {}


class AppServiceRegistrationRead(SanitizedBaseModel):
    """A registration as the owner's settings see it."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    public_id: str
    #: The catalog listing its app facts come from. Null until it arrives.
    listing_uid: Optional[str] = None
    #: The publisher the public_id's prefix names.
    publisher_id: int
    publisher_prefix: str
    publisher_name: str
    publisher_enabled: bool
    #: Where this deployment's server calls the app. Null until the operator
    #: gives its address.
    base_url: Optional[str] = None
    #: Where a browser loads its surfaces. Null when that is ``base_url`` too.
    embed_origin: Optional[str] = None
    allowed_origins: List[str] = []
    #: Public keys this app signs with. Shown in full — the
    #: public half is meant to be read, and an operator provisioning it needs
    #: to see which ``kid`` landed.
    jwks: Optional[Dict[str, Any]] = None
    #: Where the app publishes its key set, on its own origin.
    jwks_uri: Optional[str] = None
    #: The most an install of this app may be granted, from its listing.
    #: Empty means no scope may be granted.
    scope_ceiling: List[str] = []
    #: Installed into every guild and not removable by guild admins.
    mandatory: bool = False
    enabled: bool = True
    #: ``registry`` when its app facts come from a listing the registry signed,
    #: ``operator`` otherwise.
    source: str = "operator"
    #: The container image its listing names, pinned by digest.
    image_digest: Optional[str] = None
    #: The values the listing's manifest asks the operator for, in order.
    vendor_fields: List[AppVendorFieldRead] = []
    #: The plain values of the non-secret vendor fields that hold one.
    vendor_values: Dict[str, str] = {}
    #: Every vendor field that holds a value, secret or not.
    vendor_set: List[str] = []
    #: Whether every required vendor value is set.
    vendor_ready: bool = True
    #: The two addresses to register with the vendor's client: where it
    #: returns a person with a code, and where its install page returns them.
    connection_callback_url: str
    connection_setup_url: str
    #: Enabled, its publisher enabled, an address, a key set to verify
    #: against, and every required vendor value set.
    live: bool
    created_at: datetime
    updated_at: datetime


class _DeploymentFacts(SanitizedBaseModel):
    """A request naming what only the app's listing states is refused."""

    @model_validator(mode="before")
    @classmethod
    def _no_listing_facts(cls, data: Any) -> Any:
        if isinstance(data, dict) and any(key in data for key in LISTING_STATED_FIELDS):
            raise ValueError(AppServiceMessages.STATED_BY_LISTING)
        return data


class AppServiceRegistrationCreate(_DeploymentFacts):
    """Set up an app service's deployment facts before its listing arrives.

    ``public_id`` names the app. ``embed_origin`` is optional, and unset is the
    ordinary case: an app reachable at one address needs only ``base_url``.
    Give one when the address a browser must use is not the address this
    deployment calls.

    Keys are a pasted ``jwks``, a ``jwks_uri`` on ``base_url``'s own origin
    over https, or both. A registration with neither is not live.
    """

    public_id: str = Field(max_length=120)
    base_url: str = Field(max_length=1000)
    embed_origin: Optional[str] = Field(default=None, max_length=1000)
    allowed_origins: Optional[List[str]] = None
    #: JWKS holding the public half of the app's signing keys.
    jwks: Optional[Dict[str, Any]] = None
    jwks_uri: Optional[str] = Field(default=None, max_length=1000)
    mandatory: bool = False
    enabled: bool = True
    #: Values for the vendor fields the listing's manifest declares, by key.
    vendor_values: Optional[Dict[str, Optional[RawTextStr]]] = None


class AppServiceRegistrationUpdate(_DeploymentFacts):
    """Partial edit.

    An empty ``embed_origin`` clears it, putting both surfaces back on
    ``base_url``. An empty ``jwks_uri`` clears it, and an empty ``jwks``
    object clears the pasted set. In ``vendor_values`` a key sent empty or
    null clears that value, and a key left out keeps it, so a secret is kept
    by not sending it.
    """

    base_url: Optional[str] = Field(default=None, max_length=1000)
    embed_origin: Optional[str] = Field(default=None, max_length=1000)
    allowed_origins: Optional[List[str]] = None
    #: Replace the key set. An empty object clears it.
    jwks: Optional[Dict[str, Any]] = None
    jwks_uri: Optional[str] = Field(default=None, max_length=1000)
    mandatory: Optional[bool] = None
    enabled: Optional[bool] = None
    #: Set or clear vendor values, by key.
    vendor_values: Optional[Dict[str, Optional[RawTextStr]]] = None


class AppPublisherRead(SanitizedBaseModel):
    """A publisher as the owner's settings see it."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    #: The ``public_id`` prefix its apps carry.
    prefix: str
    display_name: str
    #: Whether the deployment has confirmed who this publisher is.
    verified: bool
    #: Off makes every registration under this prefix not live.
    enabled: bool
    created_at: datetime


class AppPublisherCreate(SanitizedBaseModel):
    """Add a publisher for a prefix, unverified."""

    prefix: str = Field(max_length=120)
    display_name: str = Field(max_length=200)
    enabled: bool = True


class AppPublisherUpdate(SanitizedBaseModel):
    """Rename a publisher, or switch it on or off."""

    display_name: Optional[str] = Field(default=None, max_length=200)
    enabled: Optional[bool] = None
