"""The values an installed plug-in keeps in Initiative.

An install keeps values by key, on the items it can read and on itself
(``plugin_metadata``). Every function here runs on the request's session,
routed as the install by the install seam, so the table's policies decide
which rows it reaches: its own, on an item it can read, with the read scope of
the item's tool. The checks here answer the same questions first, so a refusal
names its reason instead of surfacing as a policy violation.

A value on an item is ``shown`` when the install's pinned version declares
its key as a field on the item's kind: whoever can read the item reads it
then, and it comes back with the item (:func:`annotate_plugin_values`). The
write sets it, and :func:`reconcile_shown` sets it again when the install
moves to another version.

The caps are the plug-in kit's (``metadataValueBytes`` and the rest), read
from the vendored contract.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import (
    Any,
    Awaitable,
    Callable,
    Collection,
    Iterable,
    Mapping,
    Optional,
    Sequence,
)

from sqlalchemy import Table, and_, delete, exists, false, or_, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import PluginChannelMessages, PluginMessages
from app.core.plugin_scopes import tool_resource
from app.core.tools import INSTALL_METADATA_KIND, ITEM_KINDS, KINDS
from app.db import cohorts
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.db.guild_standing import GuildContext, InstallContext
from app.db.initiative_rls import governing_path
from app.db.request_context import SystemGuild
from app.db.session import require_actor_context, set_rls_context
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.plugin_metadata import LOOKUP_LENGTH, PluginMetadata
from app.models.tenant.plugin_placement import PluginPlacement
from app.models.tenant.task import Task
from app.schemas.tenant.plugin_data import PluginValueSummary
from app.services.marketplace import contract
from app.services.marketplace.manifest_values import is_metadata_key
from app.services.tenant import guild_plugins, plugin_age
from app.services.tenant.plugin_channels import PluginChannelError

__all__ = [
    "annotate_plugin_values",
    "drop_for_items",
    "find",
    "read",
    "reconcile_shown",
    "shown_keys",
    "write",
]

#: The most one value may take, as JSON.
VALUE_BYTES = contract.cap("metadataValueBytes")
#: What one install may keep on one item.
ITEM_KEYS = contract.cap("metadataKeysPerObject")
ITEM_BYTES = contract.cap("metadataBytesPerObject")
#: What an install may keep on itself.
INSTALL_KEYS = contract.cap("installMetadataKeys")
INSTALL_BYTES = contract.cap("installMetadataBytes")
#: The most items one read may name.
READ_IDS = 500
#: The most items one look-up answers.
FIND_LIMIT = 100


def _table(kind: str) -> Table:
    return SQLModel.metadata.tables[KINDS[kind].table]


def _read_scope(kind: str) -> str:
    """The scope an install reads ``kind`` with: its tool's read scope."""
    governed = governing_path(KINDS[kind].table)
    assert governed is not None, kind
    return f"{tool_resource(governed[0]).value}:read"


def _check_key(key: str) -> None:
    if not is_metadata_key(key):
        raise PluginChannelError(PluginChannelMessages.METADATA_KEY_INVALID)


def _size(value: Any) -> int:
    """``value``'s size as compact JSON, in bytes."""
    return len(
        json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )


def _lookup(value: Any) -> Optional[str]:
    """The text a value is looked up by: a string, number or boolean of at most
    :data:`LOOKUP_LENGTH` characters, as JSON writes it (strings bare)."""
    if isinstance(value, str):
        text = value
    elif isinstance(value, (bool, int, float)):
        text = json.dumps(value)
    else:
        return None
    return text if len(text) <= LOOKUP_LENGTH else None


async def _readable(session: AsyncSession, kind: str, entity_id: int) -> bool:
    """Whether the routed install can read the item. Its table's policies
    decide, as they do for every read of it."""
    table = _table(kind)
    return bool(await session.scalar(exists().where(table.c.id == entity_id).select()))


def shown_keys(definition: Any, kind: str) -> frozenset[str]:
    """The keys a pinned definition declares as fields on ``kind``."""
    fields = definition.get("fields") if isinstance(definition, dict) else None
    return frozenset(
        field["key"]
        for field in (fields if isinstance(fields, list) else [])
        if isinstance(field, dict)
        and isinstance(field.get("key"), str)
        and kind in (field.get("on") or ())
    )


