"""Installing and removing guild apps.

Three shapes, and the difference is what the app brings with it.

A **tool instance** mounts one of this build's own tools at guild scope.
Installing creates an ordinary row in that tool's ordinary table with no
initiative — a guild-level calendar is a `calendars` row with `initiative_id`
NULL — owned by the install, so the sidebar can link straight to it. Nothing
about the tool changes: same table, same UI, same sharing, same trash. The
content is seeded shared with everyone in the guild, which is what makes an app
useful the moment it lands. From there the guild admin decides its sharing:
remove the everyone grant to make it private, add write grants to let
particular members or roles post in it. Writing the row itself is the admin's.

An install is not limited to what it created on the way in. A guild admin
adding another guild calendar gives it to the install too, because the app is
the container: it is the entry that reaches the content, so removing it takes
the content with it rather than stranding rows nothing links to.

An **embed** brings none. It opens a surface the operator configured, so there
is no row to create, nothing to share, and nothing to trash on the way out —
installing it adds an entry, and removing it takes the entry away. Who may open
it is settled by the endpoint that mints its handoff rather than by grants,
which is why such an app reports itself as admin-only.

A **service** app brings connections rather than content: what it needs is
configuration, which lives on the install row, in its secret values
(:func:`store_secrets`) and in each member's own connection. It creates no artifacts here.

**Artifacts are what the install owns.** An install may produce more than
one thing; what it produced is every guild-level row whose owner grant names
it, read as `[{"type": …, "id": …}]`, and removal walks that through
:data:`ARTIFACT_HANDLERS`. Every tool an app may mount has a handler — asserted
by a test rather than left to be noticed the day an uninstall quietly leaves a
row behind.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Iterable, Optional

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.app_scopes import app_scope_target, ordered_scopes
from app.core.audit_events import AuditEventType
from app.models.platform.marketplace import MarketplaceListing
from app.models.tenant.app_placement import AppPlacement
from app.models.tenant.calendar import Calendar
from app.models.tenant.guild_app import GuildApp
from app.models.tenant.guild_app_secret import GuildAppSecret
from app.models.tenant.initiative import (
    BUILTIN_ROLES,
    Initiative,
    InitiativeRoleModel,
)
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.core.messages import GuildAppMessages
from app.db.session import routed_guild_id
from app.services import audit as audit_service
from app.services.marketplace import registration_lookup
from app.services.marketplace.service_apps import is_admin_only
from app.services.platform import guilds as guilds_service
from app.services.tenant import app_config as app_config_service
from app.services.tenant import app_connections as connections_service
from app.services.tenant import app_member_consents as consents_service
from app.services.tenant import webhook_subscriptions as webhook_subscriptions_service
from app.services.tenant.app_revocation import queue_install_revocations
from app.services.tenant.soft_delete import soft_delete_entity

__all__ = [
    "ARTIFACT_HANDLERS",
    "BUILTIN_ROLE_NAMES",
    "ArtifactHandler",
    "PlacementError",
    "PlacementRoleError",
    "SurfaceAccess",
    "SurfaceOpenability",
    "app_artifacts",
    "apply_static_config",
    "artifacts_by_install",
    "clear_static_connection",
    "declared_surfaces",
    "create_app_artifacts",
    "find_mounting_app",
    "has_initiative_surfaces",
    "initiative_surface_ids",
    "install_app",
    "is_placed",
    "load_secrets",
    "lock_install",
    "place_in_every_initiative",
    "place_with_roles",
    "placed_initiative_ids",
    "placement_role_ids",
    "placements_by_install",
    "remove_placement",
    "set_placed_initiatives",
    "set_placement_roles",
    "store_secrets",
    "surface_access",
    "surface_openability",
    "surface_renders_in",
    "touch",
    "uninstall_app",
]

# --- artifacts --------------------------------------------------------------


@dataclass(frozen=True)
class ArtifactHandler:
    """How one kind of artifact is made and unmade.

    ``create`` makes the row, owned by the install; ``remove`` disposes of it.
    Removal is soft wherever the tool has a trash, because what an app created
    is guild content — the events someone put in a guild calendar should survive
    an admin removing the app.
    """

    create: Callable[..., Awaitable[None]]
    remove: Callable[..., Awaitable[None]]


async def _create_calendar(session: AsyncSession, *, app: GuildApp, name: str) -> None:
    calendar = Calendar(
        # No initiative: this belongs to the guild. Its grants decide who reads
        # and writes what it holds, exactly as for an initiative calendar.
        initiative_id=None,
        created_by=app.created_by,
        name=name,
    )
    session.add(calendar)
    await session.flush()

    # Creating it wrote an owner row naming whoever asked, where the request
    # names somebody; the calendar is the install's.
    await session.exec(
        delete(ResourceGrant).where(
            col(ResourceGrant.resource_type) == "calendar",
            col(ResourceGrant.resource_id) == calendar.id,
            col(ResourceGrant.level) == ResourceAccessLevel.owner,
        )
    )
    session.add(
        ResourceGrant(
            resource_type="calendar",
            resource_id=calendar.id,
            app_install_id=app.id,
            level=ResourceAccessLevel.owner,
            initiative_id=None,
        )
    )
    # Shared with the guild from the start — an app nobody can see is not
    # useful, and narrowing it afterwards is one edit to its sharing. At guild
    # scope the everyone grant reads as every member of the guild.
    session.add(
        ResourceGrant(
            resource_type="calendar",
            resource_id=calendar.id,
            all_initiative_members=True,
            level=ResourceAccessLevel.read,
            initiative_id=None,
        )
    )
    await session.flush()


async def _remove_calendar(
    session: AsyncSession,
    artifact_id: int,
    *,
    deleted_by_user_id: Optional[int],
    retention_days: Optional[int],
) -> None:
    calendar = (
        await session.exec(select(Calendar).where(Calendar.id == artifact_id))
    ).first()
    if calendar is None:
        return
    await soft_delete_entity(
        session,
        calendar,
        deleted_by_user_id=deleted_by_user_id,
        retention_days=retention_days,
    )


#: One entry per tool an app may mount at guild scope, keyed by the artifact
#: type (which is the tool's own name). ``guild_apps_test`` asserts this covers
#: every entry in ``MOUNTABLE_TOOLS``, so a tool added to the manifest
#: vocabulary cannot ship without a way to unmake what it created.
ARTIFACT_HANDLERS: dict[str, ArtifactHandler] = {
    "calendar": ArtifactHandler(create=_create_calendar, remove=_remove_calendar),
}


async def artifacts_by_install(
    session: AsyncSession, install_ids: Iterable[int]
) -> dict[int, list[dict[str, Any]]]:
    """What each install produced, as ``[{"type": …, "id": …}]``, in one query.

    An install's artifacts are the guild-level rows it owns: the owner grant
    naming the install is the record, so there is no second list to keep in
    step with it.
    """
    ids = list(install_ids)
    if not ids:
        return {}
    rows = await session.exec(
        select(
            ResourceGrant.app_install_id,
            ResourceGrant.resource_type,
            ResourceGrant.resource_id,
        )
        .where(
            col(ResourceGrant.app_install_id).in_(ids),
            ResourceGrant.level == ResourceAccessLevel.owner,
            col(ResourceGrant.initiative_id).is_(None),
            col(ResourceGrant.resource_type).in_(ARTIFACT_HANDLERS),
        )
        .order_by(col(ResourceGrant.app_install_id), col(ResourceGrant.resource_id))
    )
    grouped: dict[int, list[dict[str, Any]]] = {install_id: [] for install_id in ids}
    for install_id, artifact_type, artifact_id in rows.all():
        grouped[install_id].append({"type": artifact_type, "id": artifact_id})
    return grouped


async def app_artifacts(session: AsyncSession, app: GuildApp) -> list[dict[str, Any]]:
    """What one install produced; see :func:`artifacts_by_install`."""
    return (await artifacts_by_install(session, [app.id]))[app.id]


async def lock_install(session: AsyncSession, app_id: int) -> Optional[GuildApp]:
    """Hold one install's row for the rest of this transaction.

    Several things on this row are values rewritten whole rather than appended
    to — the configuration maps, the connection handles — so writing one means
    reading it, changing it, and putting the result back. Two of those
    overlapping would have the second write carry a value read before the first
    landed, and the first change would be gone with no sign that it had been
    made. Taking the row first puts them in an order instead.

    Removal takes it too, before reading what the install owns. Giving the
    install something waits on it, because the owner grant's foreign key names
    this row, so the new content is either among what removal reads or finds
    the install gone.

    Answers ``None`` if the row is gone, which is the same answer as this guild
    never having had the install.
    """
    return (
        await session.exec(
            select(GuildApp)
            .where(GuildApp.id == app_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).first()


async def load_secrets(session: AsyncSession, app: GuildApp) -> dict[str, Any]:
    """An install's secret values, ``{connection_id: {key: ciphertext}}``.

    Read from ``guild_app_secrets``, which the seat and the system engine read.
    No row reads as ``{}``.
    """
    stored = (
        await session.exec(
            select(GuildAppSecret.secrets).where(GuildAppSecret.install_id == app.id)
        )
    ).first()
    return dict(stored or {})


async def store_secrets(
    session: AsyncSession, app: GuildApp, secrets: Mapping[str, Any]
) -> None:
    """Replace an install's secret values; an empty map removes its row.

    The trigger on ``guild_app_secrets`` rewrites ``guild_apps.secret_fields``
    in the same statement, and ``app`` is refreshed with it. Pending changes to
    ``app`` are flushed first, so the refresh replaces ``secret_fields`` alone.
    """
    await session.flush()
    if secrets:
        insert = pg_insert(GuildAppSecret).values(
            install_id=app.id, secrets=dict(secrets)
        )
        await session.exec(
            insert.on_conflict_do_update(
                index_elements=[GuildAppSecret.install_id],
                set_={"secrets": insert.excluded.secrets},
            )
        )
    else:
        await session.exec(
            delete(GuildAppSecret).where(col(GuildAppSecret.install_id) == app.id)
        )
    await session.refresh(app, ["secret_fields"])


async def find_mounting_app(session: AsyncSession, *, tool: str) -> Optional[GuildApp]:
    """The install that mounts ``tool`` at guild scope, if this guild has one.

    A tool-instance install is the container for what it mounts, so this is the
    question "does this guild have somewhere to put a guild-level calendar" —
    asked before creating one, and answered from the install rows rather than
    from the content, since an install with everything trashed is still the
    container.
    """
    apps = (await session.exec(select(GuildApp))).all()
    for app in apps:
        definition = app.definition or {}
        if (
            definition.get("app_kind") == "tool_instance"
            and definition.get("tool") == tool
        ):
            return app
    return None


async def create_app_artifacts(session: AsyncSession, app: GuildApp) -> None:
    """Create what the app mounts, owned by its install.

    Only a tool instance produces anything. An embed opens a surface that
    already exists, and a **service** app brings connections rather than
    content — its install is the row plus the definition it pinned, and what it
    offers is served from the container the operator registered.
    """
    definition = app.definition or {}
    if definition.get("app_kind") != "tool_instance":
        return

    tool = definition.get("tool")
    handler = ARTIFACT_HANDLERS.get(tool or "")
    if handler is None:
        # Unreachable through the endpoints — the definition validator admits
        # only tools listed there — but this is the place that would need
        # teaching about a new one.
        raise ValueError(f"cannot mount {tool!r} at guild scope")

    await handler.create(session, app=app, name=app.name)


async def install_app(
    session: AsyncSession,
    *,
    listing_uid: str,
    listing_version: str,
    definition: dict,
    guild_id: int,
    created_by: int,
    name: str,
    actor_user_id: Optional[int] = None,
    via: str = "install",
    granted_scopes: Sequence[str] = (),
) -> GuildApp:
    """Create the install row, and whatever the app mounts alongside it.

    One place knows what an install *is*, because there are two callers now: a
    guild admin choosing an app, and the deployment placing a mandatory one into
    every guild (§7.7). The row is flushed rather than committed — the caller
    owns the transaction, since a guild creation commits the install together
    with the rest of the guild's seed.

    ``actor_user_id`` is the account the caller's session runs as — an admin
    choosing the app, or ``None`` for a sweep running as nobody. ``via`` says
    which of the two routes this install came down, and rides the record.

    ``granted_scopes`` is what the seat consented to in the install dialog,
    already checked against the manifest and the ceiling by the caller. It is
    written with the row, so the install never exists without its consent.
    """
    app = GuildApp(
        listing_uid=listing_uid,
        listing_version=listing_version,
        app_kind=definition["app_kind"],
        name=name,
        definition=definition,
        config={},
        granted_scopes=sorted(set(granted_scopes)),
        created_by=created_by,
    )
    session.add(app)
    await session.flush()
    await create_app_artifacts(session, app)
    # Staged in the caller's transaction, after the flush that gives the install
    # its id, so the record and the install land together or not at all.
    await audit_service.record(
        session,
        event_type=AuditEventType.APP_INSTALLED,
        actor_user_id=actor_user_id,
        guild_id=guild_id,
        target_type="app",
        target_id=app.id,
        detail={
            "listing_uid": listing_uid,
            "version": listing_version,
            "via": via,
            "granted_scopes": sorted(set(granted_scopes)),
        },
    )
    return app


async def uninstall_app(
    session: AsyncSession, app: GuildApp, *, actor_user_id: int
) -> None:
    """Remove an install, ending its access and trashing what it created.

    The two halves are deliberately different. **Credentials are deleted**, both
    the guild's and every member's, and each app is told to let go at the vendor
    — an uninstalled app still receiving a guild's data is the thing this
    prevents. **Content is trashed** through the ordinary soft-delete path,
    because the events someone put in a guild calendar are the guild's, and
    should survive an admin removing the app for as long as the retention
    window allows.

    The caller holds the install row (:func:`lock_install`), commits, and then
    dispatches the queued revocations.
    """
    guild_id = routed_guild_id(session)
    retention_days = await guilds_service.get_guild_retention_days(session)
    connections = await connections_service.delete_app_connections(session, app=app)
    # Every member's answers to its requests go with it. The foreign key would
    # take them with the install row; removed here so the record counts them.
    consents = await consents_service.delete_install_consents(
        session, install_id=app.id
    )
    # An install is what makes an app present in a guild, so removing it ends
    # what that app is sent. Switched off rather than deleted: the row records
    # what was going where, and a reinstall registers afresh.
    await webhook_subscriptions_service.deactivate_for_install(
        session, guild_id=guild_id, app_install_id=app.id
    )
    secrets = await load_secrets(session, app)
    queue_install_revocations(
        session,
        app,
        {*(app.config or {}), *secrets},
        secrets=secrets,
        reason="uninstalled",
    )
    for artifact in await app_artifacts(session, app):
        await ARTIFACT_HANDLERS[artifact["type"]].remove(
            session,
            artifact["id"],
            deleted_by_user_id=actor_user_id,
            retention_days=retention_days,
        )
    install_id, listing_uid = app.id, app.listing_uid
    await session.delete(app)
    # Staged before the commit that removes the row, and reading the counts the
    # steps above returned rather than asking again.
    await audit_service.record(
        session,
        event_type=AuditEventType.APP_UNINSTALLED,
        actor_user_id=actor_user_id,
        guild_id=guild_id,
        target_type="app",
        target_id=install_id,
        detail={
            "listing_uid": listing_uid,
            "connections": connections,
            "consents": consents,
        },
    )


async def clear_static_connection(
    session: AsyncSession, app: GuildApp, connection_id: str
) -> None:
    """Clear a guild-wide connection's stored values and its handle.

    Its grant is ended at the vendor after the caller commits. The handle goes
    with the values, so a token asked for by the old one is refused;
    connecting again mints a fresh one. The caller holds the install row.
    """
    secrets = await load_secrets(session, app)
    if (app.config or {}).get(connection_id) or secrets.get(connection_id):
        queue_install_revocations(
            session, app, [connection_id], secrets=secrets, reason="disconnected"
        )
    app.config = {
        key: value for key, value in (app.config or {}).items() if key != connection_id
    }
    await store_secrets(
        session,
        app,
        {key: value for key, value in secrets.items() if key != connection_id},
    )
    app.connection_refs = {
        key: value
        for key, value in (app.connection_refs or {}).items()
        if key != connection_id
    }
    _unverified(app)


def _config_fields(config: dict, secrets: dict) -> dict[str, Any]:
    """Every stored configuration field, keyed ``connection.field``.

    The shape a before/after comparison reads: the keys are what a record
    carries, and the values are only ever compared with one another.
    """
    fields: dict[str, Any] = {}
    for store in (config, secrets):
        for connection_id, values in (store or {}).items():
            for field, value in (values or {}).items():
                fields[f"{connection_id}.{field}"] = value
    return fields


async def apply_static_config(
    session: AsyncSession,
    app: GuildApp,
    values: Mapping[str, Mapping[str, Any]],
    *,
    actor_user_id: int,
) -> None:
    """Set the guild-wide values ``values`` names, per connection.

    Validated against the *pinned* definition, so what an install accepts is
    the form it was configured against. Only guild-scoped connections are
    settable here. Raises :class:`~app.services.tenant.app_config.AppConfigError`
    for anything refused. The caller holds the install row and commits.
    """
    config = dict(app.config or {})
    secrets = await load_secrets(session, app)
    before = _config_fields(config, secrets)

    for connection_id, submitted in values.items():
        connection = app_config_service.connection_by_id(app.definition, connection_id)
        if connection is None:
            raise app_config_service.AppConfigError(
                GuildAppMessages.CONFIG_UNKNOWN_CONNECTION
            )
        if connection.get("scope") != "static":
            raise app_config_service.AppConfigError(
                GuildAppMessages.CONNECTION_NOT_STATIC
            )
        new_config, new_secrets = app_config_service.apply_connection_values(
            connection,
            submitted,
            current=config.get(connection_id) or {},
            current_secrets=secrets.get(connection_id) or {},
        )
        if new_config:
            config[connection_id] = new_config
        else:
            config.pop(connection_id, None)
        if new_secrets:
            secrets[connection_id] = new_secrets
        else:
            secrets.pop(connection_id, None)
        if app_config_service.token_of(connection) is not None:
            # A connection the app asks a token for is addressed by a handle.
            app_config_service.guild_connection_ref(app, connection_id)

    app.config = config
    await store_secrets(session, app, secrets)
    _unverified(app)
    # Which fields hold something different now, by name. A configuration value
    # is the app's credential to the vendor, so none of it reaches the record.
    moved = audit_service.changed_fields(before, _config_fields(config, secrets))[
        "changed"
    ]
    if moved:
        await audit_service.record(
            session,
            event_type=AuditEventType.APP_UPDATED,
            actor_user_id=actor_user_id,
            guild_id=routed_guild_id(session),
            target_type="app",
            target_id=app.id,
            detail={
                "area": "config",
                "changed": moved,
                "connection_ids": sorted(values),
            },
        )


def _unverified(app: GuildApp) -> None:
    """The app has not seen the install's values as they now stand, so its
    previous verdict no longer describes them. It reports again once it has
    pulled and checked."""
    app.config_state = "unverified"
    app.config_state_detail = None
    touch(app)


def touch(app: GuildApp) -> None:
    app.updated_at = datetime.now(timezone.utc)


# --- placement --------------------------------------------------------------
#
# Where an app's initiative-scoped surfaces appear: one ``app_placements`` row
# per initiative, carrying the initiative roles allowed to open the app there.
# An initiative with no row is one the app is not placed in. Placement is the
# seat's answer to "where does this belong", so it applies to everyone
# including guild admins — unlike the roles on a row, which an admin always
# clears.


class PlacementError(ValueError):
    """A placement that names something this guild cannot place an app in."""


class PlacementRoleError(PlacementError):
    """A placement naming a role that is not one of its initiative's."""


