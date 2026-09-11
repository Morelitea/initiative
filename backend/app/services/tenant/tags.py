"""One code path for tag assignment across every taggable surface.

``TOOL_TAG_LINKS`` is the registry: **every** ``Tool`` is taggable — a new tool
that forgets to wire tags fails ``tools_test.py`` — and the content-level
extras (tasks, queue items, calendar events, gallery images) are deliberately
hard-coded in ``EXTRA_TAG_LINKS`` (they are sub-resources of a tool, not tools
themselves). Everything an assignment surface needs — validation, replace-all,
copy, bulk add/remove, serialization — lives here, so per-entity endpoints are
wiring only.

A tag assignment is stored as one ``tagged_with`` edge in ``relationships``:
the tagged thing is the source, the tag is the target. So a spec is no longer a
junction class and a foreign key — it is the entity model and the endpoint kind
that names it, and every query below is one query against one table whatever is
being tagged.

Validation runs under the session-wide soft-delete filter
(``app.db.soft_delete_filter``): a trashed tag id is indistinguishable from a
nonexistent one and rejects with ``INVALID_TAG_IDS``. Reads join ``tags`` for
the same reason — an edge to a trashed tag is not an assignment anyone can see,
and every count and filter here agrees on that.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence, Type

from fastapi import HTTPException, status
from sqlalchemy import (
    BigInteger,
    and_,
    delete as sa_delete,
    exists,
    literal,
    update as sa_update,
)
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import SQLModel, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import TagMessages
from app.core.relationships import (
    Provenance,
    RelationshipType,
    node_base,
    node_id,
)
from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.models.tenant.calendar import Calendar
from app.models.tenant.calendar_event import CalendarEvent
from app.models.tenant.counter import CounterGroup
from app.models.tenant.dashboard import Dashboard
from app.models.tenant.post import Post
from app.models.tenant.gallery import Gallery, GalleryImage
from app.models.tenant.document import Document
from app.models.tenant.project import Project
from app.models.tenant.queue import Queue, QueueItem
from app.models.tenant.relationship import EntityRelationship
from app.models.tenant.tag import Tag
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
    "spec_for",
    "tag_edge",
    "tag_counts_for",
    "tag_summaries",
    "tagged_entity_ids",
    "untagged_clause",
    "validate_guild_tag_ids",
]

#: The one relation every function here reads and writes.
_TAGGED = RelationshipType.tagged_with


@dataclass(frozen=True)
class TagLinkSpec:
    """How one taggable entity type binds to tags.

    Two facts, and everything else derives: the model, and the endpoint kind an
    edge names it by. There is no junction to declare because there is no
    junction — a tag assignment is a ``tagged_with`` edge like any other, and
    what varies between a project's tags and a task's is one string.
    """

    entity: Type[SQLModel]
    kind: SearchEntityType

    def node_of(self, entity_id: int) -> int:
        return node_id(self.kind, entity_id)

    def node_of_column(self, entity_id: ColumnElement[int]) -> ColumnElement[int]:
        """An id column as node ids, for the indexed edge column.

        The edge table indexes the packed pair, not the two columns it is packed
        from, so a query that wants the index has to ask in those terms. The
        base is typed ``BigInteger`` explicitly: inferred from an ``int4`` id
        column it would be sent as one, and every kind code but the first is
        past the end of that range.
        """
        return literal(node_base(self.kind), BigInteger) + entity_id


# Every Tool is taggable — tools_test.py asserts this spans the enum.
TOOL_TAG_LINKS: dict[Tool, TagLinkSpec] = {
    Tool.project: TagLinkSpec(Project, SearchEntityType.project),
    Tool.document: TagLinkSpec(Document, SearchEntityType.document),
    Tool.queue: TagLinkSpec(Queue, SearchEntityType.queue),
    Tool.counter_group: TagLinkSpec(CounterGroup, SearchEntityType.counter_group),
    Tool.calendar: TagLinkSpec(Calendar, SearchEntityType.calendar),
    Tool.dashboard: TagLinkSpec(Dashboard, SearchEntityType.dashboard),
    Tool.post: TagLinkSpec(Post, SearchEntityType.post),
    Tool.gallery: TagLinkSpec(Gallery, SearchEntityType.gallery),
}

# Content-level extras: sub-resources of a tool that also carry tags. These are
# the only non-Tool tag surfaces; anything else new should be a Tool.
EXTRA_TAG_LINKS: dict[str, TagLinkSpec] = {
    "task": TagLinkSpec(Task, SearchEntityType.task),
    "queue_item": TagLinkSpec(QueueItem, SearchEntityType.queue_item),
    "calendar_event": TagLinkSpec(CalendarEvent, SearchEntityType.calendar_event),
    "gallery_image": TagLinkSpec(GalleryImage, SearchEntityType.gallery_image),
}

# Keyed by the wire name (`Tool.value` or the extra's key) — the bulk endpoint's
# ``target_type`` and the drift tests both read this combined view.
TAG_LINKS: dict[str, TagLinkSpec] = {
    **{tool.value: spec for tool, spec in TOOL_TAG_LINKS.items()},
    **EXTRA_TAG_LINKS,
}

#: The same registry keyed by model, so a caller holding entities need not also
#: say what they are. Derived, never a second list.
_SPEC_BY_MODEL: dict[Type[SQLModel], TagLinkSpec] = {
    spec.entity: spec for spec in TAG_LINKS.values()
}


def spec_for(entity: Any) -> TagLinkSpec:
    """The spec for an entity or its model. Raises for an untaggable type."""
    model = entity if isinstance(entity, type) else type(entity)
    try:
        return _SPEC_BY_MODEL[model]
    except KeyError:  # pragma: no cover - a programming error, not a request
        raise KeyError(f"{model.__name__} carries no tags") from None


# ---------------------------------------------------------------------------
# The edge, as a query
# ---------------------------------------------------------------------------


def _live_tag_edge(spec: TagLinkSpec) -> list[Any]:
    """What makes a row one of this kind's live tag assignments."""
    return [
        EntityRelationship.relationship_type == _TAGGED.value,
        EntityRelationship.source_type == spec.kind.value,
        EntityRelationship.target_type == SearchEntityType.tag.value,
        EntityRelationship.removed_at.is_(None),  # type: ignore[union-attr]
    ]