def _grouped(rows: Iterable[PluginMetadata]) -> dict[tuple[str, int], dict[str, Any]]:
    grouped: dict[tuple[str, int], dict[str, Any]] = defaultdict(dict)
    for row in rows:
        grouped[(row.entity_type, row.entity_id)][row.key] = row.value
    return grouped


async def read(
    session: AsyncSession,
    context: InstallContext,
    kind: str,
    entity_ids: Sequence[int],
) -> list[tuple[str, int, dict[str, Any]]]:
    """The install's values on each item it can read, by item. An item holding
    none, or one it cannot read, is left out. For the install's own values,
    ``entity_ids`` is not read."""
    if kind == INSTALL_METADATA_KIND:
        entity_ids = [context.install_id]
    elif len(entity_ids) > READ_IDS:
        raise PluginChannelError(PluginChannelMessages.INVALID_PAYLOAD)
    if not entity_ids:
        return []
    rows = await session.exec(
        select(PluginMetadata).where(
            PluginMetadata.install_id == context.install_id,
            PluginMetadata.entity_type == kind,
            PluginMetadata.entity_id.in_(set(entity_ids)),
        )
    )
    grouped = _grouped(rows)
    return [
        (entity_type, entity_id, values)
        for (entity_type, entity_id), values in sorted(grouped.items())
    ]


async def write(
    session: AsyncSession,
    context: InstallContext,
    kind: str,
    entity_id: Optional[int],
    values: Mapping[str, Any],
    pinned: Callable[[], Awaitable[Any]],
) -> dict[str, Any]:
    """Write some of the install's values on one item, or on itself; a
    ``None`` removes its key. Answers every value it keeps there now.

    ``pinned`` reads the install's pinned definition, whose fields on the
    item's kind say which values are shown; a value on the install itself is
    never shown, and its definition is not read.

    On an item, the install needs its tool's read scope and to be able to read
    it: the values are the install's own, and writing them changes nothing on
    the item. Nothing is written while the community's content is on hold.
    """
    if context.content_hold:
        raise PluginChannelError(PluginChannelMessages.GUILD_READ_ONLY, status_code=409)
    if kind == INSTALL_METADATA_KIND:
        entity_id = context.install_id
        max_keys, max_bytes = INSTALL_KEYS, INSTALL_BYTES
    else:
        if entity_id is None:
            raise PluginChannelError(PluginChannelMessages.INVALID_PAYLOAD)
        if not context.holds(_read_scope(kind)):
            raise PluginChannelError(PluginMessages.SCOPE_REQUIRED, status_code=403)
        if not await _readable(session, kind, entity_id):
            raise PluginChannelError(
                PluginChannelMessages.METADATA_ITEM_NOT_FOUND, status_code=404
            )
        max_keys, max_bytes = ITEM_KEYS, ITEM_BYTES

    # The keys an item ends up with are counted below; a write may remove every
    # key it holds and set as many again, and no more.
    if len(values) > 2 * max_keys:
        raise PluginChannelError(
            PluginChannelMessages.METADATA_LIMIT_REACHED, status_code=409
        )
    sizes: dict[str, int] = {}
    for key, value in values.items():
        _check_key(key)
        if value is not None:
            sizes[key] = _size(value)
            if sizes[key] > VALUE_BYTES:
                raise PluginChannelError(
                    PluginChannelMessages.METADATA_VALUE_TOO_LARGE, status_code=413
                )

    shown: Collection[str] = frozenset()
    if kind != INSTALL_METADATA_KIND:
        # Lock order: the install's fields lock (shared here), then the item's
        # lock. Holding the first while the definition is read, to the commit,
        # means a reconcile to a new definition (which takes it exclusively)
        # runs either before this read, which then sees the new definition,
        # or after this commit, and corrects what it wrote.
        await _lock_fields(session, context.guild_id, context.install_id, shared=True)
        shown = shown_keys(await pinned(), kind)

    # Writes to one item take turns, so the caps hold across them.
    await advisory_lock(
        session,
        LockNamespace.PLUGIN_METADATA,
        f"{context.guild_id}:{context.install_id}:{kind}:{entity_id}",
    )
    where = (
        PluginMetadata.install_id == context.install_id,
        PluginMetadata.entity_type == kind,
        PluginMetadata.entity_id == entity_id,
    )
    kept = {
        row.key: row.value
        for row in await session.exec(select(PluginMetadata).where(*where))
    }
    after = {key: value for key, value in kept.items() if key not in values}
    after.update({key: value for key, value in values.items() if value is not None})
    total = sum(
        sizes[key] if key in sizes else _size(value) for key, value in after.items()
    )
    if len(after) > max_keys or total > max_bytes:
        raise PluginChannelError(
            PluginChannelMessages.METADATA_LIMIT_REACHED, status_code=409
        )

    removed = [key for key, value in values.items() if value is None and key in kept]
    if removed:
        await session.exec(
            delete(PluginMetadata).where(
                *where,
                PluginMetadata.key.in_(removed),
            )
        )
    now = datetime.now(timezone.utc)
    written = [
        {
            "install_id": context.install_id,
            "entity_type": kind,
            "entity_id": entity_id,
            "key": key,
            "value": value,
            "lookup": _lookup(value),
            "shown": key in shown,
            "updated_at": now,
        }
        for key, value in values.items()
        if value is not None
    ]
    if written:
        statement = insert(PluginMetadata).values(written)
        await session.exec(
            statement.on_conflict_do_update(
                index_elements=["install_id", "entity_type", "entity_id", "key"],
                set_={
                    "value": statement.excluded.value,
                    "lookup": statement.excluded.lookup,
                    "shown": statement.excluded.shown,
                    "updated_at": statement.excluded.updated_at,
                },
            )
        )
    await session.commit()
    return after


