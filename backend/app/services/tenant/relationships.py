"""Reading and writing edges.

The table records; this module is where the shape is read. It refuses exactly
two things — an edge from a thing to itself, and a type nothing knows — and
otherwise stores what it is given, from whatever provenance. A loop between two
people's tasks is a fact about their work; a task somebody wants in two epics is
an ambiguity worth recording. Neither is this layer's business to prevent, and
both are a picker's business to warn about (see :func:`walk`).

Permission is not decided here. RLS gates both endpoints on every statement, and
the *removal* rule — your own edge, or one on a resource you can write — belongs
to the endpoint, which is where the resource and the caller's access to it are
already in hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import text, union_all
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.relationships import (
    ENDPOINT_KINDS,
    SPECS,
    Related,
    Provenance,
    RelationshipType,
    is_symmetric,
    is_transitive,
    node_id,
)
from app.core.search import SearchEntityType
from app.models.tenant.relationship import EntityRelationship

#: How deep a walk may go, whatever it is asked for. A graph that permits cycles
#: needs this even with the CYCLE clause below, because a mixed-type path can
#: revisit a node the clause is not tracking.
MAX_WALK_DEPTH = 10


@dataclass(frozen=True)
class Endpoint:
    """One end of an edge: what kind of thing, and which one."""

    kind: SearchEntityType
    id: int

    @property
    def node(self) -> int:
        return node_id(self.kind, self.id)


def _ordered(
    source: Endpoint, target: Endpoint, relationship_type: RelationshipType
) -> tuple[Endpoint, Endpoint]:
    """The pair as it is stored.

    A symmetric relation describes neither end, so there is no source to choose
    — the row is stored once with the lower node id first, and the CHECK
    constraint says the same thing. A directional one is stored as given,
    because its source is the end it describes.
    """
    if is_symmetric(relationship_type) and target.node < source.node:
        return target, source
    return source, target


class SelfLoop(ValueError):
    """An edge from a thing to itself. No relation here means anything by it."""


class NotTransitive(ValueError):
    """A multi-hop walk was asked for along a relation that does not chain."""


async def create(
    session: AsyncSession,
    *,
    source: Endpoint,
    relationship_type: RelationshipType,
    target: Endpoint,
    provenance: Provenance = Provenance.manual,
    confidence: float | None = None,
    created_by: int | None = None,
) -> EntityRelationship | None:
    """Record one edge, or return None if it is already there.

    ``provenance`` is the caller's to state and a request's never: it is the
    weight any future scoring reads, and it decides whether a removal is
    remembered. The API hands this ``manual``; the content sync hands it
    ``content``; only the accept path hands it ``inferred``.
    """
    if source.node == target.node:
        raise SelfLoop(f"{source.kind.value}:{source.id} cannot relate to itself")

    stored_source, stored_target = _ordered(source, target, relationship_type)
    existing = await find(
        session,
        source=stored_source,
        relationship_type=relationship_type,
        target=stored_target,
    )
    if existing is not None:
        return None

    row = EntityRelationship(
        source_type=stored_source.kind.value,
        source_id=stored_source.id,
        relationship_type=relationship_type.value,
        target_type=stored_target.kind.value,
        target_id=stored_target.id,
        provenance=provenance.value,
        confidence=confidence,
        created_at=datetime.now(timezone.utc),
    )
    if created_by is not None:
        row.created_by = created_by
    session.add(row)
    await session.flush()
    return row


async def find(
    session: AsyncSession,
    *,
    source: Endpoint,
    relationship_type: RelationshipType,
    target: Endpoint,
) -> EntityRelationship | None:
    """The live edge for this exact triple, if there is one."""
    stored_source, stored_target = _ordered(source, target, relationship_type)
    result = await session.exec(
        select(EntityRelationship).where(
            EntityRelationship.source_node == stored_source.node,
            EntityRelationship.relationship_type == relationship_type.value,
            EntityRelationship.target_node == stored_target.node,
            EntityRelationship.removed_at.is_(None),  # type: ignore[union-attr]
        )
    )
    return result.first()


async def remove(
    session: AsyncSession,
    row: EntityRelationship,
    *,
    removed_by: int | None,
    tombstone: bool = True,
) -> None:
    """Take an edge back.

    A person unlinking two things they had linked is the one negative signal
    nothing else in the schema records, so a manual removal keeps the row and
    marks it. An edge withdrawn because the sentence that implied it was edited
    asserts nothing and is deleted outright — counting ordinary editing as "these
    are not related" would bury the real signal in noise shaped exactly like it.
    """
    if tombstone and row.provenance == Provenance.manual.value:
        row.removed_at = datetime.now(timezone.utc)
        row.removed_by = removed_by
        session.add(row)
    else:
        await session.exec(
            delete(EntityRelationship).where(EntityRelationship.id == row.id)  # type: ignore[arg-type]
        )
    await session.flush()


async def list_for_entity(
    session: AsyncSession,
    entity: Endpoint,
    *,
    relationship_type: RelationshipType | None = None,
    other_kind: SearchEntityType | None = None,
) -> list[EntityRelationship]:
    """Every live edge touching this entity, from either side.

    Two anchored index seeks unioned, never ``WHERE source = x OR target = x``:
    the OR form can use neither index and degrades to a scan of the table, and a
    scan happens *before* the policy has narrowed anything. Both directions are
    genuinely needed — a symmetric edge is stored in node-id order, so a given
    document sits on whichever side sorted lower.
    """

    def arm(column, other_column):
        stmt = select(EntityRelationship).where(
            column == entity.node,
            EntityRelationship.removed_at.is_(None),  # type: ignore[union-attr]
        )
        if relationship_type is not None:
            stmt = stmt.where(
                EntityRelationship.relationship_type == relationship_type.value
            )
        if other_kind is not None:
            stmt = stmt.where(other_column == other_kind.value)
        return stmt

    outbound = await session.exec(
        arm(EntityRelationship.source_node, EntityRelationship.target_type)
    )
    inbound = await session.exec(
        arm(EntityRelationship.target_node, EntityRelationship.source_type)
    )
    return [*outbound.all(), *inbound.all()]


async def related_for_many(
    session: AsyncSession,
    kind: SearchEntityType,
    entity_ids: Sequence[int],
    *,
    relationship_type: RelationshipType,
    other_kind: SearchEntityType,
    model: type | None = None,
    options: Sequence[Any] = (),
) -> dict[int, list[Related]]:
    """The far ends of one relation, for many entities at once.

    **Two queries, whatever the page size.** This is the helper every list page
    goes through, so it is written to be flat in N rather than convenient: one
    UNION ALL over the two anchored indexes for the edges, one ``IN`` for the
    entities they name. Fetching per row instead would put a query per card on
    a page that already shows dozens.

    Both queries are gated. The edge query ANDs both endpoints, so an id only
    comes back if the reader clears the far end as well; the entity query then
    passes through that kind's own policies. A far end the reader cannot open
    yields ``Related.entity is None`` and the caller renders nothing for it.
    """
    nodes = [node_id(kind, entity_id) for entity_id in entity_ids]
    if not nodes:
        return {}

    columns = (
        EntityRelationship.source_node,
        EntityRelationship.source_id,
        EntityRelationship.target_node,
        EntityRelationship.target_id,
        EntityRelationship.created_at,
    )

    def arm(anchor, other_kind_column):
        return select(*columns).where(
            anchor.in_(nodes),
            EntityRelationship.relationship_type == relationship_type.value,
            other_kind_column == other_kind.value,
            EntityRelationship.removed_at.is_(None),  # type: ignore[union-attr]
        )

    rows = (
        await session.exec(
            union_all(
                arm(EntityRelationship.source_node, EntityRelationship.target_type),
                arm(EntityRelationship.target_node, EntityRelationship.source_type),
            )
        )
    ).all()

    ours = set(nodes)
    edges: list[tuple[int, int, datetime]] = []
    for source_node, source_id, target_node, target_id, created_at in rows:
        if source_node in ours:
            edges.append((source_node, target_id, created_at))
        else:
            edges.append((target_node, source_id, created_at))

    entities: dict[int, object] = {}
    if model is not None and edges:
        entity_stmt = select(model).where(
            model.id.in_({other for _, other, _ in edges})  # type: ignore[attr-defined]
        )
        if options:
            entity_stmt = entity_stmt.options(*options)
        found = await session.exec(entity_stmt)
        entities = {row.id: row for row in found.all()}

    grouped: dict[int, list[Related]] = {entity_id: [] for entity_id in entity_ids}
    by_node = {node_id(kind, entity_id): entity_id for entity_id in entity_ids}
    for node, other_id, created_at in sorted(edges, key=lambda e: e[2]):
        grouped[by_node[node]].append(
            Related(id=other_id, entity=entities.get(other_id), linked_at=created_at)
        )
    return grouped


async def related_for(
    session: AsyncSession,
    entity: Endpoint,
    *,
    relationship_type: RelationshipType,
    other_kind: SearchEntityType,
    model: type | None = None,
    options: Sequence[Any] = (),
) -> list[Related]:
    """:func:`related_for_many` for one entity — the same two queries."""
    grouped = await related_for_many(
        session,
        entity.kind,
        [entity.id],
        relationship_type=relationship_type,
        other_kind=other_kind,
        model=model,
        options=options,
    )
    return grouped.get(entity.id, [])


async def related_ids(
    session: AsyncSession,
    entity: Endpoint,
    *,
    relationship_type: RelationshipType,
    other_kind: SearchEntityType,
) -> list[int]:
    """Ids of one kind connected to this entity by one type.

    What the per-tool read schemas ask for: a project's attached documents, a
    queue item's tasks. Order is by when the edge was made, which is the order
    the junctions produced.
    """
    rows = await list_for_entity(
        session,
        entity,
        relationship_type=relationship_type,
        other_kind=other_kind,
    )
    rows.sort(key=lambda r: (r.created_at, r.id or 0))
    return [r.target_id if r.source_node == entity.node else r.source_id for r in rows]


async def set_related(
    session: AsyncSession,
    entity: Endpoint,
    *,
    relationship_type: RelationshipType,
    other_kind: SearchEntityType,
    ids: Sequence[int],
    created_by: int | None = None,
) -> None:
    """Replace one slice of an entity's edges — what a multi-select dialog does.

    Removing here is a plain delete rather than a tombstone: a replace is the UI
    restating the whole set, not a person pointing at one link and taking it
    back, and reading every dropped item as a considered negative would flood the
    signal that makes tombstones worth keeping.
    """
    wanted = list(dict.fromkeys(ids))
    current = await list_for_entity(
        session, entity, relationship_type=relationship_type, other_kind=other_kind
    )
    keep = set(wanted)

    for row in current:
        other = row.target_id if row.source_node == entity.node else row.source_id
        if other not in keep:
            await remove(session, row, removed_by=created_by, tombstone=False)

    have = {
        (row.target_id if row.source_node == entity.node else row.source_id)
        for row in current
    }
    for other_id in wanted:
        if other_id in have:
            continue
        await create(
            session,
            source=entity,
            relationship_type=relationship_type,
            target=Endpoint(other_kind, other_id),
            created_by=created_by,
        )


async def walk(
    session: AsyncSession,
    start: Endpoint,
    *,
    relationship_type: RelationshipType,
    outbound: bool = True,
    depth: int = MAX_WALK_DEPTH,
) -> list[tuple[int, int, bool]]:
    """Follow one relation, returning ``(node, depth, closes_a_cycle)``.

    Uses the SQL-standard ``CYCLE`` clause, so a cyclic graph terminates on its
    own: the row that revisits a node is flagged and not expanded, while every
    other branch carries on. That is the whole of what this design needs from
    cycles — they are recorded, and found when read — and it is why the table
    needs no rule against them.

    A multi-hop walk along a relation that does not chain is refused rather than
    answered: *A related to B* and *B related to C* says nothing about A and C,
    so walking it would return something that reads like a result and is not.
    """
    if depth > 1 and not is_transitive(relationship_type):
        raise NotTransitive(
            f"{relationship_type.value} is not transitive, so a walk deeper "
            "than one hop has no meaning"
        )
    bounded = max(1, min(depth, MAX_WALK_DEPTH))
    frm, to = (
        ("source_node", "target_node") if outbound else ("target_node", "source_node")
    )

    rows = await session.exec(
        text(f"""
            WITH RECURSIVE reachable(node, depth) AS (
                SELECT CAST(:start AS bigint), 0
              UNION ALL
                SELECT r.{to}, w.depth + 1
                FROM reachable w
                JOIN relationships r
                  ON r.{frm} = w.node
                 AND r.relationship_type = :rtype
                 AND r.removed_at IS NULL
                WHERE w.depth < :depth
            ) CYCLE node SET is_cycle USING path
            SELECT node, depth, is_cycle FROM reachable WHERE depth > 0
        """),  # noqa: S608 — column names come from a literal pair above
        {"start": start.node, "rtype": relationship_type.value, "depth": bounded},
    )
    return [(row[0], row[1], row[2]) for row in rows.all()]


async def would_close_a_cycle(
    session: AsyncSession,
    *,
    source: Endpoint,
    relationship_type: RelationshipType,
    target: Endpoint,
) -> bool:
    """Whether adding this edge would make a loop — a warning, never a refusal.

    A picker asks before it offers a candidate. The answer is shown to the
    person, who may mean it: two tasks that each wait on the other usually means
    they are one piece of work, which is worth surfacing and worth recording.
    """
    if not is_transitive(relationship_type):
        return source.node == target.node
    reachable = await walk(
        session, target, relationship_type=relationship_type, outbound=True
    )
    return any(node == source.node for node, _, _ in reachable)


async def purge_for_entities(
    session: AsyncSession,
    kind: SearchEntityType,
    entity_ids: Iterable[int],
) -> None:
    """Drop every edge naming one of these, tombstones included.

    Nothing carries an edge out with its endpoint — the endpoints are weak
    references, as on every polymorphic table here — so the purge path says so
    explicitly. A tombstone goes too: what it remembers is a link between two
    things, and one of them is about to stop existing.
    """
    nodes = [node_id(kind, entity_id) for entity_id in entity_ids]
    if not nodes:
        return
    await session.exec(
        delete(EntityRelationship).where(  # type: ignore[arg-type]
            EntityRelationship.source_node.in_(nodes)  # type: ignore[union-attr]
            | EntityRelationship.target_node.in_(nodes)  # type: ignore[union-attr]
        )
    )


__all__ = [
    "ENDPOINT_KINDS",
    "MAX_WALK_DEPTH",
    "SPECS",
    "Endpoint",
    "NotTransitive",
    "SelfLoop",
    "Related",
    "create",
    "find",
    "list_for_entity",
    "purge_for_entities",
    "related_for",
    "related_for_many",
    "related_ids",
    "remove",
    "set_related",
    "walk",
    "would_close_a_cycle",
]