#: The built-in initiative roles, by name. Every initiative is created with
#: each of them, so a name here resolves to one role in any initiative.
BUILTIN_ROLE_NAMES: tuple[str, ...] = tuple(spec.name for spec in BUILTIN_ROLES)


async def _builtin_role_ids(
    session: AsyncSession, initiative_ids: Iterable[int], names: Iterable[str]
) -> dict[int, list[int]]:
    """Each initiative's built-in roles of those names, keyed by initiative.

    One query for every initiative. An initiative missing one of the roles
    (renamed or deleted) is placed with the ones it has.
    """
    ids = list(initiative_ids)
    wanted = sorted(set(names))
    if not ids or not wanted:
        return {}
    rows = await session.exec(
        select(InitiativeRoleModel.initiative_id, InitiativeRoleModel.id)
        .where(
            InitiativeRoleModel.initiative_id.in_(ids),
            InitiativeRoleModel.name.in_(wanted),
            InitiativeRoleModel.is_builtin.is_(True),
        )
        .order_by(InitiativeRoleModel.id)
    )
    roles: dict[int, list[int]] = {}
    for initiative_id, role_id in rows.all():
        roles.setdefault(initiative_id, []).append(role_id)
    return roles


async def _moderator_role_ids(
    session: AsyncSession, initiative_ids: Iterable[int]
) -> dict[int, list[int]]:
    """Each initiative's built-in moderator role, keyed by initiative."""
    return await _builtin_role_ids(session, initiative_ids, ("moderator",))


