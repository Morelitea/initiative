"""An initiative's views of a tool: the shipped set, checking a set, storing it.

A target is one instance of a tool (a project) or, for a tool whose page the
initiative shares, the initiative itself (its calendar). A target with nothing
stored uses the views Initiative ships, which are stored nowhere; once a set is
stored it is the whole set, replaced together on every save.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from fastapi import HTTPException, status
from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ToolViewMessages
from app.core.tools import Tool
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.db.session import require_guild_context
from app.models.tenant.tool_view import ITEM_LAYOUT_KIND, VIEW_KIND, ToolView
from app.schemas.tenant.tool_view import (
    MAX_DEFINITION_BYTES,
    MAX_DEPTH,
    MAX_NODES,
    MAX_PLUGIN_PARTS,
    MAX_SLUG_LENGTH,
    MAX_VIEWS,
    CardPart,
    PluginPart,
    StackPart,
    ToolItemLayoutRead,
    ToolViewRead,
    ToolViewSetWrite,
    ViewDefinition,
)
from app.services.tenant.names import slugify, unique_slug

#: The layouts each tool draws. A tool that takes views and has none here yet
#: stores none.
LAYOUTS: dict[Tool, tuple[str, ...]] = {Tool.project: ("table", "board", "calendar")}

#: The kinds of item each tool's item layouts lay out.
ITEM_KINDS: dict[Tool, tuple[str, ...]] = {Tool.project: ("task",)}

#: The project filters the shipped filter views hold.
_INCOMPLETE = {"status_categories": ["backlog", "todo", "in_progress"]}
_UNASSIGNED = {"assignees": ["none"]}
_MINE = {"assignees": ["me"]}

#: The views a tool ships, as ``(slug, name, layout, filters)``, the first the
#: default. The frontend shows a shipped view still carrying its shipped name
#: in the reader's language.
SHIPPED: dict[Tool, tuple[tuple[str, str, str, Optional[dict[str, Any]]], ...]] = {
    Tool.project: (
        ("table", "Table", "table", None),
        ("board", "Board", "board", None),
        ("calendar", "Calendar", "calendar", None),
        ("incomplete", "Incomplete", "table", _INCOMPLETE),
        ("unassigned", "Unassigned", "table", _UNASSIGNED),
        ("mine", "Mine", "table", _MINE),
    ),
}


@dataclass(frozen=True)
class Target:
    """What a set of views is for."""

    tool: Tool
    #: The instance, or None for the initiative's shared page.
    tool_id: Optional[int]
    initiative_id: int


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def shipped_views(tool: Tool) -> list[ToolViewRead]:
    return [
        ToolViewRead(
            name=name,
            slug=slug,
            position=position,
            is_default=position == 0,
            definition=ViewDefinition.model_validate(
                {"layout": {"type": layout}}
                | ({"filters": filters} if filters is not None else {})
            ),
        )
        for position, (slug, name, layout, filters) in enumerate(SHIPPED.get(tool, ()))
    ]


def _of(target: Target) -> tuple[Any, ...]:
    return (
        ToolView.initiative_id == target.initiative_id,
        ToolView.tool == target.tool.value,
        col(ToolView.tool_id).is_not_distinct_from(target.tool_id),
    )


async def list_rows(session: AsyncSession, target: Target) -> list[ToolView]:
    rows = await session.exec(
        select(ToolView)
        .where(*_of(target))
        .order_by(col(ToolView.position), col(ToolView.id))
    )
    return list(rows.all())


def read_set(
    tool: Tool, rows: list[ToolView]
) -> tuple[list[ToolViewRead], list[ToolItemLayoutRead]]:
    """The views and item layouts to show: the stored ones, or the shipped
    views when nothing is stored."""
    if not rows:
        return shipped_views(tool), []
    views = [
        ToolViewRead.model_validate(row, from_attributes=True)
        for row in rows
        if row.kind == VIEW_KIND
    ]
    layouts = [
        ToolItemLayoutRead.model_validate(row, from_attributes=True)
        for row in rows
        if row.kind == ITEM_LAYOUT_KIND
    ]
    return views, layouts


def _parts(part: Any, depth: int) -> Iterable[tuple[Any, int]]:
    """Every part in a tree, with its depth."""
    yield part, depth
    if isinstance(part, (CardPart, StackPart)):
        for child in part.children:
            yield from _parts(child, depth + 1)


def _within_limits(stored: dict[str, Any], roots: list[Any], loose: int) -> None:
    """Refuse a definition past the node, depth, size or plug-in part limit.
    ``loose`` is the nodes outside any tree (columns, sorts)."""
    parts = [found for root in roots for found in _parts(root, 1)]
    if (
        len(parts) + loose > MAX_NODES
        or max((depth for _, depth in parts), default=0) > MAX_DEPTH
        or len(json.dumps(stored).encode()) > MAX_DEFINITION_BYTES
    ):
        raise _bad_request(ToolViewMessages.TOO_LARGE)
    installs = Counter(
        part.props.plugin for part, _ in parts if isinstance(part, PluginPart)
    )
    if any(count > MAX_PLUGIN_PARTS for count in installs.values()):
        raise _bad_request(ToolViewMessages.TOO_MANY_PLUGIN_PARTS)


def _stored(model: Any) -> dict[str, Any]:
    """A definition as stored: what was given, so what it leaves out is drawn
    as shipped."""
    return model.model_dump(mode="json", exclude_unset=True)


def check_set(target: Target, payload: ToolViewSetWrite) -> list[ToolView]:
    """The rows a set is stored as, or a 400 naming what is wrong with it."""
    layouts = LAYOUTS.get(target.tool, ())
    item_kinds = ITEM_KINDS.get(target.tool, ())
    if len(payload.views) > MAX_VIEWS:
        raise _bad_request(ToolViewMessages.LIMIT_REACHED)
    if sum(view.is_default for view in payload.views) != 1:
        raise _bad_request(ToolViewMessages.ONE_DEFAULT)

    named = [view.slug for view in payload.views if view.slug is not None]
    if len(set(named)) != len(named):
        raise _bad_request(ToolViewMessages.DUPLICATE_SLUG)
    taken = set(named)

    rows: list[ToolView] = []
    for position, view in enumerate(payload.views):
        definition = view.definition
        if definition.layout.type not in layouts:
            raise _bad_request(ToolViewMessages.LAYOUT_NOT_ALLOWED)
        stored = _stored(definition)
        _within_limits(
            stored,
            [definition.card] if definition.card is not None else [],
            len(definition.columns or ()) + len(definition.sort or ()),
        )
        slug = view.slug
        if slug is None:
            base = slugify(view.name, fallback="view", max_length=MAX_SLUG_LENGTH)
            slug = unique_slug(base, taken, max_length=MAX_SLUG_LENGTH)
            taken.add(slug)
        rows.append(
            _row(
                target,
                VIEW_KIND,
                stored,
                name=view.name,
                slug=slug,
                position=position,
                is_default=view.is_default,
            )
        )

    kinds = [layout.item_kind for layout in payload.item_layouts]
    if len(set(kinds)) != len(kinds):
        raise _bad_request(ToolViewMessages.DUPLICATE_ITEM_LAYOUT)
    for layout in payload.item_layouts:
        if layout.item_kind not in item_kinds:
            raise _bad_request(ToolViewMessages.LAYOUT_NOT_ALLOWED)
        regions = layout.definition
        stored = _stored(regions)
        _within_limits(
            stored,
            [r for r in (regions.header, regions.main, regions.side) if r is not None],
            0,
        )
        rows.append(_row(target, ITEM_LAYOUT_KIND, stored, item_kind=layout.item_kind))
    return rows


def _row(
    target: Target, kind: str, definition: dict[str, Any], **values: Any
) -> ToolView:
    return ToolView(
        initiative_id=target.initiative_id,
        tool=target.tool.value,
        tool_id=target.tool_id,
        kind=kind,
        definition=definition,
        **values,
    )


async def clear(session: AsyncSession, target: Target) -> None:
    """Return a target to the shipped views. Changes to one target's set take
    turns, so each starts from the set the one before it left."""
    guild_id = require_guild_context(session).guild_id
    await advisory_lock(
        session,
        LockNamespace.TOOL_VIEWS,
        f"{guild_id}:{target.tool.value}:{target.tool_id}:{target.initiative_id}",
    )
    await session.exec(delete(ToolView).where(*_of(target)))
    await session.flush()


async def replace_set(
    session: AsyncSession, target: Target, rows: list[ToolView]
) -> None:
    """Store ``rows`` as the target's whole set, in place of what it held."""
    await clear(session, target)
    session.add_all(rows)
    await session.flush()


