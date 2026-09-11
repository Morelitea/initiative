"""One surface for how things connect.

Replaces the per-tool attach endpoints — a project's documents, a queue item's
documents and tasks, an event's documents — which were five routes saying the
same thing about four pairs of kinds. What varies between them is which two
kinds are named, and that is a parameter.

**What a write asks is the table's to decide, not this router's.** RLS gates
both endpoints on every statement, per type: write on the end an edge describes
and read on the other, or read on both where it describes neither. So a caller
who cannot reach an end gets a 404 from the lookup below, and one who can reach
but not edit gets nothing written.

Two rules the per-tool endpoints applied that the policy deliberately does not,
carried over because they belong to the surface rather than to the table:

* **Both ends of a link made here are in one initiative.** The table permits a
  cross-initiative edge — that is where the graph gets its reach, and content
  references will make them — but choosing one in a picker is not how they
  should arrive. ``DOCUMENT_WRONG_INITIATIVE`` is the same refusal by the same
  name.
* **An archived thing takes no new links, and gives none up.** Archiving is a
  statement that a project is finished with, and the policy has no opinion on
  it. Asked of whichever end has the state — only projects and tasks do.
"""

from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import select

from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.messages import RelationshipMessages
from app.core.relationships import ENDPOINT_KINDS, RelationshipType
from app.core.search import SearchEntityType
from app.db import reference_targets
from app.models.platform.user import User
from app.models.tenant.relationship import EntityRelationship
from app.schemas.tenant.relationship import (
    EndpointRef,
    RelatedEnd,
    RelationshipCreate,
    RelationshipRead,
)
from app.services.tenant import relationships as relationships_service
from app.services.tenant.relationships import Endpoint

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


def _parse_ref(value: str) -> EndpointRef:
    """``task:12`` as the reference vocabulary already spells it."""
    kind, _, raw_id = value.partition(":")
    try:
        entity_type = SearchEntityType(kind)
        entity_id = int(raw_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=RelationshipMessages.BAD_ENDPOINT,
        ) from None
    if entity_type not in ENDPOINT_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=RelationshipMessages.BAD_ENDPOINT,
        )
    return EndpointRef(type=entity_type, id=entity_id)


async def _resolve(
    session: RLSSessionDep, ref: EndpointRef, user_id: int
) -> reference_targets.Resolved:
    """The row behind a reference, or 404.

    Asked through ``visible_ids``, which joins the row to whatever governs it
    and calls ``public.resource_access`` — the same function the tables' own
    policies call. A thing the caller cannot open is absent rather than
    forbidden, which is what every other read here does with one.
    """
    resolved = await reference_targets.resolve_one(
        session, ref.type, ref.id, user_id=user_id
    )
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=RelationshipMessages.ENDPOINT_NOT_FOUND,
        )
    return resolved


def _refuse_across_initiatives(
    a: reference_targets.Resolved, b: reference_targets.Resolved
) -> None:
    """Both ends of a link made here belong to the same place.

    Two things can have no initiative, and they are not the same thing:

    * A **tag** belongs to none by its nature — it is the guild's own
      vocabulary, which every initiative shares. It pairs with anything the
      guild holds.
    * An **event on a guild calendar** belongs to none because that is what a
      guild calendar is: an event takes its initiative from its calendar, and a
      guild calendar has none. So it is guild-level content, and initiative
      content is not its to link. That is the rule the calendar endpoint spelled
      out as ``GUILD_CALENDAR_NO_DOCUMENTS``, which was never about documents.

    What tells them apart is whether the KIND belongs to initiatives at all:
    ``calendar_events`` does and this row does not, where ``tags`` never does.
    """
    if a.initiative_id == b.initiative_id:
        return
    guild_vocabulary = any(
        end.initiative_id is None and not end.scoped_kind for end in (a, b)
    )
    if guild_vocabulary:
        return
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=RelationshipMessages.CROSS_INITIATIVE,
    )


def _refuse_archived(*ends: reference_targets.Resolved) -> None:
    """An archived thing is finished with, and its links are part of what it
    says. Asked of both ends, and of a removal as much as an addition."""
    for end in ends:
        if end.is_archived:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=RelationshipMessages.ENDPOINT_ARCHIVED,
            )