def _default_role_ids(roles: dict[int, list[int]], initiative_id: int) -> list[int]:
    """The role set a new placement starts with: the initiative's moderators."""
    return sorted(roles.get(initiative_id, []))


async def placements_by_install(
    session: AsyncSession, install_ids: Iterable[int]
) -> dict[int, list[AppPlacement]]:
    """Every placement of each install, ordered by initiative, in one query."""
    ids = list(install_ids)
    if not ids:
        return {}
    rows = await session.exec(
        select(AppPlacement)
        .where(AppPlacement.install_id.in_(ids))
        .order_by(AppPlacement.install_id, AppPlacement.initiative_id)
    )
    grouped: dict[int, list[AppPlacement]] = {install_id: [] for install_id in ids}
    for row in rows.all():
        grouped.setdefault(row.install_id, []).append(row)
    return grouped


async def placed_initiative_ids(session: AsyncSession, install_id: int) -> set[int]:
    """The initiatives this install is placed in."""
    rows = await session.exec(
        select(AppPlacement.initiative_id).where(AppPlacement.install_id == install_id)
    )
    return set(rows.all())


async def is_placed(
    session: AsyncSession, install_id: int, initiative_id: Optional[int]
) -> bool:
    """Whether this install offers its initiative surfaces in that initiative.

    ``None`` is the guild-wide reading, which placement says nothing about.
    """
    if initiative_id is None:
        return True
    row = (
        await session.exec(
            select(AppPlacement.initiative_id).where(
                AppPlacement.install_id == install_id,
                AppPlacement.initiative_id == initiative_id,
            )
        )
    ).first()
    return row is not None


