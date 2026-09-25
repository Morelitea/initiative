"""What is inside what, for the lifecycles that take a whole subtree with them.

Trashing, restoring, purging and archiving all act on a row *and everything
filed under it*. The tree they walk is not written down anywhere: it is read off
the foreign keys between the soft-deletable tables, so a table that joins the
trash can with a key to its parent joins the cascade in the same change, and the
four lifecycles cannot disagree about it.

A key that lets go on delete (``SET NULL``) is a pointer rather than ownership —
a gallery's cover picture, a queue's current item, a wiki's home page — so it is
not an edge: the thing it points at is filed under the same parent already.

The walk goes a level at a time, one query per edge per level rather than one
per row, and each level is written with one statement per table. Callers pick
the direction: a stamp goes deepest-first, a restore shallowest-first, because a
trashed or archived row freezes everything under it at the database (see
``app.db.frozen``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from functools import cache
from typing import Any, Optional

from sqlalchemy import Integer, any_, bindparam, delete, update
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import RelationshipDirection
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.soft_delete_filter import SOFT_DELETE_MODELS, select_including_deleted

#: parent model -> [(child model, fk column on the child)]
Tree = Mapping[type, Sequence[tuple[type, str]]]

#: model -> ids, for one level of a walk.
Level = dict[type, list[int]]

#: A subtree deeper than this is a cycle in the data, not a tree.
_MAX_DEPTH = 256


def _derive_children() -> dict[type, list[tuple[type, str]]]:
    by_table = {model.__tablename__: model for model in SOFT_DELETE_MODELS}
    tree: dict[type, list[tuple[type, str]]] = {}
    for child in SOFT_DELETE_MODELS:
        for column in child.__table__.columns:
            for fk in column.foreign_keys:
                parent = by_table.get(fk.target_fullname.rsplit(".", 1)[0])
                if parent is None or (fk.ondelete or "").upper() == "SET NULL":
                    continue
                tree.setdefault(parent, []).append((child, column.name))
    return tree


#: parent model -> [(child model, fk column)]: what a trashed row takes with it.
CASCADE_CHILDREN: dict[type, list[tuple[type, str]]] = _derive_children()

#: child model -> [(parent model, fk column)]: the same edges read upwards.
CASCADE_PARENTS: dict[type, list[tuple[type, str]]] = {}
for _parent, _children in CASCADE_CHILDREN.items():
    for _child, _fk in _children:
        CASCADE_PARENTS.setdefault(_child, []).append((_parent, _fk))


def parents_first(models: Iterable[type]) -> tuple[type, ...]:
    """``models`` ordered so every parent comes before its children.

    A table's edge to itself (a reply under a comment, a page under a page) is
    no constraint on the order. Ties keep the order they were given in.
    """
    pending = list(models)
    placed: list[type] = []
    while pending:
        for model in pending:
            parents = {p for p, _ in CASCADE_PARENTS.get(model, ()) if p is not model}
            if not parents & set(pending):
                placed.append(model)
                pending.remove(model)
                break
        else:  # pragma: no cover — the tables' keys would have to form a loop
            raise RuntimeError(f"cascade tree has a cycle among {pending}")
    return tuple(placed)


def ids_in(column: Any, ids: Iterable[int]) -> Any:
    """``column = ANY(:ids)`` — one bound array, however many ids there are."""
    return column == any_(bindparam(None, list(ids), type_=ARRAY(Integer)))


def group_by_model(rows: Iterable[SQLModel]) -> Level:
    level: Level = {}
    for row in rows:
        level.setdefault(type(row), []).append(row.id)  # type: ignore[attr-defined]
    return level


def _keep_deepest(levels: list[Level]) -> list[Level]:
    """Drop every row from all but the deepest level it was reached at.

    A reply is filed under its comment and also names the thing the thread is
    on, so it is reached twice. Its deepest level is the one that is below all
    of its parents, which is the one every direction of write needs.
    """
    seen: set[tuple[type, int]] = set()
    kept: list[Level] = []
    for level in reversed(levels):
        narrowed: Level = {}
        for model, ids in level.items():
            fresh = [i for i in ids if (model, i) not in seen]
            seen.update((model, i) for i in fresh)
            if fresh:
                narrowed[model] = fresh
        kept.append(narrowed)
    kept.reverse()
    return [level for level in kept if level]


async def subtree_levels(
    session: AsyncSession,
    roots: Iterable[SQLModel],
    *,
    tree: Tree = CASCADE_CHILDREN,
    where: Optional[Callable[[type], Any]] = None,
) -> list[Level]:
    """The roots and everything under them, grouped by depth — roots first.

    ``where(model)`` narrows which children are followed (the ones still live,
    the ones stamped by one particular trashing, …); without it every child is,
    in the bin or not. Each row appears once, at the deepest level it sits.
    """
    levels: list[Level] = []
    frontier = group_by_model(roots)
    while frontier:
        if len(levels) >= _MAX_DEPTH:
            raise RuntimeError("cascade tree is deeper than any real one could be")
        levels.append(frontier)
        found: dict[type, dict[int, None]] = {}
        for parent_model, parent_ids in frontier.items():
            for child_model, fk_col in tree.get(parent_model, ()):
                stmt = select_including_deleted(child_model.id).where(  # type: ignore[attr-defined]
                    ids_in(getattr(child_model, fk_col), parent_ids)
                )
                if where is not None:
                    stmt = stmt.where(where(child_model))
                for child_id in (await session.exec(stmt)).all():
                    found.setdefault(child_model, {})[child_id] = None
        frontier = {model: list(ids) for model, ids in found.items()}
    return _keep_deepest(levels)


async def set_columns(
    session: AsyncSession, model: type, ids: Sequence[int], values: dict[str, Any]
) -> None:
    """One UPDATE for every row of ``model`` named, kept in step with any of
    them the session already holds."""
    await session.exec(
        update(model)  # type: ignore[call-overload]
        .where(ids_in(model.id, ids))  # type: ignore[attr-defined]
        .values(**values)
        .execution_options(synchronize_session="fetch")
    )


@cache
def _orm_dependents(model: type) -> tuple[tuple[type, Any], ...]:
    """The rows a model's relationships delete along with it, as
    ``(table, key column)`` — its task statuses, its members, its file
    versions. A bulk DELETE never loads them the way ``session.delete`` does,
    so it removes them itself, before the rows they hang off."""
    found: list[tuple[type, Any]] = []
    for rel in sa_inspect(model).relationships:
        target = rel.mapper.class_
        if (
            "delete" not in rel.cascade
            or rel.direction is not RelationshipDirection.ONETOMANY
            or target in SOFT_DELETE_MODELS
        ):
            continue
        for local, remote in rel.local_remote_pairs or ():
            if local.name != "id":  # pragma: no cover — every one keys on the id
                raise RuntimeError(f"{model.__name__}.{rel.key} is not keyed on id")
            found.append((target, remote))
    return tuple(found)


async def delete_rows(session: AsyncSession, model: type, ids: Sequence[int]) -> None:
    """Delete these rows of ``model`` and what their relationships own."""
    for target, key in _orm_dependents(model):
        await session.exec(
            delete(target)  # type: ignore[call-overload]
            .where(ids_in(key, ids))
            .execution_options(synchronize_session=False)
        )
    await session.exec(
        delete(model)  # type: ignore[call-overload]
        .where(ids_in(model.id, ids))  # type: ignore[attr-defined]
        .execution_options(synchronize_session="fetch")
    )
