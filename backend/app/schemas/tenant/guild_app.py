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
from typing import (
    Annotated,
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    TYPE_CHECKING,
    Union,
)

from pydantic import ConfigDict, Field

from app.models.tenant.app_member_consent import ConsentAccess, ConsentStatus
from app.schemas.base import SanitizedBaseModel
from app.services.marketplace.registration_lookup import InstallState
from app.services.tenant import app_config as app_config_service
from app.services.tenant.guild_apps import (
    grantable_scopes,
    requested_scopes,
    surface_openability,
)

if TYPE_CHECKING:  # pragma: no cover
    from app.db.guild_standing import GuildContext


class GuildAppInstall(SanitizedBaseModel):
    """Install a listing into this guild, with the seat's consent.

    The definition comes from the catalog, and the content the install creates
    is made server-side. What the request adds is the seat's answer to the
    install dialog: what the app may reach, where it appears, and who opens it
    there. The install, its grant and its placements are one transaction.
    """

    listing_uid: str = Field(max_length=14)
    #: Overrides the listing's own default for the content this creates.
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    #: The scopes the seat grants. Each must be one the manifest requests and
    #: one the registration's ceiling allows, as for ``PUT …/scopes``. Left
    #: out, nothing is granted.
    granted_scopes: List[str] = Field(default_factory=list, max_length=64)
    #: Where the app's initiative surfaces appear: ``"all"`` for every
    #: initiative that exists now, or a list of this guild's initiative ids.
    #: Left out, the app is placed nowhere.
    placements: Union[Literal["all"], Annotated[List[int], Field(max_length=1000)]] = (
        Field(default_factory=list)
    )
    #: The built-in initiative roles that may open the app in each placement,
    #: by name (``moderator``, ``project_manager``, ``member``), resolved to
    #: each initiative's own role of that name.
    role_kinds: List[str] = Field(default_factory=lambda: ["moderator"], max_length=10)


