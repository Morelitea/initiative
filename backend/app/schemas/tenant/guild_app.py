"""What an installed app looks like over the wire.

One rule shapes every payload here: **a stored secret never appears in a
response.** A connection reports which of its fields hold a value and nothing
about what those values are — to the member who typed them, and to the guild
admin who governs the install alike. Ending access is the useful power; reading
a live credential is not part of it.

The connection blocks are read off the *pinned* definition rather than the
catalog, so an install describes the form it was actually configured against.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import ConfigDict, Field

from app.schemas.base import SanitizedBaseModel
from app.services.marketplace.registration_lookup import InstallState
from app.services.tenant import app_config as app_config_service
from app.services.tenant.guild_apps import app_artifacts


class GuildAppInstall(SanitizedBaseModel):
    """Install a listing into this guild.

    Names a listing and nothing else that matters: the definition comes from the
    catalog, and the content the install creates is made server-side.
    """

    listing_uid: str = Field(max_length=14)
    #: Overrides the listing's own default for the content this creates.
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)


class GuildAppUpdate(SanitizedBaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    #: Turning an app off hides it without touching what it created.
    enabled: Optional[bool] = None
    #: Which initiatives this app's initiative-scoped surfaces appear in.
    #: ``{}`` is every one of them; ``{"initiatives": [12, 15]}`` narrows it.
    #: Left out entirely, the current placement is untouched.
    placement: Optional[Dict[str, Any]] = None


class GuildAppConfigUpdate(SanitizedBaseModel):
    """Guild-scoped connection values, keyed by connection then field.

    A key sent as ``null`` clears that value; a key left out is untouched, so a
    form rendering part of a connection cannot wipe the rest.

    Deliberately untyped at this layer. A credential is opaque bytes to us, so
    sanitizing one would corrupt it, and the declared field types live in the
    pinned definition rather than in this schema — the service checks each value
    against the type its own connection declared, which coercion here would
    quietly defeat (a ``true`` arriving at an ``int`` field must be refused, not
    turned into ``1``).
    """

    values: Dict[str, Dict[str, Any]] = {}


class GuildAppArtifact(SanitizedBaseModel):
    """One thing an install produced."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    type: str
    id: int


