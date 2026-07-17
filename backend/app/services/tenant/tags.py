"""One code path for tag assignment across every taggable surface.

``TOOL_TAG_LINKS`` is the registry: **every** ``Tool`` is taggable — a new tool
that forgets to wire tags fails ``tools_test.py`` — and the two content-level
extras (tasks, queue items) are deliberately hard-coded in ``EXTRA_TAG_LINKS``
(they are sub-resources of a tool, not tools themselves). Everything an
assignment surface needs — validation, replace-all, copy, bulk add/remove,
serialization — lives here, so per-entity endpoints are wiring only.

Validation runs under the session-wide soft-delete filter
(``app.db.soft_delete_filter``): a trashed tag id is indistinguishable from a
nonexistent one and rejects with ``INVALID_TAG_IDS``.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence, Type

from fastapi import HTTPException, status
from sqlalchemy import delete as sa_delete, update as sa_update
from sqlalchemy.orm import selectinload
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import TagMessages
from app.core.tools import Tool
from app.models.tenant.advanced_tool import AdvancedTool, AdvancedToolTag
from app.models.tenant.calendar_event import CalendarEvent, CalendarEventTag
from app.models.tenant.counter import CounterGroup, CounterGroupTag
from app.models.tenant.document import Document
from app.models.tenant.project import Project
from app.models.tenant.queue import Queue, QueueItem, QueueItemTag, QueueTag
from app.models.tenant.tag import DocumentTag, ProjectTag, Tag, TaskTag
from app.models.tenant.task import Task
from app.schemas.tenant.tag import tag_summaries

__all__ = [
    "TAG_LINKS",
    "TOOL_TAG_LINKS",
    "EXTRA_TAG_LINKS",
    "TagLinkSpec",
    "annotate_tags",
    "active_tag_ids",
    "bulk_edit_tags",
    "copy_entity_tags",
    "replace_entity_tags",
    "set_entity_tags",
    "tag_summaries",
    "validate_guild_tag_ids",
]


@dataclass(frozen=True)
class TagLinkSpec:
    """How one taggable entity type binds to tags.

    The uniform contract (drift-tested): ``entity.tag_links`` is the
    relationship to ``junction``, and ``junction.tag`` reaches the ``Tag``.
    Everything below derives from those two names, so no entity ships its own
    tag loading/serialization code.
    """

    entity: Type[SQLModel]
    junction: Type[SQLModel]
    fk: str  # junction column naming the entity

    def entity_column(self):
        return getattr(self.junction, self.fk)

    def new_link(self, entity_id: int, tag_id: int) -> SQLModel:
        return self.junction(**{self.fk: entity_id, "tag_id": tag_id})

    def load_options(self):
        """Eager-load option chain for the entity's tags — pass to
        ``.options(...)`` on any select of ``entity``."""
        return selectinload(self.entity.tag_links).selectinload(self.junction.tag)


# Every Tool is taggable — tools_test.py asserts this spans the enum.
TOOL_TAG_LINKS: dict[Tool, TagLinkSpec] = {
    Tool.project: TagLinkSpec(Project, ProjectTag, "project_id"),
    Tool.document: TagLinkSpec(Document, DocumentTag, "document_id"),
    Tool.queue: TagLinkSpec(Queue, QueueTag, "queue_id"),
    Tool.counter_group: TagLinkSpec(CounterGroup, CounterGroupTag, "counter_group_id"),
    Tool.calendar_event: TagLinkSpec(
        CalendarEvent, CalendarEventTag, "calendar_event_id"
    ),
    Tool.advanced_tool: TagLinkSpec(AdvancedTool, AdvancedToolTag, "advanced_tool_id"),
}

# Content-level extras: sub-resources of a tool that also carry tags. These are
# the only non-Tool tag surfaces; anything else new should be a Tool.
EXTRA_TAG_LINKS: dict[str, TagLinkSpec] = {
    "task": TagLinkSpec(Task, TaskTag, "task_id"),
    "queue_item": TagLinkSpec(QueueItem, QueueItemTag, "queue_item_id"),
}

# Keyed by the wire name (`Tool.value` or the extra's key) — the bulk endpoint's
# ``target_type`` and the drift tests both read this combined view.
TAG_LINKS: dict[str, TagLinkSpec] = {
    **{tool.value: spec for tool, spec in TOOL_TAG_LINKS.items()},
    **EXTRA_TAG_LINKS,
}


async def validate_guild_tag_ids(
    session: AsyncSession, guild_id: int, tag_ids: Sequence[int]
) -> list[int]:
    """Dedup (order-preserving) and require every id to be an active tag of
    this guild; raises 400 ``INVALID_TAG_IDS`` otherwise."""
    unique = list(dict.fromkeys(tag_ids))
    if not unique:
        return []
    result = await session.exec(
        select(Tag.id).where(Tag.id.in_(unique), Tag.guild_id == guild_id)
    )
    if len(set(result.all())) != len(unique):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=TagMessages.INVALID_TAG_IDS,
        )
    return unique


async def replace_entity_tags(
    session: AsyncSession, spec: TagLinkSpec, entity_id: int, tag_ids: Sequence[int]
) -> None:
    """Replace the entity's junction rows with ``tag_ids`` (already validated
    + deduped). Does not commit."""
    await session.exec(
        sa_delete(spec.junction).where(spec.entity_column() == entity_id)
    )
    if tag_ids:
        session.add_all([spec.new_link(entity_id, tag_id) for tag_id in tag_ids])


async def set_entity_tags(
    session: AsyncSession,
    spec: TagLinkSpec,
    *,
    guild_id: int,
    entity_id: int,
    tag_ids: Sequence[int],
) -> list[int]:
    """Validate then replace — the whole single-entity write in one call.
    Returns the deduped ids. Does not commit."""
    unique = await validate_guild_tag_ids(session, guild_id, tag_ids)
    await replace_entity_tags(session, spec, entity_id, unique)
    return unique


async def active_tag_ids(
    session: AsyncSession, spec: TagLinkSpec, entity_id: int
) -> list[int]:
    """Tag ids linked to the entity whose tag is still active. Joins ``Tag``
    so the session-wide soft-delete filter applies — a trashed tag's dangling
    junction row is excluded."""
    result = await session.exec(
        select(spec.junction.tag_id)
        .join(Tag, Tag.id == spec.junction.tag_id)
        .where(spec.entity_column() == entity_id)
    )
    return list(result.all())


async def copy_entity_tags(
    session: AsyncSession, spec: TagLinkSpec, *, source_id: int, target_id: int
) -> None:
    """Copy tag links from one entity to another, dropping links whose tag has
    been trashed. Does not commit."""
    for tag_id in await active_tag_ids(session, spec, source_id):
        session.add(spec.new_link(target_id, tag_id))


async def bulk_edit_tags(
    session: AsyncSession,
    spec: TagLinkSpec,
    *,
    entity_ids: Sequence[int],
    add_tag_ids: Sequence[int],
    remove_tag_ids: Sequence[int],
) -> None:
    """Set-based add/remove across many entities in the current transaction.

    The caller authorizes every entity and validates ``add_tag_ids`` first.
    Adds are idempotent (existing links are skipped); removes are a single
    DELETE. Also bumps each entity's ``updated_at`` when the model has one.
    Does not commit.
    """
    if not entity_ids:
        return
    if remove_tag_ids:
        await session.exec(
            sa_delete(spec.junction).where(
                spec.entity_column().in_(entity_ids),
                spec.junction.tag_id.in_(remove_tag_ids),
            )
        )
    if add_tag_ids:
        existing = await session.exec(
            select(spec.entity_column(), spec.junction.tag_id).where(
                spec.entity_column().in_(entity_ids),
                spec.junction.tag_id.in_(add_tag_ids),
            )
        )
        have = set(existing.all())
        session.add_all(
            [
                spec.new_link(entity_id, tag_id)
                for entity_id in entity_ids
                for tag_id in add_tag_ids
                if (entity_id, tag_id) not in have
            ]
        )
    if "updated_at" in spec.entity.model_fields:
        await session.exec(
            sa_update(spec.entity)
            .where(spec.entity.id.in_(entity_ids))
            .values(updated_at=datetime.now(timezone.utc))
        )


def annotate_tags(entities: Iterable[SQLModel]) -> None:
    """Set ``.tags`` on every entity from its eager-loaded ``tag_links`` —
    the single serialization path for every taggable type. Entities whose
    Read schema uses ``from_attributes`` pick the annotation up directly."""
    for entity in entities:
        object.__setattr__(
            entity, "tags", tag_summaries(getattr(entity, "tag_links", None))
        )