async def placement_role_ids(
    session: AsyncSession, install_id: int, initiative_id: int
) -> Optional[list[int]]:
    """The roles allowed to open this install's surfaces in one initiative.

    ``None`` when the install is not placed there, which is a different answer
    from a placement allowing no role: the first has no surface to open, the
    second has one that only admins open.
    """
    row = (
        await session.exec(
            select(AppPlacement.role_ids).where(
                AppPlacement.install_id == install_id,
                AppPlacement.initiative_id == initiative_id,
            )
        )
    ).first()
    return None if row is None else list(row or [])


async def set_placement_roles(
    session: AsyncSession, app: GuildApp, initiative_id: int, role_ids: Iterable[int]
) -> AppPlacement:
    """Place the install in one initiative with exactly these roles.

    Creates the placement or replaces its roles. The initiative must be one of
    this guild's, and every role one of *that* initiative's, both read on the
    same routed session; anything else raises :class:`PlacementError`.
    """
    wanted: set[int] = set()
    for entry in role_ids:
        if isinstance(entry, bool) or not isinstance(entry, int):
            raise PlacementError("roles must be a list of role ids")
        wanted.add(entry)
    initiative = (
        await session.exec(select(Initiative.id).where(Initiative.id == initiative_id))
    ).first()
    if initiative is None:
        raise PlacementError(f"initiative {initiative_id} is not one of this guild's")
    if wanted:
        known = set(
            (
                await session.exec(
                    select(InitiativeRoleModel.id).where(
                        InitiativeRoleModel.initiative_id == initiative_id,
                        InitiativeRoleModel.id.in_(sorted(wanted)),
                    )
                )
            ).all()
        )
        foreign = sorted(wanted - known)
        if foreign:
            raise PlacementRoleError(
                f"role {foreign[0]} is not a role of initiative {initiative_id}"
            )

    placement = (
        await session.exec(
            select(AppPlacement).where(
                AppPlacement.install_id == app.id,
                AppPlacement.initiative_id == initiative_id,
            )
        )
    ).first()
    if placement is None:
        placement = AppPlacement(
            install_id=app.id, initiative_id=initiative_id, role_ids=sorted(wanted)
        )
    else:
        placement.role_ids = sorted(wanted)
        placement.updated_at = datetime.now(timezone.utc)
    session.add(placement)
    await session.flush()
    return placement