async def find(
    session: AsyncSession, context: InstallContext, key: str, value: str
) -> list[tuple[str, int, dict[str, Any]]]:
    """The items the install can read holding ``value`` under ``key``, with
    the values it keeps on each: at most :data:`FIND_LIMIT`, in kind and id
    order. The install's own values are not an item."""
    _check_key(key)
    if len(value) > LOOKUP_LENGTH:
        return []
    matches = (
        await session.exec(
            select(PluginMetadata.entity_type, PluginMetadata.entity_id)
            .where(
                PluginMetadata.install_id == context.install_id,
                PluginMetadata.key == key,
                PluginMetadata.lookup == value,
                PluginMetadata.entity_type != INSTALL_METADATA_KIND,
            )
            .order_by(PluginMetadata.entity_type, PluginMetadata.entity_id)
            .limit(FIND_LIMIT)
        )
    ).all()
    if not matches:
        return []
    by_kind: dict[str, list[int]] = defaultdict(list)
    for entity_type, entity_id in matches:
        by_kind[entity_type].append(entity_id)
    rows = await session.exec(
        select(PluginMetadata).where(
            PluginMetadata.install_id == context.install_id,
            or_(
                *(
                    and_(
                        PluginMetadata.entity_type == entity_type,
                        PluginMetadata.entity_id.in_(ids),
                    )
                    for entity_type, ids in by_kind.items()
                )
            ),
        )
    )
    grouped = _grouped(rows)
    return [
        (entity_type, entity_id, grouped.get((entity_type, entity_id), {}))
        for entity_type, entity_id in matches
    ]


async def drop_for_items(
    session: AsyncSession, kind: str, entity_ids: Iterable[int]
) -> None:
    """Remove every install's values on these items, as they are purged."""
    ids = list(entity_ids)
    if ids:
        await session.exec(
            delete(PluginMetadata).where(
                PluginMetadata.entity_type == kind,
                PluginMetadata.entity_id.in_(ids),
            )
        )


async def _lock_fields(
    session: AsyncSession, guild_id: int, install_id: int, *, shared: bool
) -> None:
    """The lock that orders reading an install's pinned definition for a write
    against reconciling its values to a new one."""
    await advisory_lock(
        session, LockNamespace.PLUGIN_FIELDS, f"{guild_id}:{install_id}", shared=shared
    )


