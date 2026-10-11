"""How an instance of a tool lists what it holds, and shows one of them: its
layouts, as shipped and as each is changed.

A target is one instance of a tool (a project) or, for a tool the initiative
shares, the initiative itself (its calendar). It has one layout of each kind
its tool draws: each way it lists what it holds, and its detail.
Each is drawn as shipped until it is changed, and stored when it is, on its
own; so is the list the target opens on. A project's lists also hold the
presets they offer.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from fastapi import HTTPException, status
from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ToolLayoutMessages
from app.core.tools import DETAIL_LAYOUTS, LAYOUT_DEFAULT, LIST_LAYOUTS, Tool
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.db.session import require_guild_context
from app.models.tenant.tool_layout import ToolLayout
from app.schemas.tenant.tool_layout import (
    MAX_DEFINITION_BYTES,
    PLUGIN_FIELD_PREFIX,
    MAX_DEPTH,
    MAX_NODES,
    MAX_PLUGIN_PARTS,
    CardPart,
    DetailLayoutDefinition,
    DetailLayoutRead,
    DetailFieldPart,
    DetailLayoutWrite,
    DetailStackPart,
    EventDetailFieldId,
    ListLayoutDefinition,
    ListLayoutRead,
    PluginPart,
    SectionPart,
    StackPart,
    TaskDetailFieldId,
    ToolLayoutRead,
    ToolLayoutWrite,
)


#: The parts any detail lays out with.
_LAYOUT_PARTS = frozenset({"stack", "section", "field", "properties"})

#: The parts each kind of detail draws. Plug-ins draw on tasks so far.
DETAIL_PARTS: dict[str, frozenset[str]] = {
    "task": _LAYOUT_PARTS
    | {
        "plugin",
        "status",
        "dates",
        "byline",
        "notice",
        "actions",
        "relations",
        "case",
        "comments",
    },
    "calendar_event": _LAYOUT_PARTS | {"dates", "rsvp", "actions", "relations"},
}

#: The built-in fields each kind of detail edits.
DETAIL_FIELDS: dict[str, frozenset[str]] = {
    "task": frozenset(field.value for field in TaskDetailFieldId),
    "calendar_event": frozenset(field.value for field in EventDetailFieldId),
}


@dataclass(frozen=True)
class Target:
    """What a set of layouts is for."""

    tool: Tool
    #: The instance, or None for the initiative's shared tool.
    tool_id: Optional[int]
    initiative_id: int


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _of(target: Target) -> tuple[Any, ...]:
    return (
        ToolLayout.initiative_id == target.initiative_id,
        ToolLayout.tool == target.tool.value,
        col(ToolLayout.tool_id).is_not_distinct_from(target.tool_id),
    )


async def list_rows(session: AsyncSession, target: Target) -> list[ToolLayout]:
    rows = await session.exec(select(ToolLayout).where(*_of(target)))
    return list(rows.all())


async def rows_by_instance(
    session: AsyncSession, initiative_id: int, tool: Tool, tool_ids: list[int]
) -> dict[int, list[ToolLayout]]:
    """The stored rows of several instances of one tool, in one read. An
    instance with nothing stored is absent."""
    if not tool_ids:
        return {}
    rows = await session.exec(
        select(ToolLayout).where(
            ToolLayout.initiative_id == initiative_id,
            ToolLayout.tool == tool.value,
            col(ToolLayout.tool_id).in_(tool_ids),
        )
    )
    found: dict[int, list[ToolLayout]] = {}
    for row in rows.all():
        if row.tool_id is not None:
            found.setdefault(row.tool_id, []).append(row)
    return found


def read_set(tool: Tool, rows: list[ToolLayout]) -> list[ToolLayoutRead]:
    """Every layout the tool draws, its lists then its details, each as stored
    or as shipped. The target opens on its default list, or on the first."""
    stored = {row.kind: row for row in rows}
    lists = LIST_LAYOUTS.get(tool, ())
    chosen = stored.get(LAYOUT_DEFAULT)
    default = chosen.definition.get("kind") if chosen is not None else None
    if default not in lists:
        default = lists[0] if lists else None

    def definition(kind: str) -> dict[str, Any]:
        row = stored.get(kind)
        return row.definition if row is not None else {}

    def when(kind: str) -> Optional[datetime]:
        row = stored.get(kind)
        return row.updated_at if row is not None else None

    layouts: list[ToolLayoutRead] = [
        ListLayoutRead(
            kind=kind,
            is_default=kind == default,
            definition=ListLayoutDefinition.model_validate(definition(kind)),
            updated_at=when(kind),
        )
        for kind in lists
    ]
    layouts.extend(
        DetailLayoutRead(
            kind=kind,
            definition=DetailLayoutDefinition.model_validate(definition(kind)),
            updated_at=when(kind),
        )
        for kind in DETAIL_LAYOUTS.get(tool, ())
    )
    return layouts


def _parts(part: Any, depth: int) -> Iterable[tuple[Any, int]]:
    """Every part in a tree, with its depth."""
    yield part, depth
    if isinstance(part, (CardPart, StackPart, DetailStackPart, SectionPart)):
        for child in part.children:
            yield from _parts(child, depth + 1)


def _within_limits(stored: dict[str, Any], roots: list[Any], loose: int) -> None:
    """Refuse a layout past the node, depth, size or plug-in part limit.
    ``loose`` is the nodes outside any tree (columns)."""
    parts = [found for root in roots for found in _parts(root, 1)]
    if (
        len(parts) + loose > MAX_NODES
        or max((depth for _, depth in parts), default=0) > MAX_DEPTH
        or len(json.dumps(stored).encode()) > MAX_DEFINITION_BYTES
    ):
        raise _bad_request(ToolLayoutMessages.TOO_LARGE)
    installs = Counter(
        part.props.plugin for part, _ in parts if isinstance(part, PluginPart)
    )
    if any(count > MAX_PLUGIN_PARTS for count in installs.values()):
        raise _bad_request(ToolLayoutMessages.TOO_MANY_PLUGIN_PARTS)


def _drawn_on(part: Any, kind: str) -> bool:
    """Whether a kind of detail draws the part: one of its own parts, or one of
    its fields. A plug-in's field is drawn where its parts are."""
    if part.type not in DETAIL_PARTS[kind]:
        return False
    if not isinstance(part, DetailFieldPart):
        return True
    field = getattr(part.props.field, "value", part.props.field)
    if field.startswith(PLUGIN_FIELD_PREFIX):
        return "plugin" in DETAIL_PARTS[kind]
    return field in DETAIL_FIELDS[kind]


