"""Plug-in blocks on tasks: which tasks a block is drawn for, its reads, its
actions, and the signal that its rows changed.

A block names its tasks to the plug-in by id. Every id sent is one both sides
may read:

1. the viewer, through the ordinary resource path (a task they cannot see is
   dropped);
2. the block is offered there: the task's project was installed from the
   block's ``project_listing``, when it names one, and the install is placed
   in the task's initiative with the viewer's role allowed
   (:func:`~app.services.tenant.guild_plugins.block_initiatives`);
3. the install itself, routed as the install, so the database answers which
   of those it can read.

A read is one call for every task left, through the widget path
(:func:`~app.services.marketplace.plugin_data.fetch_plugin_source`). An action
is one call for one task to a write the block declares, made as the
installation and naming the viewer: what it changes, and whether this viewer
may, is the plug-in's to decide. Initiative writes nothing for it.

``block.stale`` is the plug-in saying a block's rows changed. It stores
nothing: the ids the install can read are turned into their initiatives, and
the rooms of those initiatives are told, across workers, to read the block
again.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence

import httpx
from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import resource_access
from app.api.deps import InstallAccessError, VerifiedInstall, establish_install_access
from app.core.messages import PluginDataMessages
from app.core.tools import Tool
from app.db import cohorts
from app.db.guild_standing import GuildContext
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.project import Project
from app.models.tenant.task import Task
from app.services.content_sockets import initiative_room, sockets
from app.services.marketplace import plugin_data
from app.services.marketplace.plugin_data import PluginDataError
from app.services.marketplace.plugin_refs import ensure_plugin_ref
from app.services.marketplace.registration_lookup import RegistrationSnapshot
from app.services.marketplace.service_plugins import (
    BLOCK_SUBJECT_RETURN,
    ENDPOINT_ID_PREFIX,
    is_admin_only,
)
from app.services.permissions import with_tool
from app.services.tenant import guild_plugins

logger = logging.getLogger(__name__)

__all__ = [
    "CHANNEL",
    "BlockRows",
    "block_rows",
    "deliver_stale",
    "find_block",
    "mark_stale",
    "run_block_action",
]

#: The cross-worker channel a stale block is relayed on.
CHANNEL = "plugin_block"

#: How a stale block reads in a room's frame.
_RESOURCE_TYPE = "plugin_block"
_STALE = "stale"


@dataclass(frozen=True)
class BlockRows:
    """A block's read: each task's row by its id, and when it was obtained."""

    rows: dict[str, dict[str, Any]]
    fetched_at: datetime
    cached: bool = False


def find_block(plugin: GuildPlugin, block_id: str) -> Optional[dict[str, Any]]:
    """One block the install's pinned definition declares, or None."""
    return next(
        (
            block
            for block in guild_plugins.declared_blocks(plugin.definition)
            if block["id"] == block_id
        ),
        None,
    )


def _not_found() -> PluginDataError:
    return PluginDataError(PluginDataMessages.BLOCK_NOT_FOUND, 404)


def _subject_key(value: Any) -> Optional[int]:
    """The task id a row names, written as a number or as its digits."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _install_scopes(
    plugin: GuildPlugin, registration: RegistrationSnapshot
) -> frozenset[str]:
    """The scopes the install's tokens carry now: granted, still requested by
    the pinned version, and within the registration's ceiling."""
    requested = set(guild_plugins.requested_scopes(plugin.definition))
    ceiling = set(registration.scope_ceiling)
    return frozenset(
        scope
        for scope in plugin.granted_scopes or ()
        if scope in requested and scope in ceiling
    )


async def install_readable(
    plugin: GuildPlugin,
    registration: RegistrationSnapshot,
    *,
    guild_id: int,
    task_ids: Iterable[int],
    initiative_id: Optional[int] = None,
) -> dict[int, int]:
    """Which of ``task_ids`` the install can read, each with its initiative.

    Asked of the database on a session of its own, routed as the install with
    the scopes its tokens carry (and narrowed to ``initiative_id`` when the
    token asking is): the same answer the install's own reads get.
    """
    ids = sorted(set(task_ids))
    if not ids:
        return {}
    async with cohorts.request_sessionmaker(guild_id)() as session:
        try:
            await establish_install_access(
                session,
                VerifiedInstall(
                    guild_id=guild_id,
                    install_id=int(plugin.id or 0),
                    client_id=registration.public_id,
                    scopes=_install_scopes(plugin, registration),
                    initiative_id=initiative_id,
                ),
            )
        except InstallAccessError:
            return {}
        rows = await session.exec(
            select(Task.id, Project.initiative_id)
            .join(Project, Project.id == Task.project_id)  # type: ignore[arg-type]
            .where(Task.id.in_(ids))  # type: ignore[union-attr]
        )
        return {int(task_id): int(initiative) for task_id, initiative in rows.all()}