class GuildAppConnectionRead(SanitizedBaseModel):
    """One connection of an install, as the current viewer sees it.

    ``has_value`` is the whole of what is disclosed about stored values. For a
    per-member connection the presence, status and account label are the
    *viewer's own* — a colleague who has connected and one who has not are both
    looking at a correct answer, because the underlying vendor access genuinely
    differs per person.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: str
    scope: str
    label: Dict[str, str] = {}
    #: The declared fields, verbatim from the pinned definition, so one generic
    #: form renderer can draw any app's settings page.
    fields: List[Dict[str, Any]] = []
    #: What the connection says it will use the credential for. Display-only.
    access_hint: Optional[Dict[str, Any]] = None
    #: The non-secret values, so a form can show what is currently set. Secret
    #: fields are absent from this by construction — they live in a column this
    #: never reads.
    values: Dict[str, Any] = {}
    #: Which fields hold a value, secret ones included. Never the values.
    has_value: Dict[str, bool] = {}
    #: Whether everything this connection declared it needs is present.
    satisfied: bool = False
    #: Where the app runs its vendor flow, for an interactive connection.
    connect_path: Optional[str] = None
    #: The viewer's own state on an interactive connection.
    status: Optional[str] = None
    account_label: Optional[str] = None
    blocked: bool = False


class GuildAppRead(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    guild_id: int
    listing_uid: str
    listing_version: str
    app_kind: str
    name: str
    enabled: bool
    #: What the install produced — for a tool instance, the row it created, so
    #: the sidebar can link straight to it.
    artifacts: List[GuildAppArtifact] = []
    #: Whether a guild admin still has a guild-scoped connection to fill in.
    needs_config: bool = False
    #: What the app reported about the configuration it was given.
    config_state: str = "unverified"
    config_state_detail: Optional[str] = None
    #: Which tool this app mounts, when it mounts one. Read off the pinned
    #: definition so the client need not fetch the catalog to render an entry.
    tool: Optional[str] = None
    #: The listing's artwork, so the sidebar can draw this install. Looked up
    #: from the catalog rather than pinned: a publisher who changes their
    #: picture changes it everywhere the app is shown.
    avatar_url: Optional[str] = None
    #: What a service app contributes, from its pinned definition.
    features: List[str] = []
    #: The pinned definition itself, verbatim.
    #:
    #: A passthrough rather than a read: this build gives meaning to parts of it
    #: (``connections``, ``app_kind``) and none at all to others — the
    #: ``automation`` block belongs to the automation service, which parses it
    #: against its own schema off this same payload rather than through an
    #: endpoint that would have to understand it. Serving the snapshot the guild
    #: pinned, not whatever the catalog holds today, is what lets a reader say
    #: what *this* install actually is. It never carries a stored value: the
    #: definition describes the form, and what was typed into it lives in
    #: columns nothing here reads.
    definition: Dict[str, Any] = {}
    #: Which initiatives this app's initiative-scoped surfaces appear in, as the
    #: guild's admins set it. ``{}`` — the default — is every one of them.
    #: Placement rather than permission: it is the guild's own answer to where
    #: an app belongs, so it reads the same for everyone.
    placement: Dict[str, Any] = {}
    #: The deployment provides this app to every guild, and a guild admin
    #: neither removes nor disables it. The affordances are absent rather than
    #: erroring, so the client is told which installs those are.
    mandatory: bool = False
    #: Whether what this app offers can be reached right now. False for a
    #: service app whose registration is missing or switched off — the install
    #: stays where it is and says why it is doing nothing.
    available: bool = True
    installed_by_id: int
    created_at: datetime
    updated_at: datetime


class GuildAppDetail(GuildAppRead):
    """An install plus its connections, for the settings page.

    Separate from the list payload because the connection blocks carry the whole
    pinned form and the sidebar has no use for it.
    """

    connections: List[GuildAppConnectionRead] = []


class GuildAppListResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[GuildAppRead]


class GuildAppConnectStart(SanitizedBaseModel):
    """Where to send the member so the app can run the vendor's flow.

    ``connection_ref`` is the handle the app will store its result against, and
    the only name it ever learns for this person. It travels in the URL because
    it is an identifier rather than a credential — random, per (install,
    connection, member), and useless without the app's own authenticated
    write-back channel.

    ``connect_url`` is the address to open: the registration's base URL joined
    to the path the manifest declared. It is absent when this deployment has no
    live registration for the app, in which case there is nowhere to send
    anyone; ``connect_path`` still reports what the manifest asked for.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    connection_id: str
    connection_ref: str
    connect_path: str
    connect_url: Optional[str] = None
    status: str


