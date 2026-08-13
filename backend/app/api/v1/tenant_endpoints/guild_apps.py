"""Apps installed into a guild.

Reading is open to every member — the sidebar has to know which apps are there,
and an app's existence is guild-wide knowledge. Installing, renaming, disabling,
upgrading, configuring and removing are guild-admin actions: an app mounts a
guild-wide surface, which is the guild's shape rather than any one member's.

**Connecting is not an admin action.** Where a vendor authorizes a person rather
than an organization, each member connects their own account, and installation
never waits for anyone to do so. Admins govern the install and its guild-wide
credentials; they can see who connected as which vendor account and end that
access, but they neither perform another member's connection nor read its
values.

What a member may *do* inside an app is not decided here. The content an app
creates carries its own grants, and the tool that owns it enforces them exactly
as it does for initiative content. An app's *embedded* surfaces are the
exception, because they have no local content to carry grants: the handoff mint
is where who-may-open-this is settled, against the visibility the manifest
declared.

Two things a guild admin does not govern. An app the deployment marks mandatory
is installed everywhere and is neither removable nor disableable here — the
operator's registration decides whether it exists. And the operator's kill
switch outranks everything: a service whose registration is switched off reaches
nothing, whether or not the guild wanted it.
"""

import logging
from datetime import datetime, timezone
from typing import Annotated, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.messages import (
    GuildAppMessages,
    InitiativeMessages,
    MarketplaceMessages,
)
from app.db import session as db_session
from app.models.platform.guild import GuildMembership
from app.models.platform.user import User
from app.models.tenant.guild_app import GuildApp
from app.models.tenant.initiative import Initiative
from app.schemas.tenant.guild_app import (
    GuildAppConfigUpdate,
    GuildAppConnectionSummary,
    GuildAppConnectStart,
    GuildAppDetail,
    GuildAppHandoff,
    GuildAppInstall,
    GuildAppListResponse,
    GuildAppMembersResponse,
    GuildAppRead,
    GuildAppUpdate,
    serialize_guild_app,
    serialize_guild_app_detail,
    serialize_member_connection,
)
from app.services import rls as rls_service
from app.services.marketplace import catalog as catalog_service
from app.services.marketplace import registration_lookup
from app.services.marketplace.definitions import (
    APP_KINDS,
    GUILD_INSTALLABLE_APP_KINDS,
)
from app.services.marketplace.installs import (
    ListingInstallError,
    resolve_listing_install,
)
from app.services.membership import initiative_scope_clause
from app.services.platform import guilds as guilds_service
from app.services.tenant import app_config as app_config_service
from app.services.tenant import app_connections as connections_service
from app.services.tenant import app_handoff as handoff_service
from app.services.tenant import app_revocation as revocation_service
from app.services.tenant import guild_apps as guild_apps_service

logger = logging.getLogger(__name__)

router = APIRouter()

#: The same installs, reached from inside one initiative. Mounted at the guild
#: root rather than under ``/apps`` because the initiative comes first in the
#: path — it is what the request is scoped to, and an app is what it is asking
#: about.
initiative_router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_active_user)]
GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_guild_admin(guild_context: GuildContext) -> None:
    if not rls_service.is_guild_admin(guild_context.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildAppMessages.ADMIN_REQUIRED,
        )


async def _app_avatar(session: AsyncSession, app: GuildApp) -> Optional[str]:
    """The artwork for one install's listing."""
    avatars = await catalog_service.listing_avatars(session, [app.listing_uid])
    return avatars.get(app.listing_uid)


async def _load_initiative(
    session: RLSSessionDep, initiative_id: int, user_id: int
) -> Initiative:
    """The initiative this request is scoped to, or a 404.

    Scoped with ``initiative_scope_clause`` — the one rule initiative content
    reads use — so what is reachable here is what is reachable anywhere else.
    "Not yours" and "not there" are one answer, as they are on every other
    initiative-scoped read.
    """
    initiative = (
        await session.exec(
            select(Initiative).where(
                Initiative.id == initiative_id,
                initiative_scope_clause(user_id, Initiative.id),
            )
        )
    ).first()
    if initiative is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.NOT_FOUND,
        )
    return initiative