def _endpoint_kind(value: SearchEntityType) -> SearchEntityType:
    """A kind an edge may actually name.

    ``other_type`` arrives as any ``SearchEntityType``, and the two that no
    edge can name (a comment, a counter) would otherwise reach the node
    encoder and fail there as a 500 rather than here as a refusal.
    """
    if value not in ENDPOINT_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=RelationshipMessages.BAD_ENDPOINT,
        )
    return value


def _render(
    row: EntityRelationship,
    *,
    anchor: Endpoint,
    titles: dict[tuple[str, int], reference_targets.Resolved],
) -> RelationshipRead:
    """One edge from the asking entity's side."""
    outbound = row.source_node == anchor.node
    other_type = row.target_type if outbound else row.source_type
    other_id = row.target_id if outbound else row.source_id
    found = titles.get((other_type, other_id))
    return RelationshipRead(
        id=row.id,
        relationship_type=RelationshipType(row.relationship_type),
        direction="outbound" if outbound else "inbound",
        other=RelatedEnd(
            type=SearchEntityType(other_type),
            id=other_id,
            title=found.title if found else None,
            initiative_id=found.initiative_id if found else None,
        ),
        provenance=row.provenance,
        confidence=row.confidence,
        created_by=row.created_by,
        created_at=row.created_at,
    )


async def _titles_for(
    session: RLSSessionDep,
    rows: list[EntityRelationship],
    anchor: Endpoint,
    user_id: int,
) -> dict[tuple[str, int], reference_targets.Resolved]:
    """Resolve every far end named by a page of edges — one query per kind.

    A far end the caller cannot open resolves to nothing and renders as a bare
    reference: the edge cleared the gate on this side, and the other side
    answers for itself.
    """
    wanted: dict[str, list[int]] = {}
    for row in rows:
        outbound = row.source_node == anchor.node
        kind = row.target_type if outbound else row.source_type
        entity_id = row.target_id if outbound else row.source_id
        wanted.setdefault(kind, []).append(entity_id)

    found: dict[tuple[str, int], reference_targets.Resolved] = {}
    for kind, ids in wanted.items():
        resolved = await reference_targets.resolve_many(
            session, SearchEntityType(kind), ids, user_id=user_id
        )
        for entity_id, row in resolved.items():
            found[(kind, entity_id)] = row
    return found


@router.get("/", response_model=List[RelationshipRead])
async def list_relationships(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    entity: str = Query(description="The thing to list edges for, as `kind:id`"),
    relationship_type: Optional[RelationshipType] = Query(default=None),
    other_type: Optional[SearchEntityType] = Query(default=None),
) -> List[RelationshipRead]:
    """Every live edge touching one thing, rendered from its side."""
    ref = _parse_ref(entity)
    if other_type is not None:
        other_type = _endpoint_kind(other_type)
    await _resolve(session, ref, current_user.id)
    anchor = Endpoint(ref.type, ref.id)

    rows = await relationships_service.list_for_entity(
        session,
        anchor,
        relationship_type=relationship_type,
        other_kind=other_type,
    )
    rows.sort(key=lambda r: (r.created_at, r.id or 0))
    titles = await _titles_for(session, rows, anchor, current_user.id)
    return [_render(row, anchor=anchor, titles=titles) for row in rows]


@router.post("/", response_model=RelationshipRead, status_code=status.HTTP_201_CREATED)
async def create_relationship(
    body: RelationshipCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> RelationshipRead:
    """Record one edge. 409 if it is already there."""
    source = await _resolve(session, body.source, current_user.id)
    target = await _resolve(session, body.target, current_user.id)
    _refuse_across_initiatives(source, target)
    _refuse_archived(source, target)

    try:
        row = await relationships_service.create(
            session,
            source=Endpoint(body.source.type, body.source.id),
            relationship_type=body.relationship_type,
            target=Endpoint(body.target.type, body.target.id),
            created_by=current_user.id,
        )
    except relationships_service.SelfLoop:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=RelationshipMessages.SELF,
        ) from None
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=RelationshipMessages.EXISTS,
        )
    await session.commit()

    anchor = Endpoint(body.source.type, body.source.id)
    titles = await _titles_for(session, [row], anchor, current_user.id)
    return _render(row, anchor=anchor, titles=titles)


