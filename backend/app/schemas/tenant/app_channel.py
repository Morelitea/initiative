"""What an app service sees of its own installs.

These payloads serialize one install's state for the calls an app makes about
its own installation (``/app-platform/installation/*``), so they are shaped by
two rules the browser-facing schemas in :mod:`app.schemas.tenant.guild_app` do
not share:

* **Credentials do appear here — in exactly one payload.**
  :class:`AppInstallConfigRead` is the custody channel: the app is the party
  that uses these values, so it is handed them decrypted. Every other payload,
  the connections view included, carries state and never a value.
* **Members are references.** A per-member connection is addressed by its
  opaque ``connection_ref``; there is no user id, email, or display name in any
  shape below.

Values are typed ``Dict[str, Any]`` deliberately: a credential is opaque bytes
to this build, so declaring it as text would invite sanitization that corrupts
it, and the field types that *do* apply live in the pinned definition the
service layer validates against.
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import ConfigDict, Field

from app.schemas.base import SanitizedBaseModel

__all__ = [
    "AppConnectionRead",
    "AppConnectionsResponse",
    "AppConnectionWrite",
    "AppInstallConfigRead",
    "AppInstallationEvent",
    "AppMemberConfigRead",
    "AppStatusReport",
    "AppStatusRead",
]


class AppMemberConfigRead(SanitizedBaseModel):
    """One member's stored values, addressed by the handle the app knows."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    connection_id: str
    connection_ref: str
    status: str
    values: Dict[str, Any] = {}


class AppInstallConfigRead(SanitizedBaseModel):
    """The decrypted configuration for one install — the custody channel.

    ``connections`` holds the guild-wide values an admin typed, keyed by
    connection id; ``member_connections`` holds the per-member values the app
    itself wrote back, keyed by reference. Both are plaintext, and this is the
    only payload in the build where that is true.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    guild_ref: str
    install_id: int
    listing_uid: str
    listing_version: str
    enabled: bool
    config_state: str = "unverified"
    config_state_detail: Optional[str] = None
    needs_config: bool = False
    connections: Dict[str, Dict[str, Any]] = {}
    member_connections: List[AppMemberConfigRead] = []


class AppConnectionRead(SanitizedBaseModel):
    """One member's connection, as the app reconciles it.

    Enough to know which handles are live and which an admin has stopped, and
    no more: an app matching its stored credentials against this list never
    needs a value to do it.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    connection_id: str
    connection_ref: str
    status: str
    blocked: bool = False
    #: What the app itself reported the member connected as. Display only.
    account_label: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class AppConnectionsResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[AppConnectionRead] = []


class AppConnectionWrite(SanitizedBaseModel):
    """What an app writes back after completing a vendor flow.

    Only fields the pinned manifest marked ``managed`` may be set this way; a
    key sent as ``null`` clears that value, and a key left out is untouched, so
    a refresh that carries one rotated token does not disturb the rest.
    """

    values: Dict[str, Any] = {}
    #: ``pending`` while a flow is still in progress; otherwise the stored
    #: values decide, so an app cannot claim a connection it does not hold.
    status: Optional[Literal["pending", "connected"]] = None
    #: The vendor account the member connected as, e.g. ``@alice``.
    account_label: Optional[str] = Field(default=None, max_length=200)


class AppStatusReport(SanitizedBaseModel):
    """The app's verdict on the configuration it was handed.

    ``unverified`` is absent by design: it is this build's resting value for an
    install nothing has reported on, not something an app asserts.
    """

    state: Literal["ok", "invalid"]
    #: A short code shown beside an ``invalid`` state, e.g. ``missing_scope``.
    detail: Optional[str] = Field(default=None, max_length=120)


class AppStatusRead(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    guild_ref: str
    install_id: int
    config_state: str
    config_state_detail: Optional[str] = None


class AppInstallationEvent(SanitizedBaseModel):
    """A third-party event an app is re-emitting into the community whose
    install its token names.

    ``event_type`` is checked against the pinned definition and against the
    caller's own namespace.
    """

    event_type: str = Field(max_length=200)
    payload: Dict[str, Any] = {}