async def _load(session: RLSSessionDep, app_id: int) -> GuildApp:
    app = (await session.exec(select(GuildApp).where(GuildApp.id == app_id))).first()
    if app is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildAppMessages.NOT_FOUND,
        )
    return app


async def _resolve_app_listing(session: RLSSessionDep, listing_uid: str):
    """The catalog rows behind an app install, as an HTTP answer.

    The resolving itself is shared with dashboards (``services.marketplace``);
    only the mapping to a status code belongs to this layer.
    """
    try:
        return await resolve_listing_install(session, listing_uid, kind="app")
    except ListingInstallError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND if exc.not_found else status.HTTP_409_CONFLICT
            ),
            detail=exc.code,
        ) from exc


def _require_installable_kind(definition: dict) -> None:
    """Two separate refusals, because they are two different mistakes.

    A listing that is not an app at all is one answer; an app of a *kind* this
    build cannot mount is another. Every kind the vocabulary declares is
    mountable today, so the second refusal is the guard for a kind added ahead
    of the machinery that serves it — reaching the installer with one would
    answer a clear refusal with a 500.
    """
    app_kind = definition.get("app_kind")
    if app_kind not in APP_KINDS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=GuildAppMessages.NOT_AN_APP,
        )
    if app_kind not in GUILD_INSTALLABLE_APP_KINDS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=GuildAppMessages.KIND_NOT_INSTALLABLE,
        )


async def _require_removable(app: GuildApp) -> None:
    """Refuse to remove or turn off an app the deployment provides.

    Mandatory constrains guild admins, not the operator: an app marked so on
    its registration stays in every guild until the operator says otherwise.
    The UI omits the affordances entirely, so this answers a request that
    arrived some other way — and it is read from the registration each time, so
    the moment an operator clears the flag the same app becomes removable with
    nothing migrated.
    """
    state = await registration_lookup.install_state(app.definition)
    if state.mandatory:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=GuildAppMessages.MANDATORY,
        )


def _connection_or_404(app: GuildApp, connection_id: str) -> dict:
    connection = app_config_service.connection_by_id(app.definition, connection_id)
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildAppMessages.CONNECTION_NOT_FOUND,
        )
    return connection


async def _flush_revocations(session) -> None:
    """Deliver whatever the just-committed transaction queued.

    After the commit, always: the app is told a credential is finished only once
    the deletion that finished it is durable.
    """
    intents = revocation_service.drain_revocations(session)
    if intents:
        await revocation_service.dispatch_revocations(intents)


async def _member_rows(session, *, app_id: int, user_id: int) -> dict:
    rows = await connections_service.list_member_connections(
        session, app_id=app_id, user_id=user_id
    )
    return {row.connection_id: row for row in rows}


# ---------------------------------------------------------------------------
# The install itself
# ---------------------------------------------------------------------------