async def remove_placement(
    session: AsyncSession, app: GuildApp, initiative_id: int
) -> bool:
    """Take the install out of one initiative. Answers whether it was there.

    A mandatory install may be removed from an initiative like any other; it
    stays removed, since only a new initiative is placed automatically.
    """
    result = await session.exec(
        delete(AppPlacement).where(
            AppPlacement.install_id == app.id,
            AppPlacement.initiative_id == initiative_id,
        )
    )
    await session.flush()
    return bool(result.rowcount)


async def set_placed_initiatives(
    session: AsyncSession, app: GuildApp, initiative_ids: set[int]
) -> None:
    """Place the install in exactly these initiatives.

    Every id must be one of this guild's initiatives, read on the same routed
    session. A placement that stays keeps the roles it had; one that is new
    starts with the initiative's built-in moderator role; one not listed is
    removed.
    """
    for entry in initiative_ids:
        if isinstance(entry, bool) or not isinstance(entry, int):
            raise PlacementError("placement must be a list of initiative ids")
    known = set((await session.exec(select(Initiative.id))).all())
    unknown = sorted(initiative_ids - known)
    if unknown:
        raise PlacementError(f"initiative {unknown[0]} is not one of this guild's")

    current = await placed_initiative_ids(session, app.id)
    removed = current - initiative_ids
    if removed:
        await session.exec(
            delete(AppPlacement).where(
                AppPlacement.install_id == app.id,
                AppPlacement.initiative_id.in_(sorted(removed)),
            )
        )
    added = sorted(initiative_ids - current)
    roles = await _moderator_role_ids(session, added)
    for initiative_id in added:
        session.add(
            AppPlacement(
                install_id=app.id,
                initiative_id=initiative_id,
                role_ids=_default_role_ids(roles, initiative_id),
            )
        )
    await session.flush()