async def reconcile_shown(
    guild_id: int, install_id: int, *, session: Optional[AsyncSession] = None
) -> None:
    """Show the install's values on items exactly where its pinned definition
    declares their keys as fields, after it moves to another version. Only the
    rows whose answer changes are written.

    The definition is read once no write is between reading it and committing
    (:func:`write`), so what a write read before the move is corrected here.

    ``session`` is the community's system session, routed, whose caller
    commits; without one the rows are written and committed on a system
    session of their own."""
    if session is None:
        async with cohorts.system_session(guild_id) as own:
            await set_rls_context(own, SystemGuild(guild_id))
            await reconcile_shown(guild_id, install_id, session=own)
            await own.commit()
        return
    await _lock_fields(session, guild_id, install_id, shared=False)
    definition = await session.scalar(
        select(GuildPlugin.definition).where(GuildPlugin.id == install_id)
    )
    declared = {kind: shown_keys(definition, kind) for kind in ITEM_KINDS}
    shown = or_(
        false(),
        *(
            and_(PluginMetadata.entity_type == kind, PluginMetadata.key.in_(keys))
            for kind, keys in declared.items()
            if keys
        ),
    )
    await session.exec(
        update(PluginMetadata)
        .where(
            PluginMetadata.install_id == install_id,
            PluginMetadata.entity_type != INSTALL_METADATA_KIND,
            PluginMetadata.shown.is_distinct_from(shown),
        )
        .values(shown=shown)
    )


async def annotate_plugin_values(session: AsyncSession, tasks: Sequence[Task]) -> None:
    """Set ``.plugin_values`` on every task: the shown values of the installs
    whose actions the reader could run there — on, placed in the task's
    initiative with a role the reader holds (or the reader its admin), and
    the reader old enough for the plug-in (``guild_plugins.surface_access``).
    One query for the page.

    ``session`` is the reader's, so which values it reads is the table's
    policies' answer; which installs' values are drawn is decided here. Each
    task's project is loaded. An installed plug-in reading tasks is drawn
    none: it reads its own values through its metadata routes. Nor is a
    guest, who runs no plug-in."""
    context = require_actor_context(session)
    initiatives = {
        task.id: task.project.initiative_id
        for task in tasks
        if task.id is not None and task.project is not None
    }
    found: dict[int, list[PluginValueSummary]] = defaultdict(list)
    if initiatives and isinstance(context, GuildContext) and not context.guest:
        rows = await session.exec(
            select(
                PluginMetadata.entity_id,
                PluginMetadata.install_id,
                PluginMetadata.key,
                PluginMetadata.value,
                PluginPlacement.initiative_id,
                PluginPlacement.role_ids,
                GuildPlugin.definition["minimum_age"],
            )
            .join(GuildPlugin, GuildPlugin.id == PluginMetadata.install_id)
            .join(
                PluginPlacement,
                PluginPlacement.install_id == PluginMetadata.install_id,
            )
            .where(
                PluginMetadata.entity_type == "task",
                PluginMetadata.shown.is_(True),
                GuildPlugin.enabled.is_(True),
                tuple_(PluginMetadata.entity_id, PluginPlacement.initiative_id).in_(
                    list(initiatives.items())
                ),
            )
            .order_by(PluginMetadata.install_id, PluginMetadata.key)
        )
        viewer: Optional[plugin_age.AgeViewer] = None
        offered: dict[tuple[int, int], bool] = {}
        for task_id, install_id, key, value, initiative_id, roles, minimum in rows:
            if (install_id, initiative_id) not in offered:
                old_enough = True
                if minimum is not None:
                    # Read only when a plug-in here asks for an age.
                    viewer = viewer or await plugin_age.current_viewer(context.user_id)
                    old_enough = plugin_age.age_allows({"minimum_age": minimum}, viewer)
                offered[(install_id, initiative_id)] = (
                    guild_plugins.surface_access(
                        guild_plugins.ITEM_SURFACE,
                        initiative_id=initiative_id,
                        placement_role_ids=list(roles or ()),
                        is_guild_admin=context.is_admin,
                        member_role_ids=context.member_role_ids,
                        age_allows=old_enough,
                    )
                    is guild_plugins.SurfaceAccess.open
                )
            if offered[(install_id, initiative_id)]:
                found[task_id].append(
                    PluginValueSummary(plugin_id=install_id, key=key, value=value)
                )
    for task in tasks:
        object.__setattr__(task, "plugin_values", found.get(task.id or 0, []))