def remap_filters(
    filters: dict[str, Any], *, status_mapping: dict[int, int]
) -> dict[str, Any]:
    """Rewrite a filter spec for a different project.

    Status ids are per-project rows, so they are translated through the clone's
    mapping and dropped when the source status has no counterpart.
    """
    remapped = dict(filters)
    status_ids = remapped.get("status_ids")
    if isinstance(status_ids, list):
        remapped["status_ids"] = [
            status_mapping[old]
            for old in status_ids
            if isinstance(old, int) and old in status_mapping
        ]
    return remapped


async def copy_views(
    session: AsyncSession,
    source: Target,
    copy: Target,
    *,
    status_mapping: dict[int, int],
) -> None:
    """Give ``copy`` the views ``source`` stored, its filters remapped."""
    for row in await list_rows(session, source):
        definition = dict(row.definition)
        if isinstance(definition.get("filters"), dict):
            definition["filters"] = remap_filters(
                definition["filters"], status_mapping=status_mapping
            )
        session.add(
            _row(
                copy,
                row.kind,
                definition,
                item_kind=row.item_kind,
                name=row.name,
                slug=row.slug,
                position=row.position,
                is_default=row.is_default,
            )
        )
    await session.flush()


async def drop_for_instances(
    session: AsyncSession, tool: Tool, tool_ids: Iterable[int]
) -> None:
    """Remove these instances' views, as they are purged."""
    ids = list(tool_ids)
    if ids:
        await session.exec(
            delete(ToolView).where(
                ToolView.tool == tool.value, col(ToolView.tool_id).in_(ids)
            )
        )
