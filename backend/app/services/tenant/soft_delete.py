"""Generic soft-delete / restore / hard-purge service.

Single source of truth for the trash lifecycle on every entity that inherits
``SoftDeleteMixin``. What a trashed row takes with it is read off the foreign
keys between the soft-deletable tables (``lifecycle_tree.CASCADE_CHILDREN``),
and restore brings back the same set.

Restore does not ask who should own the entity. Ownership is recorded in
``resource_grants`` and never sits with someone who has left the guild, so a
restored row is owned by whoever owns it or by nobody — the same as it was while
in the trash. The columns restore used to reassign name the *author*, which is a
historical fact and not reassignable at all.

A trashed row is read-only at the database — see ``app.db.frozen`` — so both
walks here are ordered against that: a stamp goes deepest-first, a restore
shallowest-first, and each level is flushed before the next so the order is the
one the database sees rather than the one the unit of work picks.

A row which holds a NAME lets go of it in the same write that bins it, and
takes it back in the same write that restores it — see
``app.db.frozen.RELEASED_NAMES``.

Hard-purge is admin-only at the DB layer on EVERY soft-delete table: the
``soft_delete_admin_purge`` RESTRICTIVE FOR DELETE policy (rendered by
``app.db.guild_ddl`` from the SoftDeleteMixin subclasses) admits only a routed
guild admin, so a non-admin DELETE is refused by Postgres, not just by app code.
The two
guild-level soft-delete tables (initiatives, tags) have RLS enabled solely to host
that guard — not a membership gate (initiative is the gate; guilds gate at the
schema). For Files (and Initiatives whose cascade includes Files), upload
cleanup runs before the DELETE so blobs on disk and ``Upload`` rows pinned only by
the doomed files are also removed.
"""

from datetime import datetime, timedelta
from typing import Iterable, Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from sqlalchemy.orm import undefer

from app.db import gucs
from app.db.frozen import PARK, RELEASED_NAMES
from app.db.query import ids_in
from app.db.session import raise_flag
from app.db.soft_delete_filter import select_including_deleted
from app.models.tenant._mixins import SoftDeleteMixin
from app.models.tenant.comment import Comment
from app.models.tenant.file import File
from app.models.tenant.gallery import GalleryImage
from app.models.tenant.initiative import Initiative
from app.models.tenant.task import Task
from app.services.tenant.lifecycle_tree import (
    CASCADE_CHILDREN,
    Level,
    delete_rows,
    set_columns,
    subtree_levels,
)
from app.core.clock import utcnow

__all__ = [
    "CASCADE_CHILDREN",
    "hard_purge_entities",
    "hard_purge_entity",
    "restore_entity",
    "soft_delete_entity",
    "trash",
]


def _name_limit(model: type, column: str, fallback: int) -> int:
    """How long the column lets a name be."""
    return model.__table__.c[column].type.length or fallback


def _park_name(row: SoftDeleteMixin) -> None:
    """Let go of the row's name, in the same write that stamps it."""
    spec = RELEASED_NAMES.get(type(row))
    if spec is None:
        return
    column, _scope = spec
    current = getattr(row, column, None)
    if not current or PARK in current:
        return
    suffix = f"{PARK}{row.id}"
    limit = _name_limit(type(row), column, len(current) + len(suffix))
    setattr(row, column, f"{current[: limit - len(suffix)]}{suffix}")


async def _reclaim_name(session: AsyncSession, row: SoftDeleteMixin) -> None:
    """Take the name back, in the same write that restores the row.

    The one it parked, if it is still free; the same with ``-2``, ``-3``, … if
    a row written since has it. Live siblings only — the query goes through the
    session's soft-delete filter — so two rows in the bin never argue over a
    name neither of them is using. Asked before the row is written, while it
    is still in the bin and so not one of its own siblings.
    """
    spec = RELEASED_NAMES.get(type(row))
    if spec is None:
        return
    column, scope_column = spec
    parked = getattr(row, column, None) or ""
    if PARK not in parked:
        return
    wanted = parked.rsplit(PARK, 1)[0]
    model = type(row)
    statement = select(getattr(model, column)).where(
        getattr(model, scope_column) == getattr(row, scope_column)
    )
    taken = set((await session.exec(statement)).all())

    limit = _name_limit(model, column, len(wanted))
    candidate = wanted
    suffix = 2
    while candidate in taken:
        tail = f"-{suffix}"
        candidate = f"{wanted[: limit - len(tail)]}{tail}"
        suffix += 1
    setattr(row, column, candidate)