def tagged_entity_ids(
    spec: TagLinkSpec, tag_ids: Sequence[int], *, guild_id: int | None = None
) -> Select:
    """Ids of this kind carrying any of ``tag_ids``.

    Driven from the tag end, which is the indexed one for this direction, and
    joined to ``tags`` so a trashed tag matches nothing. ``guild_id`` adds the
    guild leg where the caller has one — a second answer to a question the
    schema boundary already answers, kept because a filter takes its ids from
    the request.
    """
    conditions = [
        EntityRelationship.target_node.in_(
            [node_id(SearchEntityType.tag, tag_id) for tag_id in tag_ids]
        ),
        *_live_tag_edge(spec),
    ]
    if guild_id is not None:
        conditions.append(Tag.guild_id == guild_id)
    return (
        select(EntityRelationship.source_id)
        .join(Tag, Tag.id == EntityRelationship.target_id)
        .where(*conditions)
        .distinct()
    )


def untagged_clause(
    spec: TagLinkSpec, entity_id: ColumnElement[int]
) -> ColumnElement[bool]:
    """True for a row of this kind carrying no live tag.

    Correlated on the id column the caller hands in — the entity table itself in
    a list filter, a subquery's column in a counts query — so one definition
    serves both and they cannot disagree about what "untagged" means.
    """
    return ~exists(
        select(EntityRelationship.id)
        .join(Tag, Tag.id == EntityRelationship.target_id)
        .where(
            EntityRelationship.source_node == spec.node_of_column(entity_id),
            *_live_tag_edge(spec),
        )
    )


def tag_counts_for(spec: TagLinkSpec, entity_ids: Select) -> Select:
    """``(tag_id, count)`` over the rows of this kind that ``entity_ids`` names."""
    return (
        select(EntityRelationship.target_id, func.count(EntityRelationship.source_id))
        .join(Tag, Tag.id == EntityRelationship.target_id)
        .where(
            EntityRelationship.source_id.in_(entity_ids),
            *_live_tag_edge(spec),
        )
        .group_by(EntityRelationship.target_id)
    )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


async def _tags_for(
    session: AsyncSession, spec: TagLinkSpec, entity_ids: Sequence[int]
) -> dict[int, list[Tag]]:
    """Live tags of many entities of one kind, in two queries whatever the page.

    One seek on the edge table's source index for the pairs, one ``IN`` for the
    tags themselves — flat in the number of entities, because this is what every
    list page goes through.
    """
    ids = list(dict.fromkeys(entity_ids))
    if not ids:
        return {}
    nodes = {spec.node_of(entity_id): entity_id for entity_id in ids}
    rows = (
        await session.exec(
            select(EntityRelationship.source_node, EntityRelationship.target_id).where(
                EntityRelationship.source_node.in_(list(nodes)),
                *_live_tag_edge(spec),
            )
        )
    ).all()
    if not rows:
        return {entity_id: [] for entity_id in ids}

    found = (
        await session.exec(
            select(Tag).where(Tag.id.in_({tag_id for _, tag_id in rows}))
        )
    ).all()
    by_id = {tag.id: tag for tag in found}

    grouped: dict[int, list[Tag]] = {entity_id: [] for entity_id in ids}
    for node, tag_id in rows:
        # A tag the reader cannot see — trashed, and so filtered by the
        # session-wide rule — is not an assignment, exactly as the junction era
        # decided by joining tags on every read.
        tag = by_id.get(tag_id)
        if tag is not None:
            grouped[nodes[node]].append(tag)
    return grouped


