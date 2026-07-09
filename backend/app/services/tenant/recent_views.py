"""Service layer for the polymorphic recent-items bar.

Handles upserting, clearing, and reading entries in the ``recent_views``
table that powers the layout header's tabs across projects, documents,
queues, and counter groups.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Sequence

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tenant.recent_view import RecentView
from app.schemas.tenant.recent_view import RecentEntityType

__all__ = ["RecentEntityType"]  # re-export for existing importers

# Per-user cap on entries kept/displayed, across all entity types. The user's
# ``recent_tabs_limit`` (Interface settings) drives the actual value; these
# bound it. ``DEFAULT_RECENT_VIEWS`` preserves the historic behavior for users
# who never touched the setting.
MIN_RECENT_VIEWS = 1
MAX_RECENT_VIEWS = 100
DEFAULT_RECENT_VIEWS = 20


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
    entity_type: RecentEntityType,
    entity_id: int,
    persist: bool = True,
    limit: int | None = None,
) -> RecentView:
    """Upsert a recent-view row, then prune per-user to the user's cap.

    The DB trigger ``fn_recent_views_set_guild_id`` populates ``guild_id``
    from the underlying entity, so callers don't pass it.

    ``persist=False`` returns a transient (unsaved) row instead of writing.
    PAM grantees have no ``current_guild_id``, so the recent_views guild
    policies would reject their INSERT; their browsing is also transient by
    design, so we simply don't record it.
    """
    cap = clamp_recent_limit(limit)
    now = datetime.now(timezone.utc)
    if not persist:
        return RecentView(
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            last_viewed_at=now,
        )
    stmt = (
        pg_insert(RecentView)
        .values(
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            last_viewed_at=now,
        )
        .on_conflict_do_update(
            index_elements=["user_id", "entity_type", "entity_id"],
            set_={"last_viewed_at": now},
        )
    )
    await session.exec(stmt)
    await session.commit()

    fetch = select(RecentView).where(
        RecentView.user_id == user_id,
        RecentView.entity_type == entity_type,
        RecentView.entity_id == entity_id,
    )
    record = (await session.exec(fetch)).one()

    # Prune anything beyond the cap (oldest by last_viewed_at).
    prune_stmt = (
        select(RecentView)
        .where(RecentView.user_id == user_id)
        .order_by(RecentView.last_viewed_at.desc())
        .offset(cap)
    )
    stale = (await session.exec(prune_stmt)).all()
    if stale:
        for row in stale:
            await session.delete(row)
        await session.commit()

    return record


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


async def list_recent_views(
    session: AsyncSession,
    *,
    user_id: int,
    limit: int = DEFAULT_RECENT_VIEWS,
) -> Sequence[RecentView]:
    """Return the user's most recent N rows, ordered by ``last_viewed_at`` desc.

    ``recent_views`` lives in the active guild's schema, so the search_path
    already scopes rows to that guild — no guild_id filter is needed (and the
    column isn't populated in-schema, since its denormalization trigger is a
    public-table artifact).
    """
    stmt = (
        select(RecentView)
        .where(RecentView.user_id == user_id)
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