def _compute_purge_at(
    deleted_at: datetime, retention_days: Optional[int]
) -> Optional[datetime]:
    if retention_days is None:
        return None
    return deleted_at + timedelta(days=retention_days)


async def _write_level(
    session: AsyncSession,
    level: Level,
    values: dict[str, object],
    *,
    park: bool = False,
) -> None:
    """Write ``values`` onto every row of one level, a statement per table.

    A table that holds a name is loaded instead, because each of its rows parks
    (``park=True``) or reclaims its own name in the same write. Those rows are
    written one at a time, so a sibling reclaiming after it sees the name it
    took. The level is flushed before this returns.
    """
    for model, ids in level.items():
        if model not in RELEASED_NAMES:
            await set_columns(session, model, ids, values)
            continue
        rows = (
            await session.exec(
                select_including_deleted(model).where(ids_in(model.id, ids))
            )
        ).all()
        for row in rows:
            if not park:
                await _reclaim_name(session, row)
            for column, value in values.items():
                setattr(row, column, value)
            if park:
                _park_name(row)
            session.add(row)
            await session.flush()


async def trash(
    session: AsyncSession,
    entity: SoftDeleteMixin,
    *,
    deleted_by_user_id: Optional[int],
) -> Optional[int]:
    """Put ``entity`` in the bin under the retention of the guild the session
    is routed to, and return that retention in days (``None``: kept until
    purged by hand). Caller commits."""
    from app.services.platform import guilds as guilds_service

    retention_days = await guilds_service.get_guild_retention_days(session)
    await soft_delete_entity(
        session,
        entity,
        deleted_by_user_id=deleted_by_user_id,
        retention_days=retention_days,
    )
    return retention_days


async def soft_delete_entity(
    session: AsyncSession,
    entity: SoftDeleteMixin,
    *,
    deleted_by_user_id: Optional[int],
    retention_days: Optional[int],
) -> None:
    """Stamp the entity and every active descendant as soft-deleted.

    Idempotent: re-stamping an already-soft-deleted entity is a no-op so
    callers can safely retry. The caller is responsible for committing.
    """
    if entity.deleted_at is not None:
        return
    await session.flush()
    deleted_at = utcnow()
    values = {
        "deleted_at": deleted_at,
        "deleted_by": deleted_by_user_id,
        "purge_at": _compute_purge_at(deleted_at, retention_days),
    }

    # Deepest first, with a flush per level. A trashed row freezes everything
    # under it at the database, so a child written after its parent was stamped
    # would be refused. Collected before anything is stamped, while the walk's
    # own queries still see an untouched tree.
    levels = await subtree_levels(
        session, [entity], where=lambda model: model.deleted_at.is_(None)
    )
    for level in reversed(levels):
        await _write_level(session, level, values, park=True)


async def restore_entity(
    session: AsyncSession,
    entity: SoftDeleteMixin,
) -> None:
    """Restore the entity and its cascaded descendants.

    Idempotent on already-active rows. Caller commits.
    """
    if entity.deleted_at is None:
        return
    await session.flush()

    matching = entity.deleted_at
    # The mirror of the stamp above: shallowest first, so a child is never
    # written while its parent is still trashed. Collected before anything is
    # cleared, because the set is defined by the timestamp being cleared.
    levels = await subtree_levels(
        session, [entity], where=lambda model: model.deleted_at == matching
    )
    cleared = {"deleted_at": None, "deleted_by": None, "purge_at": None}
    for level in levels:
        await _write_level(session, level, cleared)


async def _purge_references(session: AsyncSession, doomed: Level) -> None:
    """Drop every row that names one of these by ``(kind, id)``: edges,
    reactions, recent views and custom property values.

    Nothing carries those out with the row they name, and once it is gone
    their policies have nothing to ask, so they go first. Each kind is read
    from the registry that lets the table name it, and the model already
    knows its table.
    """
    from app.core.reactions import ReactionTarget
    from app.core.relationships import ENDPOINT_KINDS
    from app.db.initiative_rls import RECENT_ENTITY_TABLES
    from app.services.tenant import properties, reactions, recent_views, relationships

    edge_kinds = {endpoint.table: kind for kind, endpoint in ENDPOINT_KINDS.items()}
    reaction_targets = {target.table: target for target in ReactionTarget}
    recent_kinds = {table: kind for kind, table in RECENT_ENTITY_TABLES.items()}
    for model, ids in doomed.items():
        table = getattr(model, "__tablename__", "")
        if not ids:
            continue
        if (kind := edge_kinds.get(table)) is not None:
            await relationships.purge_for_entities(session, kind, ids)
        if (target := reaction_targets.get(table)) is not None:
            await reactions.purge_reactions_for(session, target=target, target_ids=ids)
        if (recent := recent_kinds.get(table)) is not None:
            await recent_views.purge_for_entities(session, recent, ids)
        if (spec := properties.PROPERTY_LINKS_BY_MODEL.get(model)) is not None:
            await properties.drop_values(session, spec.target, ids)