async def _shown_initiatives(
    session: AsyncSession, plugin: GuildPlugin, context: GuildContext
) -> set[int]:
    """The initiatives whose tasks show this install's blocks to the viewer."""
    install_id = int(plugin.id or 0)
    placements = await guild_plugins.placements_by_install(session, [install_id])
    return set(
        guild_plugins.block_initiatives(
            placements.get(install_id, []),
            is_guild_admin=context.is_admin,
            member_role_ids=context.member_role_ids,
        )
    )


def _offered_on(block: Mapping[str, Any], task: Task, shown: set[int]) -> bool:
    """Whether ``block`` is drawn on ``task`` for the viewer ``shown`` is of."""
    project = task.project
    if project is None or project.initiative_id not in shown:
        return False
    listing = block.get("project_listing")
    return listing is None or project.listing_uid == listing


async def _live(plugin: GuildPlugin) -> RegistrationSnapshot:
    """The install's registration, while the install is on and it is live."""
    if not plugin.enabled:
        raise PluginDataError(PluginDataMessages.PLUGIN_DISABLED, 409)
    return await plugin_data._load_registration(None, plugin=plugin)


async def block_rows(
    session: AsyncSession,
    *,
    plugin: GuildPlugin,
    block_id: str,
    task_ids: Sequence[int],
    context: GuildContext,
    user_id: int,
    transport: httpx.AsyncBaseTransport | None = None,
) -> BlockRows:
    """One block's read for the tasks a view holds that it is drawn on.

    ``session`` is the viewer's, routed into the community. Tasks the viewer
    cannot see, that the block is not offered on, or that the install cannot
    read are left out silently; with none left, the plug-in is not called.
    """
    block = find_block(plugin, block_id)
    endpoint_id = (block or {}).get("endpoint")
    if block is None or not isinstance(endpoint_id, str):
        raise _not_found()
    registration = await _live(plugin)

    asked = list(dict.fromkeys(task_ids))
    tasks = (
        (
            await session.exec(
                select(Task)
                .where(Task.id.in_(asked))  # type: ignore[union-attr]
                .options(with_tool(Task.project))
            )
        ).all()
        if asked
        else []
    )
    shown = await _shown_initiatives(session, plugin, context)
    visible = [
        int(task.id or 0)
        for task in tasks
        if _offered_on(block, task, shown) and _readable_by_viewer(task, context)
    ]
    readable = await install_readable(
        plugin, registration, guild_id=context.guild_id, task_ids=visible
    )
    ids = sorted(readable)
    if not ids:
        return BlockRows(rows={}, fetched_at=datetime.now(timezone.utc))

    result = await plugin_data.fetch_plugin_source(
        session,
        plugin=plugin,
        endpoint_id=endpoint_id,
        raw_params=None,
        user_id=user_id,
        is_guild_admin=context.is_admin,
        transport=transport,
        task_ids=ids,
    )
    return BlockRows(
        rows=_rows_by_task(result.rows, set(ids)),
        fetched_at=result.fetched_at,
        cached=result.cached,
    )


def _readable_by_viewer(task: Task, context: GuildContext) -> bool:
    """Whether the viewer reads ``task``, as its project's resource path
    decides: the tool switched on in its initiative, and the row reached."""
    try:
        resource_access.authorize(Tool.project, task.project, context=context)
    except HTTPException:
        return False
    return True


def _rows_by_task(
    rows: Iterable[Mapping[str, Any]], asked: set[int]
) -> dict[str, dict[str, Any]]:
    """An answer's rows keyed by the task each names, for the tasks asked
    about only. A task named twice keeps its first row."""
    keyed: dict[str, dict[str, Any]] = {}
    for row in rows:
        task_id = _subject_key(row.get(BLOCK_SUBJECT_RETURN))
        if task_id in asked and str(task_id) not in keyed:
            keyed[str(task_id)] = dict(row)
    return keyed