class GuildAppUpdate(SanitizedBaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    #: Turning an app off hides it without touching what it created.
    enabled: Optional[bool] = None
    #: Whether published versions are applied on their own. On until a guild
    #: admin turns it off, after which the Update button is how they land.
    auto_update: Optional[bool] = None
    #: The initiatives this app's initiative-scoped surfaces appear in, as the
    #: whole set: an initiative left out is no longer placed. An empty list
    #: places the app in none. Left out entirely, placement is untouched.
    placed_initiative_ids: Optional[List[int]] = None


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
    #: Whether the connection is established through the vendor's own flow,
    #: which Initiative runs: always on an interactive connection, and on a
    #: guild-wide one an admin connects rather than types.
    runs_flow: bool = False
    #: The viewer's own state on an interactive connection: ``pending``,
    #: ``connected``, ``expired`` (reconnect) or ``blocked``.
    status: Optional[str] = None
    account_label: Optional[str] = None
    blocked: bool = False


class AppPlacementRead(SanitizedBaseModel):
    """One initiative an app is placed in, and who may open it there."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    initiative_id: int
    #: The initiative roles allowed to open the app's surfaces here.
    role_ids: List[int] = []


class AppPlacementUpdate(SanitizedBaseModel):
    """Who may open an app's surfaces in one initiative.

    The whole set: a role left out is no longer allowed. Every id must be a
    role of that initiative. An empty list places the app with no role, so
    only guild admins open it there.
    """

    role_ids: List[int] = Field(default_factory=list, max_length=200)


class GuildAppScopesUpdate(SanitizedBaseModel):
    """The scopes the seat grants an install, as the whole set.

    Each must be one the app's manifest requests and one this deployment
    allows the app. An empty list withdraws every grant.
    """

    granted: List[str] = Field(default_factory=list, max_length=64)


class AppSurfaceAccessRead(SanitizedBaseModel):
    """Where the viewer may open one of an app's surfaces.

    Computed on the server by the same decision the handoff makes, so the
    client offers exactly the doors that open.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    surface_id: str
    #: Whether the viewer may open it at the community level.
    openable_guild_wide: bool = False
    #: The initiatives the viewer may open it in.
    openable_initiatives: List[int] = []


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
    #: Whether this install tracks its listing. True unless a guild admin chose
    #: to apply versions by hand.
    auto_update: bool = True
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
    #: The initiatives this app's initiative-scoped surfaces appear in, as the
    #: seat set them, each with the roles allowed to open it there. An
    #: initiative not listed is one the app does not appear in. Placement
    #: rather than permission: it is the community's own answer to where an
    #: app belongs, so it reads the same for everyone.
    placements: List[AppPlacementRead] = []
    #: Each embedded surface the pinned definition declares, with where the
    #: viewer may open it.
    surface_access: List[AppSurfaceAccessRead] = []
    #: The scopes the community's seat granted this install: empty until the
    #: seat grants some, and never wider than what the manifest requests or
    #: the registration allows.
    granted_scopes: List[str] = []
    #: The deployment provides this app to every guild, and a guild admin
    #: neither removes nor disables it. The affordances are absent rather than
    #: erroring, so the client is told which installs those are.
    mandatory: bool = False
    #: Whether what this app offers can be reached right now. False for a
    #: service app whose registration is missing or switched off — the install
    #: stays where it is and says why it is doing nothing.
    available: bool = True
    created_by: int
    created_at: datetime
    updated_at: datetime


class GuildAppConsentRead(SanitizedBaseModel):
    """One request from this app to act as the viewer, and their answer.

    ``label`` is the app's own description of what it wants to do, shown as
    the app's words. ``purpose`` is the app's id for it; absent for app-wide
    consent.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    purpose: Optional[str] = None
    label: str
    #: The one initiative the purpose is bound to, when it is.
    initiative_id: Optional[int] = None
    requested_access: ConsentAccess
    granted_access: Optional[ConsentAccess] = None
    status: ConsentStatus
    requested_at: datetime
    granted_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None


class GuildAppConsentAnswer(SanitizedBaseModel):
    """Allow a request, at ``access``: never more than the app asked for.
    Declining is withdrawing a request that was never granted."""

    access: ConsentAccess


class GuildAppMemberConsent(GuildAppConsentRead):
    """One member's answer to one of the app's requests, in the seat's Members
    view."""

    user_id: int


class AppSurfaceSummary(SanitizedBaseModel):
    """One of an app's embedded surfaces, by id and by its localized name."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: str
    name: Dict[str, str] = {}


class GuildAppUpgradeAsks(SanitizedBaseModel):
    """A version that asks for more than the install holds.

    ``added_scopes`` are grantable scopes neither the grant nor the pinned
    version names; ``added_surfaces`` are surfaces inside initiatives the
    pinned version does not have. ``declined`` says the seat declined this
    version: the install stays where it is and the sweep does not ask again.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    version: str
    added_scopes: List[str] = []
    added_surfaces: List[AppSurfaceSummary] = []
    declined: bool = False


class GuildAppUpgrade(SanitizedBaseModel):
    """The seat's consent to a version that asks for more.

    ``version`` is the version the seat was shown; if the catalog offers a
    different one now, nothing is applied. ``add_scopes`` are the scopes the
    seat grants with it, each requested by that version and within the
    ceiling. Consenting to a version's new surfaces alone sends none.
    """

    version: str = Field(max_length=32)
    add_scopes: List[str] = Field(default_factory=list, max_length=64)


class GuildAppDecline(SanitizedBaseModel):
    """Keep the pinned version, and stop being asked about this one."""

    version: str = Field(max_length=32)


class GuildAppDetail(GuildAppRead):
    """An install plus its connections, for the settings page.

    Separate from the list payload because the connection blocks carry the whole
    pinned form and the sidebar has no use for it.
    """

    connections: List[GuildAppConnectionRead] = []
    #: The viewer's own answers to this app's requests to act as them, one per
    #: purpose, the app-wide one first. Nobody else's.
    consents: List[GuildAppConsentRead] = []
    #: The version this install would move to if it updated now, and absent
    #: when there is none — an install already on the newest, and one whose
    #: listing is gone or has published nothing this build can run, are one
    #: answer to the only question being asked. Only the detail read carries it:
    #: it costs a catalog lookup, and it is the page offering the Update button
    #: that needs the answer.
    update_version: Optional[str] = None
    #: The scopes the pinned manifest asks for, in vocabulary order.
    requested_scopes: List[str] = []
    #: The requested scopes this deployment allows the seat to grant. A
    #: requested scope missing here is one the server would refuse.
    grantable_scopes: List[str] = []
    #: What ``update_version`` asks for beyond what the install holds, when it
    #: asks for anything. Absent for a version that asks nothing new, which
    #: applies without consent.
    pending_update: Optional[GuildAppUpgradeAsks] = None
    #: For each ``apps:`` scope above, the requested ones and those the pending
    #: version adds: the name the app it lets this one use goes by, keyed by
    #: that app's public id. Its public id when the catalog has no name for it.
    app_names: Dict[str, str] = {}


class GuildAppListResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[GuildAppRead]


class GuildAppConnectStart(SanitizedBaseModel):
    """Where to send the person connecting: the vendor's authorization page,
    or its install page for a connection an organization installs.

    Initiative runs the flow, and the vendor returns the person to Initiative's
    own callback. Nothing is stored until it does.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    connection_id: str
    connect_url: str
    #: The viewer's current state on this connection, before the flow runs.
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
    #: Every member's answers to this app's requests to act as them. Beside the
    #: connections rather than in a view of its own: both answer "what does this
    #: app have of this member's", and an admin governing one wants the other in
    #: the same place.
    consents: List[GuildAppMemberConsent] = []


# --- serialization ----------------------------------------------------------


def serialize_guild_app(
    app: Any,
    *,
    context: "GuildContext",
    install_state: Optional[InstallState] = None,
    avatar_url: Optional[str] = None,
    placements: Sequence[Any] = (),
    artifacts: Sequence[Dict[str, Any]] = (),
) -> GuildAppRead:
    """One install as the client sees it.

    ``install_state`` is what this deployment's registration says about the app
    (§7.7): whether the platform provides it, and whether it can be reached at
    all. It is passed in rather than looked up here so a list of installs
    resolves it once. ``placements`` are the install's ``app_placements`` rows,
    and ``artifacts`` what it owns at guild scope, loaded by the caller for the
    same reason.
    """
    definition = app.definition or {}
    state = app_config_service.config_state(app)
    openability = surface_openability(
        definition,
        placements=placements,
        is_guild_admin=context.is_admin,
        member_role_ids=context.member_role_ids,
    )
    features = definition.get("features")
    service_state = install_state or InstallState()
    return GuildAppRead(
        id=app.id,
        guild_id=context.guild_id,
        listing_uid=app.listing_uid,
        listing_version=app.listing_version,
        app_kind=app.app_kind,
        name=app.name,
        enabled=app.enabled,
        auto_update=app.auto_update,
        artifacts=[GuildAppArtifact(**artifact) for artifact in artifacts],
        needs_config=state.needs_config,
        config_state=state.state,
        config_state_detail=state.detail,
        tool=definition.get("tool"),
        avatar_url=avatar_url,
        features=list(features) if isinstance(features, list) else [],
        definition=definition,
        placements=[
            AppPlacementRead(
                initiative_id=row.initiative_id, role_ids=list(row.role_ids or [])
            )
            for row in sorted(placements, key=lambda row: row.initiative_id)
        ],
        surface_access=[
            AppSurfaceAccessRead(
                surface_id=one.surface_id,
                openable_guild_wide=one.openable_guild_wide,
                openable_initiatives=list(one.openable_initiatives),
            )
            for one in openability
        ],
        granted_scopes=sorted(app.granted_scopes or []),
        mandatory=service_state.mandatory,
        available=service_state.available,
        created_by=app.created_by,
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

    declared = {
        field.get("key")
        for field in connection.get("fields") or []
        if isinstance(field, dict)
    }
    return GuildAppConnectionRead(
        id=connection_id,
        scope=scope,
        label=connection.get("label") or {},
        fields=connection.get("fields") or [],
        access_hint=connection.get("access_hint"),
        # Declared fields only: a flow's tokens and their expiry sit beside
        # them under reserved keys, and are nobody's to read here.
        values={key: value for key, value in stored_config.items() if key in declared},
        has_value=app_config_service.has_value_map(
            connection, stored_config, stored_secrets
        ),
        satisfied=app_config_service.is_satisfied(
            connection, stored_config, stored_secrets
        ),
        runs_flow=app_config_service.runs_vendor_flow(connection),
        status=member_row.status if member_row is not None else None,
        account_label=member_row.account_label if member_row is not None else None,
        blocked=member_row is not None and member_row.blocked_at is not None,
    )


def serialize_guild_app_detail(
    app: Any,
    *,
    context: "GuildContext",
    member_rows: Dict[str, Any],
    install_state: Optional[InstallState] = None,
    avatar_url: Optional[str] = None,
    update_offer: Any = None,
    placements: Sequence[Any] = (),
    artifacts: Sequence[Dict[str, Any]] = (),
    consent_rows: Sequence[Any] = (),
    app_names: Optional[Dict[str, str]] = None,
) -> GuildAppDetail:
    """The install and its connections, from the viewer's own perspective.

    ``update_offer`` (an ``app_updates.UpdateOffer``) is resolved by the
    caller, which is the layer holding a session that can read the catalog.
    """
    base = serialize_guild_app(
        app,
        context=context,
        install_state=install_state,
        avatar_url=avatar_url,
        placements=placements,
        artifacts=artifacts,
    )
    connections = [
        serialize_connection(
            app, connection, member_row=member_rows.get(connection.get("id") or "")
        )
        for connection in app_config_service.definition_connections(app.definition)
    ]
    return GuildAppDetail(
        **base.model_dump(),
        connections=connections,
        consents=[serialize_consent(row) for row in consent_rows],
        update_version=update_offer.version if update_offer is not None else None,
        pending_update=serialize_upgrade_asks(app, update_offer),
        requested_scopes=requested_scopes(app.definition),
        grantable_scopes=grantable_scopes(
            app.definition, (install_state or InstallState()).scope_ceiling
        ),
        app_names=dict(app_names or {}),
    )


def upgrade_asks_read(version: str, asks: Any, *, declined: bool = False):
    """What a version asks for, as the client reads it."""
    return GuildAppUpgradeAsks(
        version=version,
        added_scopes=list(asks.added_scopes),
        added_surfaces=[
            AppSurfaceSummary(
                id=surface["id"],
                name={
                    str(key): str(value)
                    for key, value in (surface.get("name") or {}).items()
                },
            )
            for surface in asks.added_surfaces
        ],
        declined=declined,
    )


def serialize_upgrade_asks(app: Any, offer: Any) -> Optional[GuildAppUpgradeAsks]:
    """The offered version's asks, or ``None`` when it asks nothing new."""
    if offer is None or not offer.asks.asks_more:
        return None
    return upgrade_asks_read(
        offer.version, offer.asks, declined=app.declined_version == offer.version
    )


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


def serialize_consent(row: Any) -> GuildAppConsentRead:
    return GuildAppConsentRead(
        id=row.id,
        purpose=row.purpose,
        label=row.label,
        initiative_id=row.initiative_id,
        requested_access=ConsentAccess(row.requested_access),
        granted_access=(
            ConsentAccess(row.granted_access) if row.granted_access else None
        ),
        status=row.status,
        requested_at=row.requested_at,
        granted_at=row.granted_at,
        revoked_at=row.revoked_at,
    )


def serialize_member_consent(row: Any) -> GuildAppMemberConsent:
    return GuildAppMemberConsent(
        **serialize_consent(row).model_dump(), user_id=row.user_id
    )
