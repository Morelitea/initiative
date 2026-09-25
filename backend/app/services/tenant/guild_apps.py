"""Installing and removing guild apps.

Three shapes, and the difference is what the app brings with it.

A **tool instance** mounts one of this build's own tools at guild scope.
Installing creates an ordinary row in that tool's ordinary table with no
initiative — a guild-level calendar is a `calendars` row with `initiative_id`
NULL — and records it in the app's `artifacts`, so the sidebar can link straight
to it. Nothing about the tool changes: same table, same UI, same sharing, same
trash. The content is seeded shared with everyone in the guild, which is what
makes an app useful the moment it lands. From there its grants behave like any
other instance's: remove the everyone grant to make it private, add write grants
to let particular members or roles post. Guild admins keep full authority
through the existing admin override.

An install is not limited to what it created on the way in. A member adding a
guild calendar records it here too (`record_artifact`), because the app is the
container: it is the entry that reaches the content, so removing it takes the
content with it rather than stranding rows nothing links to.

An **embed** brings none. It opens a surface the operator configured, so there
is no row to create, nothing to share, and nothing to trash on the way out —
installing it adds an entry, and removing it takes the entry away. Who may open
it is settled by the endpoint that mints its handoff rather than by grants,
which is why such an app reports itself as admin-only.

A **service** app brings connections rather than content: what it needs is
configuration, which lives on the install row and in each member's own
connection. It creates no artifacts here.

**Artifacts are a list, not a field.** An install may produce more than one
thing, so what it produced is recorded as `[{"type": …, "id": …}]` and removal
walks the list through :data:`ARTIFACT_HANDLERS`. Every tool an app may mount
has a handler — asserted by a test rather than left to be noticed the day an
uninstall quietly leaves a row behind.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Iterable, Optional

from sqlalchemy import cast, delete, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.app_scopes import app_scope_target, ordered_scopes
from app.core.audit_events import AuditEventType
from app.models.platform.marketplace import MarketplaceListing
from app.models.tenant.app_placement import AppPlacement
from app.models.tenant.calendar import Calendar
from app.models.tenant.guild_app import GuildApp
from app.models.tenant.initiative import (
    BUILTIN_ROLES,
    Initiative,
    InitiativeRoleModel,
)
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.services import audit as audit_service
from app.services.marketplace import registration_lookup
from app.services.marketplace.service_apps import is_admin_only
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
    "declared_surfaces",
    "create_app_artifacts",
    "find_mounting_app",
    "has_initiative_surfaces",
    "initiative_surface_ids",
    "install_app",
    "is_placed",
    "legacy_artifacts",
    "lock_install",
    "place_in_every_initiative",
    "place_with_roles",
    "placed_initiative_ids",
    "placement_role_ids",
    "placements_by_install",
    "record_artifact",
    "remove_app_artifacts",
    "remove_placement",
    "set_placed_initiatives",
    "set_placement_roles",
    "surface_access",
    "surface_openability",
    "surface_renders_in",
    "touch",
]

# --- artifacts --------------------------------------------------------------


@dataclass(frozen=True)
class ArtifactHandler:
    """How one kind of artifact is made and unmade.

    ``create`` returns the id of the row it produced; ``remove`` disposes of it.
    Removal is soft wherever the tool has a trash, because what an app created
    is guild content — the events someone put in a guild calendar should survive
    an admin removing the app.
    """

    create: Callable[..., Awaitable[int]]
    remove: Callable[..., Awaitable[None]]


async def _create_calendar(
    session: AsyncSession, *, guild_id: int, created_by: int, name: str
) -> int:
    calendar = Calendar(
        # No initiative: this belongs to the guild. Its grants decide who reads
        # and writes it, exactly as for an initiative calendar.
        initiative_id=None,
        created_by=created_by,
        name=name,
    )
    session.add(calendar)
    await session.flush()

    session.add(
        ResourceGrant(
            resource_type="calendar",
            resource_id=calendar.id,
            user_id=created_by,
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
    return calendar.id  # ty: ignore[invalid-return-type] — flushed row, id is set


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


def legacy_artifacts(definition: dict, config: dict) -> list[dict[str, Any]]:
    """The artifacts an install recorded before ``artifacts`` existed.

    Tool-instance installs used to keep the id of the row they created under a
    per-tool key on ``config``. Migration 20260812_0171 rewrites those rows, and
    this is the same reading in Python: shared so the migration's behaviour is
    testable without a database, and so a row that somehow escaped it still
    resolves rather than reading as an install that created nothing.
    """
    tool = (definition or {}).get("tool")
    if tool not in ARTIFACT_HANDLERS:
        return []
    value = (config or {}).get(f"{tool}_id")
    if not isinstance(value, int) or isinstance(value, bool):
        return []
    return [{"type": tool, "id": value}]


def app_artifacts(app: GuildApp) -> list[dict[str, Any]]:
    """What this install produced, as ``[{"type": …, "id": …}]``.

    Entries naming a type this build has no handler for are dropped: they cannot
    be linked to or removed, so reporting them would only promise something no
    code can keep.
    """
    stored = app.artifacts or []
    if not isinstance(stored, list):
        stored = []
    artifacts: list[dict[str, Any]] = []
    for entry in stored:
        if not isinstance(entry, dict):
            continue
        artifact_type = entry.get("type")
        artifact_id = entry.get("id")
        if artifact_type not in ARTIFACT_HANDLERS:
            continue
        if not isinstance(artifact_id, int) or isinstance(artifact_id, bool):
            continue
        artifacts.append({"type": artifact_type, "id": artifact_id})
    if artifacts:
        return artifacts
    return legacy_artifacts(app.definition or {}, app.config or {})


async def lock_install(session: AsyncSession, app_id: int) -> Optional[GuildApp]:
    """Hold one install's row for the rest of this transaction.

    Several things on this row are values rewritten whole rather than appended
    to — the configuration maps, the connection handles — so writing one means
    reading it, changing it, and putting the result back. Two of those
    overlapping would have the second write carry a value read before the first
    landed, and the first change would be gone with no sign that it had been
    made. Taking the row first puts them in an order instead.

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