async def place_in_every_initiative(session: AsyncSession, app: GuildApp) -> None:
    """Place the install in every initiative that exists now.

    What installing a mandatory app does. Initiatives created afterwards are
    placed by the ``initiative_roles`` trigger, which reads
    ``follows_new_initiatives``.
    """
    every = set((await session.exec(select(Initiative.id))).all())
    current = await placed_initiative_ids(session, app.id)
    added = sorted(every - current)
    roles = await _moderator_role_ids(session, added)
    for initiative_id in added:
        session.add(
            AppPlacement(
                install_id=app.id,
                initiative_id=initiative_id,
                role_ids=_default_role_ids(roles, initiative_id),
            )
        )
    await session.flush()


async def place_with_roles(
    session: AsyncSession,
    app: GuildApp,
    initiative_ids: Optional[Iterable[int]],
    role_names: Iterable[str],
) -> list[int]:
    """Place a new install in these initiatives, each with these built-in roles.

    What the install dialog does. ``None`` is every initiative that exists now,
    the same set "every current initiative" places from the placement panel;
    an initiative created afterwards is placed only if the seat places it.
    Each name must be a built-in role, resolved to that initiative's own role
    of the name. Anything else raises :class:`PlacementError`, before anything
    is written. Answers the initiatives placed, sorted.
    """
    names = list(role_names)
    for name in names:
        if name not in BUILTIN_ROLE_NAMES:
            raise PlacementRoleError(f"{name!r} is not a built-in role")
    known = set((await session.exec(select(Initiative.id))).all())
    if initiative_ids is None:
        chosen = known
    else:
        chosen = set()
        for entry in initiative_ids:
            if isinstance(entry, bool) or not isinstance(entry, int):
                raise PlacementError("placement must be a list of initiative ids")
            chosen.add(entry)
        unknown = sorted(chosen - known)
        if unknown:
            raise PlacementError(f"initiative {unknown[0]} is not one of this guild's")

    placed = sorted(chosen)
    roles = await _builtin_role_ids(session, placed, names)
    for initiative_id in placed:
        session.add(
            AppPlacement(
                install_id=app.id,
                initiative_id=initiative_id,
                role_ids=sorted(roles.get(initiative_id, [])),
            )
        )
    await session.flush()
    return placed


