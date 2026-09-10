"""Minting and resolving the references outside parties know entities by.

The table is ``public.identity_refs`` and every function here expects a session
on the **system engine** (``AdminSessionDep``) — the request-path roles hold no
grants on it.

Forward (entity -> reference) is ``ensure_ref``, which mints on first use, so a
new purpose needs no migration and no backfill: every existing user and guild
acquires a reference for it the first time one is asked for. Reverse (reference
-> entity) is ``resolve_ref``, an indexed lookup.

See ``history/opaque-identity-design.md``.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import delete, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.identity_ref import (
    REF_ENTROPY_BYTES,
    REF_MAX_LENGTH,
    IdentityEntity,
    IdentityRef,
    ref_prefix,
)

__all__ = [
    "REF_GRACE_PERIOD",
    "drop_entity_refs",
    "ensure_ref",
    "mint_ref",
    "purge_retired_refs",
    "reissue_all_refs",
    "reissue_ref",
    "resolve_ref",
]

#: How long a replaced reference keeps resolving. Long enough for the other
#: party to pick up the new value and for anything already in flight to land.
REF_GRACE_PERIOD = timedelta(days=30)


def mint_ref(entity_type: IdentityEntity, purpose: str) -> str:
    """A fresh reference. Random, and unrelated to the row it will name."""
    return (
        f"{ref_prefix(entity_type, purpose)}_{secrets.token_urlsafe(REF_ENTROPY_BYTES)}"
    )


async def ensure_ref(
    session: AsyncSession,
    *,
    entity_type: IdentityEntity,
    entity_id: int,
    purpose: str,
) -> str:
    """This entity's live reference for this purpose, minting one on first use.

    Idempotent under concurrency: two callers racing the same first mint both
    insert, one loses on the partial unique index, and both read back the same
    row.
    """
    existing = await _live_ref(
        session, entity_type=entity_type, entity_id=entity_id, purpose=purpose
    )
    if existing is not None:
        return existing.ref

    await session.exec(
        pg_insert(IdentityRef.__table__)
        .values(
            ref=mint_ref(entity_type, purpose),
            entity_type=entity_type.value,
            entity_id=entity_id,
            purpose=purpose,
            created_at=datetime.now(timezone.utc),
        )
        # A core-level insert, so the model's default factories do not run and
        # the conflict target must name the partial index's predicate.
        .on_conflict_do_nothing(
            index_elements=["entity_type", "entity_id", "purpose"],
            index_where=IdentityRef.retired_at.is_(None),
        )
    )

    # Read back rather than returning what was offered: on a lost race the
    # stored value is the winner's, and that is the one the caller must use.
    stored = await _live_ref(
        session, entity_type=entity_type, entity_id=entity_id, purpose=purpose
    )
    if stored is None:  # pragma: no cover - the insert either landed or lost
        raise RuntimeError("identity ref was neither inserted nor found")
    return stored.ref


async def resolve_ref(
    session: AsyncSession, *, ref: str, now: datetime | None = None
) -> IdentityRef | None:
    """Which entity a reference names, or None.

    A retired reference still resolves until its grace window closes; past
    that it is treated as unknown even while the row waits to be swept.
    """
    if not ref or len(ref) > REF_MAX_LENGTH:
        return None
    moment = now or datetime.now(timezone.utc)
    return (
        await session.exec(
            select(IdentityRef).where(
                IdentityRef.ref == ref,
                or_(
                    IdentityRef.retired_at.is_(None),
                    IdentityRef.retired_at > moment - REF_GRACE_PERIOD,
                ),
            )
        )
    ).first()


async def reissue_ref(
    session: AsyncSession,
    *,
    entity_type: IdentityEntity,
    entity_id: int,
    purpose: str,
    now: datetime | None = None,
) -> str:
    """Replace one entity's reference for one purpose, and return the new one.

    The old value keeps resolving for ``REF_GRACE_PERIOD``. Nothing else about
    the entity moves, and no other entity is touched.
    """
    moment = now or datetime.now(timezone.utc)
    await session.exec(
        update(IdentityRef)
        .where(
            IdentityRef.entity_type == entity_type,
            IdentityRef.entity_id == entity_id,
            IdentityRef.purpose == purpose,
            IdentityRef.retired_at.is_(None),
        )
        .values(retired_at=moment)
    )
    return await ensure_ref(
        session, entity_type=entity_type, entity_id=entity_id, purpose=purpose
    )


async def reissue_all_refs(
    session: AsyncSession,
    *,
    entity_type: IdentityEntity,
    purpose: str,
    now: datetime | None = None,
) -> int:
    """Replace every entity's reference for one purpose. Returns the count.

    The coarse lever, for a purpose whose references have to move together
    rather than one holder at a time. Resumable: retiring and re-minting are
    separate steps, so a run interrupted between them is completed by the next
    one — an entity left with no live reference gets a fresh one, and an entity
    already re-minted is skipped.
    """
    moment = now or datetime.now(timezone.utc)
    retired = await session.exec(
        update(IdentityRef)
        .where(
            IdentityRef.entity_type == entity_type,
            IdentityRef.purpose == purpose,
            IdentityRef.retired_at.is_(None),
        )
        .values(retired_at=moment)
        .returning(IdentityRef.entity_id)
    )
    entity_ids = {row for row in retired.scalars().all()}

    # Entities whose retirement landed on a previous, interrupted run.
    stranded = await session.exec(
        select(IdentityRef.entity_id)
        .where(
            IdentityRef.entity_type == entity_type,
            IdentityRef.purpose == purpose,
        )
        .group_by(IdentityRef.entity_id)
        .having(func.count().filter(IdentityRef.retired_at.is_(None)) == 0)
    )
    entity_ids.update(stranded.all())

    for entity_id in sorted(entity_ids):
        await ensure_ref(
            session, entity_type=entity_type, entity_id=entity_id, purpose=purpose
        )
    return len(entity_ids)


async def drop_entity_refs(
    session: AsyncSession, *, entity_type: IdentityEntity, entity_id: int
) -> int:
    """Remove every reference to one entity. Returns the count.

    Called when the row is erased, so that what the outside parties hold stops
    resolving to anybody.
    """
    result = await session.exec(
        delete(IdentityRef).where(
            IdentityRef.entity_type == entity_type,
            IdentityRef.entity_id == entity_id,
        )
    )
    return result.rowcount or 0


async def purge_retired_refs(
    session: AsyncSession, *, now: datetime | None = None
) -> int:
    """Drop the rows whose grace window has closed. Returns the count."""
    moment = now or datetime.now(timezone.utc)
    result = await session.exec(
        delete(IdentityRef).where(
            IdentityRef.retired_at.is_not(None),
            IdentityRef.retired_at <= moment - REF_GRACE_PERIOD,
        )
    )
    return result.rowcount or 0


async def _live_ref(
    session: AsyncSession,
    *,
    entity_type: IdentityEntity,
    entity_id: int,
    purpose: str,
) -> IdentityRef | None:
    return (
        await session.exec(
            select(IdentityRef).where(
                IdentityRef.entity_type == entity_type,
                IdentityRef.entity_id == entity_id,
                IdentityRef.purpose == purpose,
                IdentityRef.retired_at.is_(None),
            )
        )
    ).first()