async def find_mounting_app(
    session: AsyncSession, *, guild_id: int, tool: str, for_update: bool = False
) -> Optional[GuildApp]:
    """The install that mounts ``tool`` at guild scope, if this guild has one.

    A tool-instance install is the container for what it mounts, so this is the
    question "does this guild have somewhere to put a guild-level calendar" —
    asked before creating one, and answered from the install rows rather than
    from the content, since an install with everything trashed is still the
    container.

    ``for_update`` holds the row for the rest of the transaction, and is how
    putting something *into* an app orders itself against removing the app.
    Removal takes the same lock before it reads what to trash, so the two happen
    in an order rather than at once: whichever is second either trashes the new
    content along with the rest, or finds no install and refuses. Without the
    lock a calendar could be committed just as its app went away, and would then
    be live with nothing that reaches it and no removal that knows about it.
    """
    apps = (await session.exec(select(GuildApp))).all()
    for app in apps:
        if (app.definition or {}).get("app_kind") != "tool_instance":
            continue
        if (app.definition or {}).get("tool") == tool:
            return app if not for_update else await lock_install(session, app.id)
    return None


async def record_artifact(
    session: AsyncSession, app: GuildApp, *, artifact_type: str, artifact_id: int
) -> None:
    """Add something to what this install is answerable for.

    Everything made inside an app is made *by* the app as far as removal is
    concerned: uninstalling walks ``artifacts`` and trashes every entry, so a
    calendar someone added to the guild calendar leaves with it rather than
    outliving the only entry that reached it.

    The append is done by the database, not in Python. Any member may add a
    calendar, so two of them can be adding one at the same moment — and reading
    the list, appending, and writing the whole value back would have the second
    write carry a list taken before the first landed. ``||`` appends to whatever
    the stored value is when the statement runs, so both entries survive
    whichever order they arrive in.
    """
    entry = [{"type": artifact_type, "id": artifact_id}]
    await session.exec(
        update(GuildApp)
        .where(GuildApp.id == app.id)
        .values(
            artifacts=GuildApp.artifacts.op("||")(cast(entry, JSONB)),
            updated_at=datetime.now(timezone.utc),
        )
        .execution_options(synchronize_session=False)
    )
    # The row has moved on without this copy of it, so send the next read of
    # those two back to the database rather than to a value we know is behind.
    session.expire(app, ["artifacts", "updated_at"])


async def create_app_artifacts(
    session: AsyncSession,
    *,
    definition: dict,
    guild_id: int,
    created_by: int,
    name: str,
) -> list[dict[str, Any]]:
    """Create what the app mounts, and return what it produced.

    Only a tool instance produces anything. An embed opens a surface that
    already exists, and a **service** app brings connections rather than
    content — its install is the row plus the definition it pinned, and what it
    offers is served from the container the operator registered. Both answer
    with an empty list rather than being a case the installer has to know
    about.
    """
    if definition.get("app_kind") != "tool_instance":
        return []

    tool = definition.get("tool")
    handler = ARTIFACT_HANDLERS.get(tool or "")
    if handler is None:
        # Unreachable through the endpoints — the definition validator admits
        # only tools listed there — but this is the place that would need
        # teaching about a new one.
        raise ValueError(f"cannot mount {tool!r} at guild scope")

    artifact_id = await handler.create(
        session, guild_id=guild_id, created_by=created_by, name=name
    )
    return [{"type": tool, "id": artifact_id}]


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
    artifacts = await create_app_artifacts(
        session,
        definition=definition,
        guild_id=guild_id,
        created_by=created_by,
        name=name,
    )
    app = GuildApp(
        listing_uid=listing_uid,
        listing_version=listing_version,
        app_kind=definition["app_kind"],
        name=name,
        definition=definition,
        config={},
        config_secrets={},
        artifacts=artifacts,
        granted_scopes=sorted(set(granted_scopes)),
        created_by=created_by,
    )
    session.add(app)
    await session.flush()
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


async def remove_app_artifacts(
    session: AsyncSession,
    app: GuildApp,
    *,
    deleted_by_user_id: Optional[int],
    retention_days: Optional[int],
) -> None:
    """Trash everything the app created.

    Through the ordinary soft-delete path, so removing an app is recoverable for
    as long as the guild's retention window allows — the events someone put in a
    guild calendar should not evaporate because an admin removed the app.
    """
    for artifact in app_artifacts(app):
        handler = ARTIFACT_HANDLERS[artifact["type"]]
        await handler.remove(
            session,
            artifact["id"],
            deleted_by_user_id=deleted_by_user_id,
            retention_days=retention_days,
        )


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
