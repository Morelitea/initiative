"""Service layer for ``recent_views``: what each person opened, and when.

Opening any tool, or anything inside one, records a row. The tools' rows are
the layout header's tabs. Every row is kept for :data:`WINDOW`; past it, a tool
is kept while it is among the person's newest tabs, and anything else goes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterable, Sequence

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tenant.recent_view import RECENT_TAB_TYPES, RecentView, ViewSource
from app.schemas.tenant.recent_view import RecentEntityType
from app.services.tenant.change_log import RETENTION

if TYPE_CHECKING:
    from app.services.tenant.expiry import Expiring

__all__ = ["RecentEntityType"]  # re-export for existing importers

# Per-user cap on entries kept/displayed, across all entity types. The user's
# ``recent_tabs_limit`` (Interface settings) drives the actual value; these
# bound it. ``DEFAULT_RECENT_VIEWS`` preserves the historic behavior for users
# who never touched the setting.
MIN_RECENT_VIEWS = 1
MAX_RECENT_VIEWS = 100
DEFAULT_RECENT_VIEWS = 20

#: How long every open is kept, tab or not: the span the change log keeps, so
#: what people opened and what they changed cover the same days.
WINDOW = RETENTION


def clamp_recent_limit(value: int | None) -> int:
    """Clamp a user's ``recent_tabs_limit`` to the allowed range.

    Falls back to ``DEFAULT_RECENT_VIEWS`` for ``None`` (legacy rows / unset).
    """
    if value is None:
        return DEFAULT_RECENT_VIEWS
    return max(MIN_RECENT_VIEWS, min(MAX_RECENT_VIEWS, value))


async def record_view(
    session: AsyncSession,
    *,
    user_id: int,
    entity_type: str,
    entity_id: int,
    source: ViewSource = ViewSource.direct,
    persist: bool = True,
) -> RecentView:
    """Upsert a recent-view row, with where this open came from. What a person
    no longer keeps goes in the hourly pass (:func:`expire`), not here.

    ``persist=False`` returns a transient (unsaved) row instead of writing.
    A PAM grantee's browsing is transient by design, so it is not recorded.
    """
    record = RecentView(
        user_id=user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        last_viewed_at=datetime.now(timezone.utc),
        source=source.value,
    )
    if not persist:
        return record
    await session.exec(
        pg_insert(RecentView)
        .values(record.model_dump())
        .on_conflict_do_update(
            index_elements=["user_id", "entity_type", "entity_id"],
            set_={"last_viewed_at": record.last_viewed_at, "source": record.source},
        )
    )
    await session.commit()
    return record


async def expire(session: AsyncSession, expiring: Expiring) -> None:
    """Drop each person's views past :data:`WINDOW`, except a tab among their
    newest ``recent_tabs_limit``. A view reopened while this runs is left: it
    no longer has the time it was ranked by."""
    users = list(expiring.tab_limits)
    await session.exec(
        text(
            """
            DELETE FROM recent_views rv
            USING (
                SELECT user_id, entity_type, entity_id, last_viewed_at,
                       entity_type = ANY (CAST(:tabs AS text[])) AS is_tab,
                       row_number() OVER (
                           PARTITION BY user_id,
                                        entity_type = ANY (CAST(:tabs AS text[]))
                           ORDER BY last_viewed_at DESC
                       ) AS n
                  FROM recent_views
            ) ranked
            LEFT JOIN unnest(CAST(:users AS integer[]), CAST(:limits AS integer[]))
                   AS chosen(user_id, tab_limit)
                   ON chosen.user_id = ranked.user_id
            WHERE rv.user_id = ranked.user_id
              AND rv.entity_type = ranked.entity_type
              AND rv.entity_id = ranked.entity_id
              AND rv.last_viewed_at = ranked.last_viewed_at
              AND rv.last_viewed_at < :cutoff
              AND (NOT ranked.is_tab
                   OR ranked.n > COALESCE(chosen.tab_limit, :default_limit))
            """
        ).bindparams(
            tabs=list(RECENT_TAB_TYPES),
            cutoff=expiring.now - WINDOW,
            users=users,
            limits=[expiring.tab_limits[user] for user in users],
            default_limit=DEFAULT_RECENT_VIEWS,
        )
    )


async def clear_view(
    session: AsyncSession,
    *,
    user_id: int,
    entity_type: RecentEntityType,
    entity_id: int,
) -> None:
    """Remove a recent-view row if it exists. Idempotent."""
    stmt = select(RecentView).where(
        RecentView.user_id == user_id,
        RecentView.entity_type == entity_type,
        RecentView.entity_id == entity_id,
    )
    record = (await session.exec(stmt)).one_or_none()
    if record is not None:
        await session.delete(record)
        await session.commit()


async def purge_for_entities(
    session: AsyncSession, entity_type: str, entity_ids: Iterable[int]
) -> None:
    """Drop everyone's recent view of these, for a purge: ``entity_id`` is a
    weak reference, so nothing carries the rows out with the entity. A row is
    its member's alone, so the platform drops them."""
    from app.db.cohorts import exec_as_system

    ids = tuple(entity_ids)
    if not ids:
        return
    await exec_as_system(
        session,
        delete(RecentView).where(  # type: ignore[arg-type]
            RecentView.entity_type == entity_type,
            RecentView.entity_id.in_(ids),  # type: ignore[attr-defined]
        ),
    )


async def purge_for_user(session: AsyncSession, user_id: int) -> None:
    """Drop a person's recent views in this community, for their leaving it.
    Whoever removes them cannot reach rows that are the person's alone, so the
    platform drops them."""
    from app.db.cohorts import exec_as_system

    await exec_as_system(
        session,
        delete(RecentView).where(RecentView.user_id == user_id),  # type: ignore[arg-type]
    )


async def list_recent_views(
    session: AsyncSession,
    *,
    user_id: int,
    limit: int = DEFAULT_RECENT_VIEWS,
) -> Sequence[RecentView]:
    """Return the user's most recent N tabs, ordered by ``last_viewed_at`` desc.

    ``recent_views`` lives in its community's schema, so the routed session
    already scopes rows to that community.
    """
    stmt = (
        select(RecentView)
        .where(
            RecentView.user_id == user_id,
            col(RecentView.entity_type).in_(RECENT_TAB_TYPES),
        )
        .order_by(RecentView.last_viewed_at.desc())
        .limit(limit)
    )
    return (await session.exec(stmt)).all()


def group_ids_by_type(
    rows: Iterable[RecentView],
) -> dict[str, list[int]]:
    """Bucket recent-view rows by ``entity_type``, preserving order."""
    out: dict[str, list[int]] = {}
    for row in rows:
        out.setdefault(row.entity_type, []).append(row.entity_id)
    return out