# --- opening a surface ------------------------------------------------------
#
# One decision, read by both the handoff mint and the app read that tells the
# client where each surface may be opened, so the two cannot disagree.


class SurfaceAccess(str, Enum):
    """What one viewer gets when opening one surface somewhere."""

    #: The surface may be opened here.
    open = "open"
    #: There is no such surface here: it does not render in this scope, or the
    #: install is not placed in this initiative.
    not_here = "not_here"
    #: The surface is here, and this viewer may not open it.
    refused = "refused"


def requested_scopes(definition: Any) -> list[str]:
    """The scopes a pinned definition's service asks for, in vocabulary order,
    then the ``apps:`` scopes sorted.

    Only known scopes are returned, each once.
    """
    service = definition.get("service") if isinstance(definition, dict) else None
    scopes = service.get("scopes") if isinstance(service, dict) else None
    if not isinstance(scopes, list):
        return []
    return ordered_scopes(scopes)


def grantable_scopes(definition: Any, ceiling: Iterable[str]) -> list[str]:
    """The requested scopes the deployment's ceiling allows, in the order
    :func:`requested_scopes` gives them."""
    allowed = set(ceiling)
    return [scope for scope in requested_scopes(definition) if scope in allowed]


async def app_scope_names(
    session: AsyncSession, scopes: Iterable[str]
) -> dict[str, str]:
    """For each ``apps:`` scope among ``scopes``, the name the app it names
    goes by in the catalog, keyed by its public id: its registration's
    listing's name, or the public id itself when there is none to read."""
    targets = sorted(
        {target for scope in scopes if (target := app_scope_target(scope))}
    )
    if not targets:
        return {}
    registrations = await registration_lookup.load_registrations()
    by_uid = {
        registrations[target].listing_uid: target
        for target in targets
        if target in registrations and registrations[target].listing_uid
    }
    names: dict[str, str] = {}
    if by_uid:
        rows = (
            await session.exec(
                select(MarketplaceListing.uid, MarketplaceListing.name).where(
                    col(MarketplaceListing.uid).in_(list(by_uid))
                )
            )
        ).all()
        names = {by_uid[uid]: name for uid, name in rows}
    return {target: names.get(target, target) for target in targets}