#: The tables whose rows the purge hooks read, not just their ids, with the
#: deferred columns those hooks read.
_PURGE_LOADS: dict[type, tuple] = {
    Comment: (),
    GalleryImage: (),
    Task: (),
    File: (undefer(File.content),),
}


async def hard_purge_entity(
    session: AsyncSession,
    entity: SoftDeleteMixin,
) -> set[str]:
    """Hard-delete the entity and every descendant. See ``hard_purge_entities``."""
    return await hard_purge_entities(session, [entity])


async def hard_purge_entities(
    session: AsyncSession,
    entities: Iterable[SoftDeleteMixin],
) -> set[str]:
    """Hard-delete these entities and every descendant, and return the stored
    names of the uploads that went with them.

    The caller's ``session`` must be able to clear the RESTRICTIVE FOR DELETE
    policies on these tables — either a routed **guild-admin** RLS session (the
    interactive purge endpoint) or a guild-admin-routed ``app_admin`` session (the
    background auto-purge worker, which has no guild context). The caller is also
    responsible for locking the targets against a concurrent restore and for
    committing, and for deleting the returned blobs after its commit
    (``attachments.delete_blobs``), so a rolled-back purge leaves the files.

    Descendants are walked through the same tree the soft-delete path uses,
    in the bin or not, then deleted a level at a time from the bottom up, one
    statement per table, so no foreign key is left pointing at a row that went
    first. For Files anywhere in the set, upload cleanup runs before the
    DELETEs so ``Upload`` rows pinned only by the doomed files go too.
    """
    from app.services.tenant.files import unresolve_wikilinks_to_file
    from app.services.tenant.attachments import (
        purge_file_uploads,
        purge_gallery_image_uploads,
        purge_initiative_uploads,
        purge_pasted_images,
    )

    roots = list(entities)
    if not roots:
        return set()
    await session.flush()

    # Purge is the one lifecycle step that writes frozen content instead of only
    # removing it — the wikilink unresolve below reaches files that are
    # themselves in the trash. Transaction-local (see app.db.gucs.PURGING).
    await raise_flag(session, gucs.PURGING)

    levels = await subtree_levels(session, roots)
    doomed: Level = {}
    for level in levels:
        for model, ids in level.items():
            doomed.setdefault(model, []).extend(ids)

    loaded: dict[type, list] = {}
    for model, options in _PURGE_LOADS.items():
        if doomed.get(model):
            loaded[model] = list(
                (
                    await session.exec(
                        select_including_deleted(model)
                        .where(ids_in(model.id, doomed[model]))
                        .options(*options)
                    )
                ).all()
            )

    # A picture's blobs — every version and its thumbnail — go with it, the
    # way an uploaded file's do.
    released: set[str] = set()
    if loaded.get(GalleryImage):
        released |= await purge_gallery_image_uploads(session, loaded[GalleryImage])

    # Pictures pasted into a task's description or a comment go with it,
    # unless something that stays still shows them.
    released |= await purge_pasted_images(
        session, [*loaded.get(Task, ()), *loaded.get(Comment, ())]
    )

    if loaded.get(File):
        released |= await purge_file_uploads(session, loaded[File])
        # Links in surviving files that point at a doomed one are blanked
        # before the row disappears, so they render as unresolved rather than
        # pointing at nothing. Runs before the DELETEs, while the edges naming
        # it are still there to find the files carrying those links.
        for doc in loaded[File]:
            await unresolve_wikilinks_to_file(session, deleted_file_id=doc.id)

    # What is left of an initiative's files goes with it.
    if doomed.get(Initiative):
        released |= await purge_initiative_uploads(session, doomed[Initiative])

    # Tombstones go with the edges: what one remembers is a link between two
    # things, and one of them is about to stop existing. Last of the sweeps,
    # because the step above reads the edges pointing at a doomed file to
    # find the files whose links have to be blanked.
    await _purge_references(session, doomed)
    await session.flush()

    # Leaves before parents: most of the keys between these tables do not
    # cascade in the database.
    for level in reversed(levels):
        for model, ids in level.items():
            await delete_rows(session, model, ids)
    return released