async def annotate_tags(session: AsyncSession, entities: Iterable[SQLModel]) -> None:
    """Set ``.tags`` on every entity — the single serialization path.

    The kind comes from the entities themselves, so a caller never states twice
    what it is already holding. Entities whose Read schema uses
    ``from_attributes`` pick the annotation up directly.
    """
    rows = [entity for entity in entities if entity is not None]
    if not rows:
        return
    spec = spec_for(rows[0])
    grouped = await _tags_for(session, spec, [row.id for row in rows])
    for row in rows:
        object.__setattr__(row, "tags", tag_summaries(grouped.get(row.id, [])))


async def active_tag_ids(
    session: AsyncSession, spec: TagLinkSpec, entity_id: int
) -> list[int]:
    """Tag ids assigned to the entity whose tag is still active."""
    grouped = await _tags_for(session, spec, [entity_id])
    return [tag.id for tag in grouped.get(entity_id, []) if tag.id is not None]


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


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


def _new_edge(spec: TagLinkSpec, entity_id: int, tag_id: int) -> EntityRelationship:
    """One assignment. ``tagged_with`` is directional — a tag is a label, so the
    edge describes the thing carrying it — which is why the tagged entity is
    always the source and no ordering question arises."""
    return EntityRelationship(
        source_type=spec.kind.value,
        source_id=entity_id,
        relationship_type=_TAGGED.value,
        target_type=SearchEntityType.tag.value,
        target_id=tag_id,
        provenance=Provenance.manual.value,
        created_at=datetime.now(timezone.utc),
    )


def tag_edge(spec: TagLinkSpec, entity_id: int, tag_id: int) -> EntityRelationship:
    """One assignment, for a caller adding it to the session itself.

    What an import does: the entity is new, so there is nothing to deduplicate
    against and the round-trip a replace would pay for buys nothing.
    """
    return _new_edge(spec, entity_id, tag_id)


def _drop(spec: TagLinkSpec, entity_ids: Sequence[int], tag_ids: Sequence[int] | None):
    """DELETE for assignments of these entities, optionally narrowed to tags.

    A replace or a bulk remove is the UI restating a set, not a person pointing
    at one link and taking it back, so these rows go rather than tombstone —
    reading every dropped assignment as a considered negative would bury the
    signal a tombstone exists to keep.
    """
    conditions = [
        EntityRelationship.source_node.in_([spec.node_of(i) for i in entity_ids]),
        *_live_tag_edge(spec),
    ]
    if tag_ids is not None:
        conditions.append(
            EntityRelationship.target_node.in_(
                [node_id(SearchEntityType.tag, tag_id) for tag_id in tag_ids]
            )
        )
    return sa_delete(EntityRelationship).where(and_(*conditions))


async def replace_entity_tags(
    session: AsyncSession, spec: TagLinkSpec, entity_id: int, tag_ids: Sequence[int]
) -> None:
    """Replace the entity's assignments with ``tag_ids`` (already validated
    + deduped). Does not commit."""
    await session.exec(_drop(spec, [entity_id], None))
    for tag_id in tag_ids:
        session.add(_new_edge(spec, entity_id, tag_id))


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


async def copy_entity_tags(
    session: AsyncSession, spec: TagLinkSpec, *, source_id: int, target_id: int
) -> None:
    """Copy assignments from one entity to another, dropping any whose tag has
    been trashed. Does not commit."""
    for tag_id in await active_tag_ids(session, spec, source_id):
        session.add(_new_edge(spec, target_id, tag_id))


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
    Adds are idempotent (existing assignments are skipped); removes are a single
    DELETE. Also bumps each entity's ``updated_at`` when the model has one.
    Does not commit.
    """
    if not entity_ids:
        return
    if remove_tag_ids:
        await session.exec(_drop(spec, entity_ids, remove_tag_ids))
    if add_tag_ids:
        existing = await session.exec(
            select(EntityRelationship.source_id, EntityRelationship.target_id).where(
                EntityRelationship.source_node.in_(
                    [spec.node_of(i) for i in entity_ids]
                ),
                EntityRelationship.target_node.in_(
                    [node_id(SearchEntityType.tag, t) for t in add_tag_ids]
                ),
                *_live_tag_edge(spec),
            )
        )
        have = set(existing.all())
        session.add_all(
            [
                _new_edge(spec, entity_id, tag_id)
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