def declared_surfaces(definition: Any) -> list[dict[str, Any]]:
    """The embedded surfaces a pinned definition declares, well-formed ones only."""
    if not isinstance(definition, dict):
        return []
    embeds = definition.get("embeds")
    if not isinstance(embeds, list):
        return []
    return [
        embed
        for embed in embeds
        if isinstance(embed, dict) and isinstance(embed.get("id"), str)
    ]


def initiative_surface_ids(definition: Any) -> set[str]:
    """The ids of the surfaces a pinned definition renders inside initiatives."""
    return {
        embed["id"]
        for embed in declared_surfaces(definition)
        if surface_renders_in(embed, "initiative")
    }


def has_initiative_surfaces(definition: Any) -> bool:
    """Whether the app has anything to place in an initiative."""
    return bool(initiative_surface_ids(definition))


def surface_renders_in(embed: dict[str, Any], scope: str) -> bool:
    """Whether a surface asked to render in ``scope``.

    Definitions pinned before a surface could say where it belongs carry no
    ``scopes``, and every one of those is guild-wide.
    """
    scopes = embed.get("scopes")
    return scope in scopes if isinstance(scopes, list) else scope == "guild"


def surface_access(
    embed: dict[str, Any],
    *,
    initiative_id: Optional[int],
    placement_role_ids: Optional[Collection[int]],
    is_guild_admin: bool,
    member_role_ids: Collection[int],
) -> SurfaceAccess:
    """Whether a viewer may open ``embed`` where it is being opened.

    ``initiative_id`` is where: ``None`` is the community level. For an
    initiative, ``placement_role_ids`` is that placement's roles, or ``None``
    when the install is not placed there.

    * In an initiative, the install must be placed there, and the viewer is a
      guild admin or holds one of the placement's roles.
    * At the community level, the viewer is a guild admin.
    * A surface marked ``admin_only`` is opened by guild admins alone,
      wherever it is (read by :func:`is_admin_only`, which also honours the
      earlier contract's term on a definition pinned before it).

    ``member_role_ids`` are the viewer's initiative roles across the community.
    A role belongs to one initiative and a placement names only its own
    initiative's roles, so meeting one of them here is holding it here.
    """
    scope = "guild" if initiative_id is None else "initiative"
    if not surface_renders_in(embed, scope):
        return SurfaceAccess.not_here
    if initiative_id is not None and placement_role_ids is None:
        return SurfaceAccess.not_here
    if is_guild_admin:
        return SurfaceAccess.open
    if initiative_id is None or is_admin_only(embed):
        return SurfaceAccess.refused
    allowed = set(placement_role_ids or ())
    if allowed.intersection(member_role_ids):
        return SurfaceAccess.open
    return SurfaceAccess.refused


@dataclass(frozen=True)
class SurfaceOpenability:
    """Where one viewer may open one surface."""

    surface_id: str
    openable_guild_wide: bool
    openable_initiatives: tuple[int, ...]


def surface_openability(
    definition: Any,
    *,
    placements: Sequence[AppPlacement],
    is_guild_admin: bool,
    member_role_ids: Collection[int],
) -> list[SurfaceOpenability]:
    """Every declared surface, with where this viewer may open it.

    Measured with :func:`surface_access` against each placement the install
    has, which is the same decision the handoff makes.
    """
    ordered = sorted(placements, key=lambda row: row.initiative_id)
    answers: list[SurfaceOpenability] = []
    for embed in declared_surfaces(definition):
        guild_wide = surface_access(
            embed,
            initiative_id=None,
            placement_role_ids=None,
            is_guild_admin=is_guild_admin,
            member_role_ids=member_role_ids,
        )
        initiatives = tuple(
            row.initiative_id
            for row in ordered
            if surface_access(
                embed,
                initiative_id=row.initiative_id,
                placement_role_ids=list(row.role_ids or []),
                is_guild_admin=is_guild_admin,
                member_role_ids=member_role_ids,
            )
            is SurfaceAccess.open
        )
        answers.append(
            SurfaceOpenability(
                surface_id=embed["id"],
                openable_guild_wide=guild_wide is SurfaceAccess.open,
                openable_initiatives=initiatives,
            )
        )
    return answers
