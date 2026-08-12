"""Installing and removing guild apps.

Two shapes, and the difference is whether the app brings content with it.

A **tool instance** mounts one of this build's own tools at guild scope.
Installing creates an ordinary row in that tool's ordinary table with no
initiative — a guild-level calendar is a `calendars` row with `initiative_id`
NULL — and records its id on the app so the sidebar can link straight to it.
Nothing about the tool changes: same table, same UI, same sharing, same trash.
The content is seeded shared with everyone in the guild, which is what makes an
app useful the moment it lands. From there its grants behave like any other
instance's: remove the everyone grant to make it private, add write grants to
let particular members or roles post. Guild admins keep full authority through
the existing admin override.

An **embed** brings none. It opens a surface the operator configured, so there
is no row to create, nothing to share, and nothing to trash on the way out —
installing it adds an entry, and removing it takes the entry away. Who may open
it is settled by the endpoint that mints its handoff rather than by grants,
which is why such an app reports itself as admin-only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tenant.calendar import Calendar
from app.models.tenant.guild_app import GuildApp
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.services.tenant.soft_delete import soft_delete_entity

__all__ = [
    "create_app_content",
    "remove_app_content",
    "get_app_content_id",
    "requires_guild_admin",
]

#: Where each mountable tool records the id of what the install created.
_CONTENT_KEY: dict[str, str] = {"calendar": "calendar_id"}

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


def get_app_content_id(app: GuildApp) -> Optional[int]:
    """The id of the row this app created, if it created one."""
    tool = (app.definition or {}).get("tool")
    key = _CONTENT_KEY.get(tool or "")
    if key is None:
        return None
    value = (app.config or {}).get(key)
    return value if isinstance(value, int) else None


async def create_app_content(
    session: AsyncSession,
    *,
    definition: dict,
    guild_id: int,
    created_by_id: int,
    name: str,
) -> dict:
    """Create what the app mounts, and return the config that points at it."""
    if definition.get("app_kind") == "embed":
        # Nothing to create: the surface already exists, wherever the operator
        # pointed it. The app row alone is the install.
        return {}

    tool = definition.get("tool")
    if tool != "calendar":
        # Unreachable through the endpoints — the definition validator admits
        # only the tools listed there — but this is the place that would need
        # teaching about a new one.
        raise ValueError(f"cannot mount {tool!r} at guild scope")

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
    return {"calendar_id": calendar.id}


async def remove_app_content(
    session: AsyncSession,
    app: GuildApp,
    *,
    deleted_by_user_id: Optional[int],
    retention_days: Optional[int],
) -> None:
    """Trash what the app created.

    Through the ordinary soft-delete path, so removing an app is recoverable for
    as long as the guild's retention window allows — the events someone put in a
    guild calendar should not evaporate because an admin removed the app.
    """
    content_id = get_app_content_id(app)
    if content_id is None:
        return
    calendar = (
        await session.exec(select(Calendar).where(Calendar.id == content_id))
    ).first()
    if calendar is None:
        return
    await soft_delete_entity(
        session,
        calendar,
        deleted_by_user_id=deleted_by_user_id,
        retention_days=retention_days,
    )


def touch(app: GuildApp) -> None:
    app.updated_at = datetime.now(timezone.utc)
