"""What an app service sees of its own installs.

These payloads serialize one install's state for the calls an app makes about
its own installation (``/app-platform/installation/*``), so they are shaped by
two rules the browser-facing schemas in :mod:`app.schemas.tenant.guild_app` do
not share:

* **Credentials do appear here — in two payloads.**
  :class:`AppInstallConfigRead` carries the values a community typed and the
  managed values a connection's ``after_connect`` hook returned, decrypted; a
  flow's tokens are never in it. :class:`AppConnectionToken` is one usable
  access token, asked for by reference. Every other payload, the connections
  view included, carries state and never a value.
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
    "AppConnectionToken",
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

    ``connections`` holds the guild-wide values, keyed by connection id;
    ``member_connections`` holds each member's managed values, keyed by
    reference. ``connection_refs`` names the handle of each guild-wide
    connection that has one, for asking for its token. A flow's tokens are in
    none of them.
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
    connection_refs: Dict[str, str] = {}
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


class AppConnectionToken(SanitizedBaseModel):
    """A usable access token for one connection.

    Refreshed first when it was close to expiring, or minted for a connection
    that declares a ``jwt_bearer`` token. ``expires_at`` is in epoch seconds,
    and absent when the vendor did not say.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    access_token: str
    expires_at: Optional[int] = None


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
