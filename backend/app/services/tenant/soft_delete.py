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

That same read-only rule is why a row which holds a NAME lets go of it on the
way INTO the bin rather than on the way out — see ``RELEASED_NAMES``.

Hard-purge is admin-only at the DB layer on EVERY soft-delete table: the
``soft_delete_admin_purge`` RESTRICTIVE FOR DELETE policy (rendered by
``app.db.guild_ddl`` from the SoftDeleteMixin subclasses) admits only a routed
guild admin, so a non-admin DELETE is refused by Postgres, not just by app code.
The two
guild-level soft-delete tables (initiatives, tags) have RLS enabled solely to host
that guard — not a membership gate (initiative is the gate; guilds gate at the
schema). For Documents (and Initiatives whose cascade includes Documents), upload
cleanup runs before the DELETE so blobs on disk and ``Upload`` rows pinned only by
the doomed documents are also removed.
"""

from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from sqlalchemy import text

from app.db.frozen import PURGE_GUC
from app.db.soft_delete_filter import select_including_deleted
from app.models.tenant._mixins import SoftDeleteMixin
from app.models.tenant.comment import Comment
from app.models.tenant.document import Document
from app.models.tenant.gallery import GalleryImage
from app.models.tenant.task import Task
from app.models.tenant.wiki import WikiPage
from app.services.tenant.lifecycle_tree import (
    CASCADE_CHILDREN,
    Level,
    delete_rows,
    ids_in,
    set_columns,
    subtree_levels,
)

__all__ = [
    "CASCADE_CHILDREN",
    "hard_purge_entities",
    "hard_purge_entity",
    "restore_entity",
    "soft_delete_entity",
    "trash",
]


#: Rows that hold a NAME which is unique among their siblings, mapped to the
#: column holding it and the column that says which siblings it competes with.
#:
#: A name is an address somebody types, not a fact about the row, so a row in
#: the bin has no business keeping one: a wiki page called "Step 1", thrown
#: away, must not stop the next "Step 1" from being written. It therefore
#: PARKS its name when it is stamped and takes it back when it is restored —
#: with a suffix, if somebody has taken it in the meantime, because coming back
#: under a slightly different address always beats not coming back.
#:
#: Which way round that happens is forced by the freeze: a trashed row takes no
#: content writes, so the park rides along in the same UPDATE as the stamp, and
#: the reclaim is a second UPDATE once the row is live again.
RELEASED_NAMES: dict[type, tuple[str, str]] = {
    WikiPage: ("slug", "wiki_id"),
}

#: What a parked name is parked behind. Deliberately outside the alphabet these
#: names are generated from (see ``wikis.slugify_page_title``), so a parked name
#: can never be one a live row would pick, and the id after it makes it unique
#: among everything else in the bin.
_PARK = "~"


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
    if not current or _PARK in current:
        return
    suffix = f"{_PARK}{row.id}"
    limit = _name_limit(type(row), column, len(current) + len(suffix))
    setattr(row, column, f"{current[: limit - len(suffix)]}{suffix}")


async def _reclaim_name(session: AsyncSession, row: SoftDeleteMixin) -> None:
    """Take the name back, now that the row is live enough to be written.

    The one it parked, if it is still free; the same with ``-2``, ``-3``, … if
    a row written since has it. Live siblings only — the query goes through the
    session's soft-delete filter — so two rows in the bin never argue over a
    name neither of them is using.
    """
    spec = RELEASED_NAMES.get(type(row))
    if spec is None:
        return
    column, scope_column = spec
    parked = getattr(row, column, None) or ""
    if _PARK not in parked:
        return
    wanted = parked.rsplit(_PARK, 1)[0]
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
    session.add(row)
    await session.flush()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


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
) -> list[SoftDeleteMixin]:
    """Write ``values`` onto every row of one level, a statement per table.

    A table that holds a name is loaded instead, because each of its rows parks
    (``park=True``) or later reclaims its own name; those rows are returned for
    the reclaim. The level is flushed before this returns.
    """
    named: list[SoftDeleteMixin] = []
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
            for column, value in values.items():
                setattr(row, column, value)
            if park:
                _park_name(row)
            session.add(row)
        named.extend(rows)
    await session.flush()
    return named


async def trash(
    session: AsyncSession,
    entity: SoftDeleteMixin,
    *,
    guild_id: int,
    deleted_by_user_id: Optional[int],
) -> Optional[int]:
    """Put ``entity`` in the bin under the guild's retention, and return that
    retention in days (``None``: kept until purged by hand). Caller commits."""
    from app.services.platform import guilds as guilds_service

    retention_days = await guilds_service.get_guild_retention_days(session, guild_id)
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
    deleted_at = _utc_now()
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
        for row in await _write_level(session, level, cleared):
            await _reclaim_name(session, row)


async def _purge_relationships(session: AsyncSession, doomed: Level) -> None:
    """Drop every edge naming one of these, whichever end it names them on."""
    from app.core.relationships import ENDPOINT_KINDS
    from app.services.tenant import relationships

    # Derived from the endpoint registry rather than a second list of model
    # classes: a kind that can sit on an edge is a kind whose table is named
    # there, and the model already knows its table.
    kind_by_table = {endpoint.table: kind for kind, endpoint in ENDPOINT_KINDS.items()}
    for model, ids in doomed.items():
        kind = kind_by_table.get(getattr(model, "__tablename__", ""))
        if kind is not None and ids:
            await relationships.purge_for_entities(session, kind, ids)


#: The tables whose rows the purge hooks read, not just their ids.
_PURGE_LOADS = (Comment, GalleryImage, Task, Document)


async def hard_purge_entity(
    session: AsyncSession,
    entity: SoftDeleteMixin,
) -> None:
    """Hard-delete the entity and every descendant. See ``hard_purge_entities``."""
    await hard_purge_entities(session, [entity])


async def hard_purge_entities(
    session: AsyncSession,
    entities: Iterable[SoftDeleteMixin],
) -> None:
    """Hard-delete these entities and every descendant.

    The caller's ``session`` must be able to clear the RESTRICTIVE FOR DELETE
    policies on these tables — either a routed **guild-admin** RLS session (the
    interactive purge endpoint) or a guild-admin-routed ``app_admin`` session (the
    background auto-purge worker, which has no guild context). The caller is also
    responsible for locking the targets against a concurrent restore and for
    committing.

    Descendants are walked through the same tree the soft-delete path uses,
    in the bin or not, then deleted a level at a time from the bottom up, one
    statement per table, so no foreign key is left pointing at a row that went
    first. For Documents anywhere in the set, upload cleanup runs before the
    DELETEs so blobs on disk and ``Upload`` rows pinned only by the doomed
    documents are also removed.
    """
    from app.services.tenant.documents import unresolve_wikilinks_to_document
    from app.services.tenant.attachments import (
        purge_document_uploads,
        purge_gallery_image_uploads,
        purge_pasted_images,
    )
    from app.services.tenant.reactions import purge_comment_reactions

    roots = list(entities)
    if not roots:
        return
    await session.flush()

    # Purge is the one lifecycle step that writes frozen content instead of only
    # removing it — the wikilink unresolve below reaches documents that are
    # themselves in the trash. Transaction-local (see app.db.frozen.PURGE_GUC).
    await session.exec(
        text("SELECT set_config(:name, 'true', true)").bindparams(name=PURGE_GUC)
    )

    levels = await subtree_levels(session, roots)
    doomed: Level = {}
    for level in levels:
        for model, ids in level.items():
            doomed.setdefault(model, []).extend(ids)

    loaded: dict[type, list] = {}
    for model in _PURGE_LOADS:
        if doomed.get(model):
            loaded[model] = list(
                (
                    await session.exec(
                        select_including_deleted(model).where(
                            ids_in(model.id, doomed[model])
                        )
                    )
                ).all()
            )

    # Reactions name their target polymorphically, so no foreign key carries
    # them out with the comment. Cleared explicitly, before the row goes.
    if loaded.get(Comment):
        await purge_comment_reactions(session, loaded[Comment])

    # A picture's blobs — every version and its thumbnail — go with it, the
    # way a file document's do.
    if loaded.get(GalleryImage):
        await purge_gallery_image_uploads(session, loaded[GalleryImage])

    # Pictures pasted into a task's description or a comment go with it,
    # unless something that stays still shows them.
    await purge_pasted_images(
        session, [*loaded.get(Task, ()), *loaded.get(Comment, ())]
    )

    if loaded.get(Document):
        await purge_document_uploads(session, loaded[Document])
        # Links in surviving documents that point at a doomed one are blanked
        # before the row disappears, so they render as unresolved rather than
        # pointing at nothing. Runs before the DELETEs, while the edges naming
        # it are still there to find the documents carrying those links.
        for doc in loaded[Document]:
            await unresolve_wikilinks_to_document(session, deleted_document_id=doc.id)

    # Edges name both ends polymorphically, so nothing carries them out with
    # the thing they connect. Tombstones go too: what one remembers is a link
    # between two things, and one of them is about to stop existing. Last of
    # the sweeps, because the step above reads the edges pointing at a doomed
    # document to find the documents whose links have to be blanked.
    await _purge_relationships(session, doomed)
    await session.flush()

    # Leaves before parents: most of the keys between these tables do not
    # cascade in the database.
    for level in reversed(levels):
        for model, ids in level.items():
            await delete_rows(session, model, ids)