@router.get("/", response_model=GuildAppListResponse)
async def list_guild_apps(
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> GuildAppListResponse:
    """Every app installed in this guild, enabled or not.

    Disabled ones are included so an admin can find and re-enable them; the
    sidebar filters to enabled. A service app whose registration is gone or
    switched off comes back too, marked unavailable — an install that quietly
    vanished would leave an admin with nothing to look at and nothing to
    remove.
    """
    apps = (
        await session.exec(select(GuildApp).order_by(GuildApp.name, GuildApp.id))
    ).all()
    avatars = await catalog_service.listing_avatars(
        session, [app.listing_uid for app in apps]
    )
    return GuildAppListResponse(
        items=[
            serialize_guild_app(
                app,
                install_state=await registration_lookup.install_state(app.definition),
                avatar_url=avatars.get(app.listing_uid),
            )
            for app in apps
        ]
    )


@router.get("/{app_id}", response_model=GuildAppDetail)
async def get_guild_app(
    app_id: int,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> GuildAppDetail:
    """One install with its connections, from the caller's own perspective.

    Any member may read this: the per-member connection blocks report the
    caller's own state, and a guild-scoped one reports presence rather than
    values, so there is nothing here that belongs to somebody else.
    """
    app = await _load(session, app_id)
    return serialize_guild_app_detail(
        app,
        avatar_url=await _app_avatar(session, app),
        member_rows=await _member_rows(session, app_id=app.id, user_id=current_user.id),
        install_state=await registration_lookup.install_state(app.definition),
    )


@router.post("/", response_model=GuildAppRead, status_code=status.HTTP_201_CREATED)
async def install_guild_app(
    payload: GuildAppInstall,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> GuildAppRead:
    """Install a listing as a guild app.

    The request names a listing; everything stored comes from the catalog row
    and from what the install creates here. One install per listing: an app
    mounts a single guild-wide surface, so a second copy would have nothing to
    be — rename or re-share the one that exists instead.

    Nothing about connections gates this. An app whose credentials are all
    supplied per member installs with none present, and members connect their
    own accounts afterwards if they want what those unlock.
    """
    _require_guild_admin(guild_context)

    listing, version = await _resolve_app_listing(session, payload.listing_uid)

    existing = (
        await session.exec(select(GuildApp).where(GuildApp.listing_uid == listing.uid))
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=GuildAppMessages.ALREADY_INSTALLED,
        )

    definition = dict(version.definition)
    _require_installable_kind(definition)

    name = (payload.name or definition.get("default_name") or listing.name).strip()
    try:
        app = await guild_apps_service.install_app(
            session,
            listing_uid=listing.uid,
            listing_version=version.version,
            definition=definition,
            guild_id=guild_context.guild_id,
            installed_by_id=current_user.id,
            name=name,
        )
        await session.commit()
    except IntegrityError as exc:
        # The look-up above and this insert are not one atomic step, so two
        # installs arriving together both get past it. The unique constraint is
        # what actually holds — at the flush inside the install or at the commit
        # — and this turns losing that race into the same answer the look-up
        # gives.
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=GuildAppMessages.ALREADY_INSTALLED,
        ) from exc
    await session.refresh(app)

    installed = serialize_guild_app(
        app,
        install_state=await registration_lookup.install_state(app.definition),
        avatar_url=await _app_avatar(session, app),
    )
    await _count_install(listing.id)
    return installed


@router.post("/{app_id}/upgrade", response_model=GuildAppDetail)
async def upgrade_guild_app(
    app_id: int,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> GuildAppDetail:
    """Re-pin an installed app to its listing's current version.

    Nothing is ever pushed into a guild: a new version sits in the catalog until
    an admin here asks for it. Applying one replaces this install's definition
    and leaves everything else alone.

    Stored configuration survives, minus anything the new version stopped
    declaring — a value cannot outlive the field it was typed into. Per-member
    connections the new version dropped go the same way, and are revoked rather
    than orphaned.
    """
    _require_guild_admin(guild_context)
    app = await _load(session, app_id)

    _, version = await _resolve_app_listing(session, app.listing_uid)
    if version.version == app.listing_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=MarketplaceMessages.ALREADY_LATEST_VERSION,
        )

    definition = dict(version.definition)
    _require_installable_kind(definition)

    # Stored values are pruned to what the new definition still declares, down
    # to individual fields. A connection it stopped declaring takes its values
    # with it and is revoked on the way out rather than merely dropped, since
    # the app is still holding whatever those values bought it.
    config, config_secrets, dropped = app_config_service.prune_to_definition(
        definition, app.config, app.config_secrets
    )
    for connection_id in sorted(dropped):
        revocation_service.queue_revocation(
            session,
            revocation_service.RevocationIntent(
                guild_id=app.guild_id,
                app_id=app.id,
                listing_uid=app.listing_uid,
                connection_id=connection_id,
                reason="upgraded",
            ),
        )
    app.config = config
    app.config_secrets = config_secrets
    app.definition = definition
    app.listing_version = version.version
    # The app has not seen the new configuration shape yet, so whatever it said
    # about the old one is no longer an answer to the current question.
    app.config_state = "unverified"
    app.config_state_detail = None
    guild_apps_service.touch(app)
    session.add(app)

    surviving = {
        connection.get("id")
        for connection in app_config_service.definition_connections(definition)
    }
    for row in await connections_service.list_app_connections(session, app_id=app.id):
        if row.connection_id not in surviving:
            await connections_service.disconnect(
                session,
                app=app,
                connection_id=row.connection_id,
                user_id=row.user_id,
                reason="upgraded",
            )

    await session.commit()
    await _flush_revocations(session)
    await session.refresh(app)
    return serialize_guild_app_detail(
        app,
        avatar_url=await _app_avatar(session, app),
        member_rows=await _member_rows(session, app_id=app.id, user_id=current_user.id),
        install_state=await registration_lookup.install_state(app.definition),
    )


@router.patch("/{app_id}", response_model=GuildAppRead)
async def update_guild_app(
    app_id: int,
    payload: GuildAppUpdate,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> GuildAppRead:
    """Rename an app, or turn it off without removing what it created.

    Renaming is always allowed — a guild may call an app whatever it likes.
    Turning one off is a different matter for an app the deployment provides:
    that switch belongs to the operator, so it is refused by name here.
    """
    _require_guild_admin(guild_context)
    app = await _load(session, app_id)

    data = payload.model_dump(exclude_unset=True)
    if data.get("name"):
        app.name = data["name"].strip()
    if "enabled" in data and data["enabled"] is not None:
        if not data["enabled"]:
            await _require_removable(app)
        app.enabled = data["enabled"]
    app.updated_at = datetime.now(timezone.utc)
    session.add(app)
    await session.commit()
    await session.refresh(app)
    return serialize_guild_app(
        app,
        install_state=await registration_lookup.install_state(app.definition),
        avatar_url=await _app_avatar(session, app),
    )


@router.delete("/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
async def uninstall_guild_app(
    app_id: int,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> None:
    """Remove an app, ending its access and trashing what it created.

    The two halves are deliberately different. **Credentials are deleted**, both
    the guild's and every member's, and each app is told to let go at the vendor
    — an uninstalled app still receiving a guild's data is the thing this
    prevents. **Content is trashed**, because the events someone put in a guild
    calendar are the guild's, and should survive an admin removing the app for
    as long as the retention window allows.

    An app the deployment provides to every guild is not removable here (§7.7):
    the operator's registration decides whether it exists at all.
    """
    _require_guild_admin(guild_context)
    app = await _load(session, app_id)
    await _require_removable(app)

    retention_days = await guilds_service.get_guild_retention_days(
        session, guild_context.guild_id
    )
    await connections_service.delete_app_connections(session, app=app)
    if app.config_secrets or app.config:
        revocation_service.queue_revocation(
            session,
            revocation_service.RevocationIntent(
                guild_id=app.guild_id,
                app_id=app.id,
                listing_uid=app.listing_uid,
                connection_id="*",
                reason="uninstalled",
            ),
        )
    await guild_apps_service.remove_app_artifacts(
        session,
        app,
        deleted_by_user_id=current_user.id,
        retention_days=retention_days,
    )
    await session.delete(app)
    await session.commit()
    await _flush_revocations(session)


# ---------------------------------------------------------------------------
# Guild-scoped configuration
# ---------------------------------------------------------------------------


@router.put("/{app_id}/config", response_model=GuildAppDetail)
async def update_guild_app_config(
    app_id: int,
    payload: GuildAppConfigUpdate,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> GuildAppDetail:
    """Set the guild-wide values an app's connections ask for.

    Validated against the *pinned* definition, so what an install accepts is the
    form it was configured against rather than whatever the catalog says today.
    Secret fields are encrypted on the way in and never come back out; the
    response reports which fields hold a value.

    Only guild-scoped connections are settable here. A per-member one is that
    member's to make, and the fields an app marks ``managed`` arrive on the
    app's own write-back path rather than through a form.
    """
    _require_guild_admin(guild_context)
    app = await _load(session, app_id)

    config = dict(app.config or {})
    secrets = dict(app.config_secrets or {})

    for connection_id, submitted in payload.values.items():
        connection = app_config_service.connection_by_id(app.definition, connection_id)
        if connection is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=GuildAppMessages.CONFIG_UNKNOWN_CONNECTION,
            )
        if connection.get("scope") != "static":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=GuildAppMessages.CONNECTION_NOT_STATIC,
            )
        try:
            new_config, new_secrets = app_config_service.apply_connection_values(
                connection,
                submitted,
                current=config.get(connection_id) or {},
                current_secrets=secrets.get(connection_id) or {},
            )
        except app_config_service.AppConfigError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code
            ) from exc

        if new_config:
            config[connection_id] = new_config
        else:
            config.pop(connection_id, None)
        if new_secrets:
            secrets[connection_id] = new_secrets
        else:
            secrets.pop(connection_id, None)

    app.config = config
    app.config_secrets = secrets
    # The app has not seen these values yet, so its previous verdict no longer
    # describes them. It reports again once it has pulled and checked.
    app.config_state = "unverified"
    app.config_state_detail = None
    guild_apps_service.touch(app)
    session.add(app)
    await session.commit()
    await session.refresh(app)
    return serialize_guild_app_detail(
        app,
        avatar_url=await _app_avatar(session, app),
        member_rows=await _member_rows(session, app_id=app.id, user_id=current_user.id),
        install_state=await registration_lookup.install_state(app.definition),
    )


# ---------------------------------------------------------------------------
# Embedded surfaces
# ---------------------------------------------------------------------------


@router.post("/{app_id}/handoff/{surface_id}", response_model=GuildAppHandoff)
async def create_guild_app_handoff(
    app_id: int,
    surface_id: str,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> GuildAppHandoff:
    """Mint the short-lived credential for one of this app's embedded surfaces.

    Whether the surface may be opened is decided here, under the caller's real
    session, so the app never makes that call and never sees a request from
    somebody who failed it. What the manifest declared as ``visibility``
    governs, read guild-wide: a surface naming any audience narrower than
    ``member`` is reachable here only by the guild's admins, and everything
    else is open to every member of the installing guild.

    The token goes to the iframe by ``postMessage`` — never a query string —
    and expires in a minute.
    """
    app = await _load(session, app_id)
    handoff = await handoff_service.mint_embed_handoff(
        app,
        surface_id=surface_id,
        user_id=current_user.id,
        is_guild_admin=rls_service.is_guild_admin(guild_context.role),
        # This route reaches a guild and names no initiative. A surface that
        # renders only inside one is not offered here.
        initiative_id=None,
        is_initiative_manager=False,
    )
    return _handoff_response(handoff)


@initiative_router.post(
    "/initiatives/{initiative_id}/apps/{app_id}/handoff/{surface_id}",
    response_model=GuildAppHandoff,
    tags=["apps"],
)
async def create_initiative_app_handoff(
    initiative_id: int,
    app_id: int,
    surface_id: str,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> GuildAppHandoff:
    """Mint the credential for a surface opened inside one initiative.

    The install is the guild's — there is one of it, not one per initiative —
    but the surface is being opened somewhere narrower, and the token says so.

    Three gates, outermost first. The initiative must be one this caller can
    reach. The manifest must declare the surface for this scope. And the
    surface's ``visibility`` is then read *here*, where ``member`` means this
    initiative's members and ``initiative_manager`` means its managers — a
    guild admin clears both, as they do everywhere in their own guild.

    The initiative in the minted token is this route's, never the caller's to
    supply, so an app can scope what it shows without asking a second question
    or trusting a parameter.
    """
    initiative = await _load_initiative(session, initiative_id, current_user.id)
    app = await _load(session, app_id)
    handoff = await handoff_service.mint_embed_handoff(
        app,
        surface_id=surface_id,
        user_id=current_user.id,
        is_guild_admin=rls_service.is_guild_admin(guild_context.role),
        initiative_id=initiative.id,
        is_initiative_manager=await rls_service.is_initiative_manager(
            session, initiative_id=initiative.id, user=current_user
        ),
    )
    return _handoff_response(handoff)


def _handoff_response(handoff: handoff_service.EmbedHandoff) -> GuildAppHandoff:
    """The same answer either route gives.

    The initiative is not in it: it is a claim in the token, and the browser
    already knows which initiative it is looking at.
    """
    return GuildAppHandoff(
        handoff_token=handoff.token,
        expires_in_seconds=handoff.expires_in_seconds,
        embed_url=handoff.embed_url,
        allowed_origins=list(handoff.allowed_origins),
        audience=handoff.audience,
        surface_id=handoff.surface_id,
    )


# ---------------------------------------------------------------------------
# A member's own connection
# ---------------------------------------------------------------------------


@router.post(
    "/{app_id}/connections/{connection_id}/connect",
    response_model=GuildAppConnectStart,
)
async def connect_guild_app(
    app_id: int,
    connection_id: str,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> GuildAppConnectStart:
    """Start this member's own connection to an app's vendor.

    Any member may: the vendor is going to authorize *them*, and what the
    resulting credential reaches is what they already reach. The row and its
    opaque handle are minted here so the app has something to write its result
    against; the vendor flow itself runs at the app's own URL.

    That URL is assembled server-side — the registration supplies the address,
    the manifest supplies the path — and carries the ``connection_ref`` so the
    app knows which credential it is about to hold. The ref is an identifier,
    not a credential: it authorizes nothing on its own, and the app writes its
    result back over its own authenticated channel.
    """
    app = await _load(session, app_id)
    if not app.enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=GuildAppMessages.DISABLED
        )

    connection = _connection_or_404(app, connection_id)
    if connection.get("scope") != "interactive":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=GuildAppMessages.CONNECTION_NOT_INTERACTIVE,
        )
    connect_path = connection.get("connect_path")
    if not connect_path:
        # The validator requires one on an interactive connection, so this is a
        # definition pinned before that rule — there is nowhere to send anyone.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=GuildAppMessages.CONNECT_PATH_MISSING,
        )

    # The vendor flow runs at the app's own URL, so it has to be wired up and
    # switched on before a member is sent anywhere.
    registration = await handoff_service.require_live_registration(app)

    existing = await connections_service.get_connection(
        session, app_id=app.id, connection_id=connection_id, user_id=current_user.id
    )
    if connections_service.is_blocked(existing):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildAppMessages.CONNECTION_BLOCKED,
        )

    row = await connections_service.connect(
        session, app=app, connection_id=connection_id, user_id=current_user.id
    )
    await session.commit()
    await session.refresh(row)
    return GuildAppConnectStart(
        connection_id=row.connection_id,
        connection_ref=row.connection_ref,
        connect_path=connect_path,
        connect_url=(
            f"{registration.base_url}{connect_path}"
            f"?connection_ref={quote(row.connection_ref, safe='')}"
        ),
        status=row.status,
    )


@router.delete(
    "/{app_id}/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def disconnect_guild_app(
    app_id: int,
    connection_id: str,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> None:
    """Disconnect: a member's own account, or a guild-wide credential.

    Which one depends on the connection's scope, not on who is asking. A
    per-member connection is always the caller's own — an admin ending somebody
    else's uses the Members endpoints, which record who acted. Clearing a
    guild-wide credential is an admin action, since it is the guild's.
    """
    app = await _load(session, app_id)
    connection = _connection_or_404(app, connection_id)

    if connection.get("scope") == "static":
        _require_guild_admin(guild_context)
        if (app.config or {}).get(connection_id) or (app.config_secrets or {}).get(
            connection_id
        ):
            revocation_service.queue_revocation(
                session,
                revocation_service.RevocationIntent(
                    guild_id=app.guild_id,
                    app_id=app.id,
                    listing_uid=app.listing_uid,
                    connection_id=connection_id,
                    reason="disconnected",
                ),
            )
        app.config = {
            key: value
            for key, value in (app.config or {}).items()
            if key != connection_id
        }
        app.config_secrets = {
            key: value
            for key, value in (app.config_secrets or {}).items()
            if key != connection_id
        }
        app.config_state = "unverified"
        app.config_state_detail = None
        guild_apps_service.touch(app)
        session.add(app)
    else:
        await connections_service.disconnect(
            session,
            app=app,
            connection_id=connection_id,
            user_id=current_user.id,
        )

    await session.commit()
    await _flush_revocations(session)


# ---------------------------------------------------------------------------
# Admin governance of members' connections
# ---------------------------------------------------------------------------


@router.get("/{app_id}/members", response_model=GuildAppMembersResponse)
async def list_guild_app_members(
    app_id: int,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> GuildAppMembersResponse:
    """Who has connected which of this app's per-member connections.

    Guild admins only, and never secret values: what this supports is governance
    — seeing which vendor account somebody connected as, and ending it — rather
    than looking at credentials.
    """
    _require_guild_admin(guild_context)
    app = await _load(session, app_id)

    rows = await connections_service.list_app_connections(session, app_id=app.id)
    member_count = len(
        (
            await session.exec(
                select(GuildMembership.user_id).where(
                    GuildMembership.guild_id == guild_context.guild_id
                )
            )
        ).all()
    )

    summary: list[GuildAppConnectionSummary] = []
    for connection in app_config_service.definition_connections(app.definition):
        if connection.get("scope") != "interactive":
            continue
        connection_id = connection.get("id") or ""
        matching = [row for row in rows if row.connection_id == connection_id]
        summary.append(
            GuildAppConnectionSummary(
                connection_id=connection_id,
                label=connection.get("label") or {},
                connected_count=sum(1 for row in matching if row.blocked_at is None),
                blocked_count=sum(1 for row in matching if row.blocked_at is not None),
                member_count=member_count,
            )
        )

    return GuildAppMembersResponse(
        summary=summary,
        items=[serialize_member_connection(row) for row in rows],
    )


@router.delete(
    "/{app_id}/members/{user_id}/connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_member_connection(
    app_id: int,
    user_id: int,
    connection_id: str,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> None:
    """End one member's connection. They may connect again unless blocked."""
    _require_guild_admin(guild_context)
    app = await _load(session, app_id)
    _connection_or_404(app, connection_id)

    await connections_service.disconnect(
        session,
        app=app,
        connection_id=connection_id,
        user_id=user_id,
        reason="admin_revoked",
    )
    await session.commit()
    await _flush_revocations(session)


@router.post(
    "/{app_id}/members/{user_id}/connections/{connection_id}/block",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def block_member_connection(
    app_id: int,
    user_id: int,
    connection_id: str,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> None:
    """Revoke a member's connection and refuse the next one.

    The lever for "this person should no longer reach that system through us"
    that does not mean uninstalling the app for everyone.
    """
    _require_guild_admin(guild_context)
    app = await _load(session, app_id)
    _connection_or_404(app, connection_id)

    await connections_service.block_member_connection(
        session,
        app=app,
        connection_id=connection_id,
        user_id=user_id,
        blocked_by_id=current_user.id,
    )
    await session.commit()
    await _flush_revocations(session)


@router.delete(
    "/{app_id}/members/{user_id}/connections/{connection_id}/block",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unblock_member_connection(
    app_id: int,
    user_id: int,
    connection_id: str,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> None:
    """Lift a block, so the member may connect their own account again."""
    _require_guild_admin(guild_context)
    app = await _load(session, app_id)
    _connection_or_404(app, connection_id)

    await connections_service.unblock_member_connection(
        session, app=app, connection_id=connection_id, user_id=user_id
    )
    await session.commit()


@router.post("/{app_id}/revoke-all", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_all_member_connections(
    app_id: int,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> None:
    """End every member's connection at once, leaving the install standing.

    For a suspected app or vendor compromise: reacting fast should not cost the
    guild its configuration.
    """
    _require_guild_admin(guild_context)
    app = await _load(session, app_id)

    await connections_service.revoke_all(session, app=app)
    await session.commit()
    await _flush_revocations(session)


async def _count_install(listing_id: Optional[int]) -> None:
    """Tally the install against its listing, after the fact and best-effort —
    the catalog has no request-path writer, and a failed tally must not undo an
    install that already happened."""
    if listing_id is None:
        return
    try:
        async with db_session.AdminSessionLocal() as admin:
            await catalog_service.bump_installs_count(admin, listing_id)
            await admin.commit()
    except Exception:
        logger.warning(
            "marketplace: install count bump failed for listing %s",
            listing_id,
            exc_info=True,
        )
