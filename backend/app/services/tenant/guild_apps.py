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

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tenant.calendar import Calendar
from app.models.tenant.guild_app import GuildApp
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.services.tenant.soft_delete import soft_delete_entity

__all__ = [
    "ARTIFACT_HANDLERS",
    "ArtifactHandler",
    "app_artifacts",
    "create_app_artifacts",
    "get_app_content_id",
    "legacy_artifacts",
    "remove_app_artifacts",
    "requires_guild_admin",
    "touch",
]

#: Embed targets only a guild admin may open.
#:
#: The deployment's advanced-tool surface is one: the endpoint that mints its
#: handoff has always been admin-only, and an app entry that refuses everyone who
#: clicks it is worse than no entry. Anything with content of its own is absent
#: from here — a tool instance is governed by its grants, which can say things a
#: single flag cannot.
_ADMIN_ONLY_EMBED_TARGETS = frozenset({"advanced_tool"})


def requires_guild_admin(definition: dict) -> bool:
    """Whether only a guild admin can open what this app installed."""
    if definition.get("app_kind") != "embed":
        return False
    return definition.get("embed_target") in _ADMIN_ONLY_EMBED_TARGETS


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
    session: AsyncSession, *, guild_id: int, created_by_id: int, name: str
) -> int:
    calendar = Calendar(
        guild_id=guild_id,
        # No initiative: this belongs to the guild. Its grants decide who reads
        # and writes it, exactly as for an initiative calendar.
        initiative_id=None,
        created_by_id=created_by_id,
        name=name,
    )
    session.add(calendar)
    await session.flush()

    session.add(
        ResourceGrant(
            resource_type="calendar",
            resource_id=calendar.id,
            user_id=created_by_id,
            level=ResourceAccessLevel.owner,
            guild_id=guild_id,
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
            guild_id=guild_id,
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


def get_app_content_id(app: GuildApp) -> Optional[int]:
    """The id of the first row this app created, if it created one.

    A convenience for the single-artifact case the UI still links at; anything
    walking everything an install produced wants :func:`app_artifacts`.
    """
    artifacts = app_artifacts(app)
    return artifacts[0]["id"] if artifacts else None


async def create_app_artifacts(
    session: AsyncSession,
    *,
    definition: dict,
    guild_id: int,
    created_by_id: int,
    name: str,
) -> list[dict[str, Any]]:
    """Create what the app mounts, and return what it produced."""
    if definition.get("app_kind") != "tool_instance":
        # An embed opens a surface that already exists; a service app brings
        # configuration rather than content. Neither has anything to create.
        return []

    tool = definition.get("tool")
    handler = ARTIFACT_HANDLERS.get(tool or "")
    if handler is None:
        # Unreachable through the endpoints — the definition validator admits
        # only tools listed there — but this is the place that would need
        # teaching about a new one.
        raise ValueError(f"cannot mount {tool!r} at guild scope")

    artifact_id = await handler.create(
        session, guild_id=guild_id, created_by_id=created_by_id, name=name
    )
    return [{"type": tool, "id": artifact_id}]


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
