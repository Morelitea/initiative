"""Archiving and unarchiving, with the cascade that makes it mean something.

Archiving says *this is finished with*. What is inside a finished thing is
finished too, so archiving an initiative archives the tools in it, and archiving
a project archives its tasks — the same shape the trash can already has, and for
the same reason: a surface that lists live work reads one column, and a project
inside an archived initiative that still reads as live would be shown as live.

The stamp is shared. Every row a cascade touches gets the SAME ``archived_at``
as the row that started it, which is what lets unarchiving put back exactly what
this archiving took: a child archived earlier, on its own, carries a different
timestamp and keeps it. That mirrors ``soft_delete``'s ``deleted_at`` rule.

The tree is derived — the trash can's ``CASCADE_CHILDREN`` narrowed to the
models that can be archived — so a tool that becomes archivable joins the
cascade by declaring the mixin, and the two lifecycles cannot disagree about
what is inside what.

Both walks go a level at a time, shallowest first, with a flush between: a row
may not clear a stamp the thing above it still carries, so a child written
before its parent was brought back would be refused. The unit of work orders
UPDATEs by mapper rather than by the order they were added, so the levels are
flushed explicitly rather than assumed.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.soft_delete_filter import select_including_deleted
from app.models.tenant._mixins import ArchiveMixin
from app.services.tenant.soft_delete import CASCADE_CHILDREN


def _archivable_tree() -> dict[
    type[ArchiveMixin], list[tuple[type[ArchiveMixin], str]]
]:
    """The trash can's tree, narrowed to what can be archived."""
    tree: dict[type[ArchiveMixin], list[tuple[type[ArchiveMixin], str]]] = {}
    for parent, children in CASCADE_CHILDREN.items():
        if not issubclass(parent, ArchiveMixin):
            continue
        archivable = [
            (child, fk) for child, fk in children if issubclass(child, ArchiveMixin)
        ]
        if archivable:
            tree[parent] = archivable
    return tree


#: parent model -> [(child model, fk column)], for the archivable tree only.
ARCHIVE_CHILDREN = _archivable_tree()


async def _descendant_levels(
    session: AsyncSession,
    parent: ArchiveMixin,
    *,
    matching: Optional[datetime],
) -> list[list[ArchiveMixin]]:
    """Every archivable descendant, grouped by how far down it sits.

    ``matching`` picks the set: ``None`` takes the ones still live (what
    archiving stamps), a timestamp takes the ones this archiving stamped (what
    unarchiving brings back).
    """
    levels: list[list[ArchiveMixin]] = []
    frontier: list[ArchiveMixin] = [parent]
    while frontier:
        level: list[ArchiveMixin] = []
        for node in frontier:
            for child_model, fk_col in ARCHIVE_CHILDREN.get(type(node), []):
                fk = getattr(child_model, fk_col)
                stmt = select_including_deleted(child_model).where(fk == node.id)
                if matching is None:
                    stmt = stmt.where(child_model.archived_at.is_(None))
                else:
                    stmt = stmt.where(child_model.archived_at == matching)
                level.extend((await session.exec(stmt)).all())
        if not level:
            break
        levels.append(level)
        frontier = level
    return levels


async def archive_entity(session: AsyncSession, entity: ArchiveMixin) -> datetime:
    """Archive it and everything inside it. Idempotent: an already-archived row
    keeps the stamp it has, so the date says when it was archived rather than
    when it was last asked about. The caller commits."""
    if entity.archived_at is not None:
        return entity.archived_at
    archived_at = datetime.now(timezone.utc)
    levels = await _descendant_levels(session, entity, matching=None)

    entity.archived_at = archived_at
    session.add(entity)
    await session.flush()
    for level in levels:
        for child in level:
            child.archived_at = archived_at
            session.add(child)
        await session.flush()
    return archived_at


async def unarchive_entity(session: AsyncSession, entity: ArchiveMixin) -> None:
    """Put it back, and with it everything this archiving took. Idempotent on a
    live row. The caller commits."""
    if entity.archived_at is None:
        return
    matching = entity.archived_at
    # Collected before anything is cleared, because the set is defined by the
    # timestamp being cleared.
    levels = await _descendant_levels(session, entity, matching=matching)

    entity.archived_at = None
    session.add(entity)
    await session.flush()
    for level in levels:
        for child in level:
            child.archived_at = None
            session.add(child)
        await session.flush()


#: What the ``archived`` query parameter says, written once for every tool's
#: list rather than reworded on each.
ARCHIVED_QUERY_DESCRIPTION = (
    "true lists what has been archived instead of what is live. Omit for the "
    "live list, which is what every other view shows."
)


def archive_filter_clause(model: type[ArchiveMixin], archived: Optional[bool]):
    """The WHERE clause a tool's list needs to answer ``archived``.

    A list shows live rows unless it is asked for the archive. That is what
    makes archiving mean anything on a list — the default view is the work in
    front of you — and it is why the archive view has to exist: a row nobody can
    find is a row nobody can take back out.

    ``None`` and ``false`` mean the same thing here, the way they do for the
    project list this generalises.
    """
    return model.archived_at.isnot(None) if archived else model.archived_at.is_(None)