@router.put("/", response_model=List[RelationshipRead])
async def replace_relationship_slice(
    ids: List[int],
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    entity: str = Query(description="The thing whose edges are being set"),
    relationship_type: RelationshipType = Query(),
    other_type: SearchEntityType = Query(),
) -> List[RelationshipRead]:
    """Replace one slice of an entity's edges — what a multi-select does.

    Every id named has to resolve for this caller, so a slice cannot be used to
    attach something out of reach. What is dropped is deleted rather than
    remembered: a replace is the surface restating a set, not a person taking
    one link back.
    """
    ref = _parse_ref(entity)
    other_type = _endpoint_kind(other_type)
    anchor_row = await _resolve(session, ref, current_user.id)
    _refuse_archived(anchor_row)

    wanted = list(dict.fromkeys(ids))
    resolved = await reference_targets.resolve_many(
        session, other_type, wanted, user_id=current_user.id
    )
    for entity_id in wanted:
        found = resolved.get(entity_id)
        if found is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=RelationshipMessages.ENDPOINT_NOT_FOUND,
            )
        _refuse_across_initiatives(anchor_row, found)
        _refuse_archived(found)

    anchor = Endpoint(ref.type, ref.id)

    # A replace is a bulk removal, so everything it drops answers the same
    # question a single removal does. One edge the caller may not remove fails
    # the whole request: keeping it silently would answer with a set the caller
    # did not ask for.
    keeping = set(wanted)
    for row in await relationships_service.list_for_entity(
        session, anchor, relationship_type=relationship_type, other_kind=other_type
    ):
        other_id = row.target_id if row.source_node == anchor.node else row.source_id
        if other_id in keeping:
            continue
        if not await _may_remove(session, row, current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=RelationshipMessages.REMOVE_DENIED,
            )

    await relationships_service.set_related(
        session,
        anchor,
        relationship_type=relationship_type,
        other_kind=other_type,
        ids=wanted,
        created_by=current_user.id,
    )
    await session.commit()

    rows = await relationships_service.list_for_entity(
        session, anchor, relationship_type=relationship_type, other_kind=other_type
    )
    rows.sort(key=lambda r: (r.created_at, r.id or 0))
    titles = await _titles_for(session, rows, anchor, current_user.id)
    return [_render(row, anchor=anchor, titles=titles) for row in rows]


@router.delete("/{relationship_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_relationship(
    relationship_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Take an edge back.

    Guarded here rather than by the policy, because a symmetric edge is
    writable by anyone who can read both of its ends — which is the right rule
    for making one and the wrong rule for undoing somebody else's. Your own
    edge, or one on a thing you can edit.
    """
    row = (
        await session.exec(
            select(EntityRelationship).where(
                EntityRelationship.id == relationship_id,
                EntityRelationship.removed_at.is_(None),  # type: ignore[union-attr]
            )
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=RelationshipMessages.NOT_FOUND,
        )

    if not await _may_remove(session, row, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=RelationshipMessages.REMOVE_DENIED,
        )

    await relationships_service.remove(session, row, removed_by=current_user.id)
    await session.commit()


async def _may_remove(
    session: RLSSessionDep, row: EntityRelationship, user_id: int
) -> bool:
    """Whether this caller may take one edge back.

    Your own edge, or one on a thing you can edit. The single removal and the
    replace both ask this, so a slice cannot do what a DELETE refuses.
    """
    if row.created_by == user_id:
        return True
    for kind, entity_id in (
        (row.source_type, row.source_id),
        (row.target_type, row.target_id),
    ):
        writable = await session.exec(
            reference_targets.visible_ids(
                SearchEntityType(kind), user_id, need_write=True
            ).where(reference_targets.id_column(SearchEntityType(kind)) == entity_id)
        )
        if writable.first() is not None:
            return True
    return False