def _require(kind: str, kinds: tuple[str, ...]) -> None:
    if kind not in kinds:
        raise _bad_request(ToolLayoutMessages.KIND_NOT_ALLOWED)


def check(target: Target, write: ToolLayoutWrite) -> dict[str, Any]:
    """A layout's definition as stored, or a 400 naming what is wrong with it.
    What it leaves out is left out, so it is drawn as shipped."""
    definition = write.definition
    stored = definition.model_dump(mode="json", exclude_unset=True)
    if isinstance(write, DetailLayoutWrite):
        _require(write.kind, DETAIL_LAYOUTS.get(target.tool, ()))
        assert isinstance(definition, DetailLayoutDefinition)
        roots = [
            part
            for region in (definition.header, definition.main, definition.side)
            for part in region or ()
        ]
        _within_limits(stored, roots, 0)
        if not all(
            _drawn_on(part, write.kind) for root in roots for part, _ in _parts(root, 1)
        ):
            raise _bad_request(ToolLayoutMessages.KIND_NOT_ALLOWED)
    else:
        _require(write.kind, LIST_LAYOUTS.get(target.tool, ()))
        assert isinstance(definition, ListLayoutDefinition)
        # Presets hold task filters, so only a project's lists offer them, and
        # only a table is sorted by its own.
        if definition.presets and (
            target.tool != Tool.project
            or (write.kind != "table" and any(p.sort for p in definition.presets))
        ):
            raise _bad_request(ToolLayoutMessages.KIND_NOT_ALLOWED)
        _within_limits(
            stored,
            [definition.card] if definition.card is not None else [],
            len(definition.columns or ()),
        )
    return stored