class GuildAppHandoff(SanitizedBaseModel):
    """A short-lived credential for one of an app's embedded surfaces.

    The token reaches the iframe by ``postMessage`` and never a query string,
    and it is worth a minute. ``allowed_origins`` is what the SPA posts to and
    accepts messages from — the registration's own list, not a client guess.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    handoff_token: str
    expires_in_seconds: int
    embed_url: str
    allowed_origins: List[str] = []
    audience: str
    surface_id: str


class GuildAppMemberConnection(SanitizedBaseModel):
    """One member's connection, in the admin's Members view.

    Who connected, as which vendor account, when, and whether they are blocked.
    No values, and no ``connection_ref`` — the handle is between the platform
    and the app, and putting it in an admin screen would make it something
    people copy around.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    connection_id: str
    user_id: int
    status: str
    account_label: Optional[str] = None
    blocked: bool = False
    blocked_by_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class GuildAppConnectionSummary(SanitizedBaseModel):
    """The aggregate an admin actually wants: how many of the guild connected."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    connection_id: str
    label: Dict[str, str] = {}
    connected_count: int = 0
    blocked_count: int = 0
    member_count: int = 0


class GuildAppMembersResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    summary: List[GuildAppConnectionSummary] = []
    items: List[GuildAppMemberConnection] = []


# --- serialization ----------------------------------------------------------


def serialize_guild_app(
    app: Any,
    *,
    install_state: Optional[InstallState] = None,
    avatar_url: Optional[str] = None,
) -> GuildAppRead:
    """One install as the client sees it.

    ``install_state`` is what this deployment's registration says about the app
    (§7.7): whether the platform provides it, and whether it can be reached at
    all. It is passed in rather than looked up here so a list of installs
    resolves it once.
    """
    definition = app.definition or {}
    state = app_config_service.config_state(app)
    features = definition.get("features")
    service_state = install_state or InstallState()
    return GuildAppRead(
        id=app.id,
        guild_id=app.guild_id,
        listing_uid=app.listing_uid,
        listing_version=app.listing_version,
        app_kind=app.app_kind,
        name=app.name,
        enabled=app.enabled,
        artifacts=[GuildAppArtifact(**artifact) for artifact in app_artifacts(app)],
        needs_config=state.needs_config,
        config_state=state.state,
        config_state_detail=state.detail,
        tool=definition.get("tool"),
        avatar_url=avatar_url,
        features=list(features) if isinstance(features, list) else [],
        definition=definition,
        placement=app.placement or {},
        mandatory=service_state.mandatory,
        available=service_state.available,
        installed_by_id=app.installed_by_id,
        created_at=app.created_at,
        updated_at=app.updated_at,
    )


def serialize_connection(
    app: Any,
    connection: Dict[str, Any],
    *,
    member_row: Any = None,
) -> GuildAppConnectionRead:
    """One connection block for the viewer looking at it.

    A guild-scoped connection reads its presence off the install row; a
    per-member one reads it off the viewer's own row, which is why an unrelated
    member's state can never leak through this payload — there is no branch that
    could reach another row.
    """
    connection_id = connection.get("id") or ""
    scope = connection.get("scope") or "static"

    if scope == "static":
        stored_config = (app.config or {}).get(connection_id) or {}
        stored_secrets = (app.config_secrets or {}).get(connection_id) or {}
    else:
        stored_config = (member_row.config or {}) if member_row is not None else {}
        stored_secrets = (
            (member_row.config_secrets or {}) if member_row is not None else {}
        )

    return GuildAppConnectionRead(
        id=connection_id,
        scope=scope,
        label=connection.get("label") or {},
        fields=connection.get("fields") or [],
        access_hint=connection.get("access_hint"),
        values=dict(stored_config),
        has_value=app_config_service.has_value_map(
            connection, stored_config, stored_secrets
        ),
        satisfied=app_config_service.is_satisfied(
            connection, stored_config, stored_secrets
        ),
        connect_path=connection.get("connect_path"),
        status=member_row.status if member_row is not None else None,
        account_label=member_row.account_label if member_row is not None else None,
        blocked=member_row is not None and member_row.blocked_at is not None,
    )


def serialize_guild_app_detail(
    app: Any,
    *,
    member_rows: Dict[str, Any],
    install_state: Optional[InstallState] = None,
    avatar_url: Optional[str] = None,
) -> GuildAppDetail:
    """The install and its connections, from the viewer's own perspective."""
    base = serialize_guild_app(app, install_state=install_state, avatar_url=avatar_url)
    connections = [
        serialize_connection(
            app, connection, member_row=member_rows.get(connection.get("id") or "")
        )
        for connection in app_config_service.definition_connections(app.definition)
    ]
    return GuildAppDetail(**base.model_dump(), connections=connections)


def serialize_member_connection(row: Any) -> GuildAppMemberConnection:
    return GuildAppMemberConnection(
        connection_id=row.connection_id,
        user_id=row.user_id,
        status=row.status,
        account_label=row.account_label,
        blocked=row.blocked_at is not None,
        blocked_by_id=row.blocked_by_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