async def run_block_action(
    session: AsyncSession,
    *,
    plugin: GuildPlugin,
    block_id: str,
    action_key: str,
    task_id: int,
    context: GuildContext,
    user_id: int,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Optional[dict[str, Any]]:
    """Run one of a block's actions on one task, and return the block's fresh
    row for it, or None.

    Checks only that the connection may be made: the block declares the
    action, the viewer can see the task, the block is offered on it, and the
    install can read it. The write is the plug-in's, called as the
    installation with the task and the viewer named; nothing here changes a
    row.
    """
    block = find_block(plugin, block_id)
    if block is None:
        raise _not_found()
    registration = await _live(plugin)
    action_id = f"{ENDPOINT_ID_PREFIX}{registration.public_id}.{action_key}"
    write = next(
        (
            endpoint
            for endpoint in plugin_data._endpoints(plugin.definition)
            if endpoint.get("id") == action_id
            and endpoint.get("direction") == "write"
            and endpoint.get("subject") == "task"
        ),
        None,
    )
    if write is None or action_id not in (block.get("actions") or []):
        raise _not_found()
    if is_admin_only(write) and not context.is_admin:
        raise PluginDataError(PluginDataMessages.ADMIN_ONLY, 403)

    task = await resource_access.load_child(session, Task, task_id)
    shown = await _shown_initiatives(session, plugin, context)
    if not _offered_on(block, task, shown) or not await install_readable(
        plugin, registration, guild_id=context.guild_id, task_ids=[task_id]
    ):
        raise PluginDataError(PluginDataMessages.BLOCK_NOT_OFFERED, 403)

    params, _ = plugin_data.validate_params(write, None)
    refs, fields = await plugin_data._resolve_connections(
        session, plugin=plugin, endpoint=write, user_id=None, actor="installation"
    )
    viewer = await ensure_plugin_ref(
        guild_id=context.guild_id,
        plugin_install_id=int(plugin.id or 0),
        user_id=user_id,
    )
    read_endpoint = plugin_data.find_read_endpoint(
        plugin.definition, str(block.get("endpoint") or "")
    )

    async def read(
        request: httpx.Request | plugin_data.Answered,
    ) -> Optional[dict[str, Any]]:
        if read_endpoint is None:
            # Nothing of the answer is drawn by a block with no read.
            await plugin_data._read_body(request, transport=transport)
            return None
        rows, _values = await plugin_data._read_answer(
            request, endpoint=read_endpoint, transport=transport
        )
        return _rows_by_task(rows, {task_id}).get(str(task_id))

    row = await plugin_data._call_plugin(
        registration=registration,
        plugin=plugin,
        guild_id=context.guild_id,
        endpoint_id=action_id,
        params=params,
        refs=refs,
        fields=fields,
        transport=transport,
        read=read,
        task_ids=[task_id],
        viewer=viewer,
    )
    # The action changed what the install's reads answer.
    plugin_data.clear_plugin_data_cache(
        guild_id=context.guild_id, plugin_id=int(plugin.id or 0)
    )
    return row


# --- block.stale --------------------------------------------------------------


async def mark_stale(
    plugin: GuildPlugin,
    registration: RegistrationSnapshot,
    *,
    guild_id: int,
    block_id: str,
    task_ids: Sequence[int],
    token_initiative_id: Optional[int],
) -> list[int]:
    """Tell the rooms of the initiatives holding ``task_ids`` that a block's
    rows changed, and return those initiatives.

    Only tasks the install can read count. Nothing is stored: the signal
    names the install, the block and the initiatives, and the browsers read
    the block again through its read.
    """
    if find_block(plugin, block_id) is None:
        raise _not_found()
    readable = await install_readable(
        plugin,
        registration,
        guild_id=guild_id,
        task_ids=task_ids,
        initiative_id=token_initiative_id,
    )
    initiatives = sorted(set(readable.values()))
    if initiatives:
        await _send(
            {
                "guild": guild_id,
                "install": int(plugin.id or 0),
                "block": block_id,
                "initiatives": initiatives,
            }
        )
    return initiatives


async def _send(signal: dict[str, Any]) -> None:
    """Relay one stale block to every worker; with the bus down, to this one."""
    from app.services.platform import notify_bus

    payload = json.dumps(signal, separators=(",", ":"))
    try:
        await notify_bus.notify(CHANNEL, payload)
    except Exception:
        logger.debug("plugin blocks: bus unavailable", exc_info=True)
        await deliver_stale(payload)


async def deliver_stale(payload: str) -> None:
    """Take a stale block off the bus and tell the initiatives' rooms here."""
    try:
        signal = json.loads(payload)
        guild_id = int(signal["guild"])
        install_id = int(signal["install"])
        block_id = str(signal["block"])
        initiatives = [int(initiative) for initiative in signal["initiatives"]]
    except (ValueError, KeyError, TypeError):
        logger.warning("plugin blocks: unreadable signal on %s", CHANNEL)
        return
    if guild_id not in set(sockets.guild_ids()):
        return
    for initiative_id in initiatives:
        sockets.emit_json(
            initiative_room(guild_id, initiative_id),
            {
                "changes": [
                    {
                        "resource": {"type": _RESOURCE_TYPE, "id": install_id},
                        "parents": [],
                        "initiative_id": initiative_id,
                        "action": _STALE,
                        "changed": [block_id],
                    }
                ]
            },
        )