async def _locked_rows(session: AsyncSession, target: Target) -> list[ToolLayout]:
    """The target's rows, read once the changes to it before this one are
    done: changes to one target take turns."""
    guild_id = require_guild_context(session).guild_id
    await advisory_lock(
        session,
        LockNamespace.TOOL_LAYOUTS,
        f"{guild_id}:{target.tool.value}:{target.tool_id}:{target.initiative_id}",
    )
    return await list_rows(session, target)


async def _keep(
    session: AsyncSession, target: Target, kind: str, definition: dict[str, Any]
) -> None:
    """Store ``definition`` as the target's ``kind``, marking when it changed.
    The target's other rows are not touched."""
    rows = await _locked_rows(session, target)
    row = next((row for row in rows if row.kind == kind), None)
    if row is None:
        session.add(
            ToolLayout(
                initiative_id=target.initiative_id,
                tool=target.tool.value,
                tool_id=target.tool_id,
                kind=kind,
                definition=definition,
            )
        )
    elif row.definition != definition:
        row.definition = definition
        row.updated_at = datetime.now(timezone.utc)
        session.add(row)
    await session.flush()


async def save(session: AsyncSession, target: Target, write: ToolLayoutWrite) -> None:
    """Change one of the target's layouts."""
    await _keep(session, target, write.kind, check(target, write))


async def save_default(session: AsyncSession, target: Target, kind: str) -> None:
    """Open the target on its ``kind`` list."""
    _require(kind, LIST_LAYOUTS.get(target.tool, ()))
    await _keep(session, target, LAYOUT_DEFAULT, {"kind": kind})


async def reset(session: AsyncSession, target: Target, kind: str) -> None:
    """Draw one of the target's layouts as shipped again."""
    _require(
        kind, LIST_LAYOUTS.get(target.tool, ()) + DETAIL_LAYOUTS.get(target.tool, ())
    )
    for row in await _locked_rows(session, target):
        if row.kind == kind:
            await session.delete(row)
    await session.flush()


def copied_definition(
    definition: dict[str, Any],
    status_mapping: dict[int, int],
    *,
    same_initiative: bool,
) -> dict[str, Any]:
    """``definition`` for a copied project. Status ids are the project's own
    rows, so a preset's go through the copy's mapping, and one with no
    counterpart is dropped. Properties are the initiative's, so a copy into
    another initiative keeps no property filters."""
    presets = definition.get("presets")
    if not isinstance(presets, list):
        return dict(definition)

    def copied(filters: dict[str, Any]) -> dict[str, Any]:
        statuses = [
            status_mapping[old]
            for old in filters.get("status_ids", [])
            if old in status_mapping
        ]
        return {
            **filters,
            "status_ids": statuses,
            **({} if same_initiative else {"properties": []}),
        }

    return {
        **definition,
        "presets": [
            {**preset, "filters": copied(preset.get("filters", {}))}
            for preset in presets
        ],
    }


async def copy_layouts(
    session: AsyncSession,
    source: Target,
    copy: Target,
    *,
    status_mapping: dict[int, int],
) -> None:
    """Give ``copy`` what ``source`` stored, its presets' statuses its own."""
    for row in await list_rows(session, source):
        session.add(
            ToolLayout(
                initiative_id=copy.initiative_id,
                tool=copy.tool.value,
                tool_id=copy.tool_id,
                kind=row.kind,
                definition=copied_definition(
                    row.definition,
                    status_mapping,
                    same_initiative=copy.initiative_id == source.initiative_id,
                ),
            )
        )
    await session.flush()


async def drop_for_instances(
    session: AsyncSession, tool: Tool, tool_ids: Iterable[int]
) -> None:
    """Remove these instances' layouts, as they are purged."""
    ids = list(tool_ids)
    if ids:
        await session.exec(
            delete(ToolLayout).where(
                ToolLayout.tool == tool.value, col(ToolLayout.tool_id).in_(ids)
            )
        )
