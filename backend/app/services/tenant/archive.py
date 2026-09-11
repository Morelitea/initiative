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


async def _stamp_descendants(
    session: AsyncSession,
    parent: ArchiveMixin,
    *,
    archived_at: Optional[datetime],
    matching: Optional[datetime] = None,
) -> int:
    """Walk down, stamping or clearing. Returns how many rows were touched.

    ``matching`` is the unarchive side: only descendants carrying that exact
    timestamp are cleared, so one archived on its own stays archived.

    No flushing between levels. A lifecycle column is the one thing a row under
    an archived parent may still change, so the order these reach the database
    in does not matter — which is the whole point of the guard being a trigger
    that compares the old row with the new one.
    """
    touched = 0
    for child_model, fk_col in ARCHIVE_CHILDREN.get(type(parent), []):
        fk = getattr(child_model, fk_col)
        stmt = select_including_deleted(child_model).where(fk == parent.id)
        if matching is None:
            stmt = stmt.where(child_model.archived_at.is_(None))
        else:
            stmt = stmt.where(child_model.archived_at == matching)
        for child in (await session.exec(stmt)).all():
            child.archived_at = archived_at
            session.add(child)
            touched += 1
            touched += await _stamp_descendants(
                session, child, archived_at=archived_at, matching=matching
            )
    return touched


async def archive_entity(session: AsyncSession, entity: ArchiveMixin) -> datetime:
    """Archive it and everything inside it. Idempotent: an already-archived row
    keeps the stamp it has, so the date says when it was archived rather than
    when it was last asked about. The caller commits."""
    if entity.archived_at is not None:
        return entity.archived_at
    archived_at = datetime.now(timezone.utc)
    entity.archived_at = archived_at
    session.add(entity)
    await _stamp_descendants(session, entity, archived_at=archived_at)
    return archived_at


async def unarchive_entity(session: AsyncSession, entity: ArchiveMixin) -> None:
    """Put it back, and with it everything this archiving took. Idempotent on a
    live row. The caller commits."""
    if entity.archived_at is None:
        return
    matching = entity.archived_at
    entity.archived_at = None
    session.add(entity)
    await _stamp_descendants(session, entity, archived_at=None, matching=matching)
