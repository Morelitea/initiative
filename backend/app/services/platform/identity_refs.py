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

from sqlalchemy import and_, exists, func, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import delete, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import Guild
from app.models.platform.identity_ref import (
    REF_ENTROPY_BYTES,
    REF_MAX_LENGTH,
    IdentityEntity,
    IdentityPurpose,
    IdentityRef,
    ref_prefix,
)

__all__ = [
    "REF_GRACE_PERIOD",
    "billing_guild_ref",
    "billing_refs",
    "billing_user_ref",
    "drop_entity_refs",
    "drop_sector_refs",
    "ensure_ref",
    "mint_ref",
    "purge_orphaned_sector_refs",
    "purge_retired_refs",
    "reissue_all_refs",
    "reissue_ref",
    "resolve_billing_guild",
    "resolve_ref",
]

#: How long a replaced reference keeps resolving. Long enough for the other
#: party to pick up the new value and for anything already in flight to land.
REF_GRACE_PERIOD = timedelta(days=30)


def mint_ref(entity_type: IdentityEntity, purpose: IdentityPurpose) -> str:
    """A fresh reference. Random, and unrelated to the row it will name."""
    return (
        f"{ref_prefix(entity_type, purpose)}_{secrets.token_urlsafe(REF_ENTROPY_BYTES)}"
    )


async def ensure_ref(
    session: AsyncSession,
    *,
    entity_type: IdentityEntity,
    entity_id: int,
    purpose: IdentityPurpose,
    sector_guild_id: int | None = None,
    sector_id: int | None = None,
) -> str:
    """This entity's live reference for this sector, minting one on first use.

    Idempotent under concurrency: two callers racing the same first mint both
    insert, one loses on the partial unique index, and both read back the same
    row.
    """
    sector = (sector_guild_id, sector_id)
    existing = await _live_ref(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        purpose=purpose,
        sector=sector,
    )
    if existing is not None:
        return existing.ref

    await session.exec(
        pg_insert(IdentityRef.__table__)
        .values(
            ref=mint_ref(entity_type, purpose),
            entity_type=entity_type.value,
            entity_id=entity_id,
            purpose=purpose.value,
            sector_guild_id=sector_guild_id,
            sector_id=sector_id,
            created_at=datetime.now(timezone.utc),
        )
        # A core-level insert, so the model's default factories do not run and
        # the conflict target must name the partial index's columns and
        # predicate.
        .on_conflict_do_nothing(
            index_elements=[
                "entity_type",
                "entity_id",
                "purpose",
                "sector_guild_id",
                "sector_id",
            ],
            index_where=IdentityRef.retired_at.is_(None),
        )
    )

    # Read back rather than returning what was offered: on a lost race the
    # stored value is the winner's, and that is the one the caller must use.
    stored = await _live_ref(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        purpose=purpose,
        sector=sector,
    )
    if stored is None:  # pragma: no cover - the insert either landed or lost
        raise RuntimeError("identity ref was neither inserted nor found")
    return stored.ref


async def billing_user_ref(*, user_id: int) -> str:
    """The reference billing knows one user by, minting on first use.

    For the people a handoff names besides the one presenting it — the
    approver of a support visit — who need the same treatment and no more.
    """
    from app.db.session import AdminSessionLocal

    async with AdminSessionLocal() as session:
        ref = await ensure_ref(
            session,
            entity_type=IdentityEntity.user,
            entity_id=user_id,
            purpose=IdentityPurpose.billing,
        )
        await session.commit()
    return ref


async def billing_guild_ref(*, guild_id: int) -> str:
    """The reference billing knows one guild by, minting on first use.

    For the paths that name a guild to billing without a person attached — the
    membership nudge, and the tests that post what billing would.
    """
    from app.db.session import AdminSessionLocal

    async with AdminSessionLocal() as session:
        ref = await ensure_ref(
            session,
            entity_type=IdentityEntity.guild,
            entity_id=guild_id,
            purpose=IdentityPurpose.billing,
        )
        await session.commit()
    return ref


async def billing_refs(*, user_id: int, guild_id: int) -> tuple[str, str]:
    """The references billing knows one user and one guild by.

    Opens a system-engine session of its own: the table is reachable only
    there (``app.db.system_grants``), while the callers are request handlers
    routed to other roles and one background task holding no session at all.
    The same pattern ``services.platform.user_tokens`` uses for its sweep.
    """
    from app.db.session import AdminSessionLocal

    purpose = IdentityPurpose.billing
    async with AdminSessionLocal() as session:
        user_ref = await ensure_ref(
            session,
            entity_type=IdentityEntity.user,
            entity_id=user_id,
            purpose=purpose,
        )
        guild_ref = await ensure_ref(
            session,
            entity_type=IdentityEntity.guild,
            entity_id=guild_id,
            purpose=purpose,
        )
        await session.commit()
    return user_ref, guild_ref


async def resolve_billing_guild(*, ref: str) -> int | None:
    """Which guild one billing reference names, or None.

    The inverse of ``billing_refs``, for the endpoints billing calls: it names
    the guild by the reference it was given, and this is where that becomes the
    row id everything inside works on. Opens a system-engine session of its own
    for the same reason ``billing_refs`` does — the callers are request
    handlers routed to other roles.

    Narrower than ``resolve_ref``: a reference minted for a user, or for
    another purpose, is not an answer to this question.
    """
    from app.db.session import AdminSessionLocal

    async with AdminSessionLocal() as session:
        row = await resolve_ref(session, ref=ref)
    if row is None:
        return None
    if (
        row.entity_type != IdentityEntity.guild
        or row.purpose != IdentityPurpose.billing
    ):
        return None
    return row.entity_id


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


def _sector_clause(sector: tuple[int | None, int | None]):
    """Match one sector, treating an unset one as a value rather than unknown."""
    guild_id, sector_id = sector
    return and_(
        IdentityRef.sector_guild_id.is_(None)
        if guild_id is None
        else IdentityRef.sector_guild_id == guild_id,
        IdentityRef.sector_id.is_(None)
        if sector_id is None
        else IdentityRef.sector_id == sector_id,
    )


async def reissue_ref(
    session: AsyncSession,
    *,
    entity_type: IdentityEntity,
    entity_id: int,
    purpose: IdentityPurpose,
    sector_guild_id: int | None = None,
    sector_id: int | None = None,
    now: datetime | None = None,
) -> str:
    """Replace one entity's reference for one sector, and return the new one.

    The old value keeps resolving for ``REF_GRACE_PERIOD``. Nothing else about
    the entity moves, and no other entity is touched.
    """
    moment = now or datetime.now(timezone.utc)
    sector = (sector_guild_id, sector_id)
    await session.exec(
        update(IdentityRef)
        .where(
            IdentityRef.entity_type == entity_type,
            IdentityRef.entity_id == entity_id,
            IdentityRef.purpose == purpose,
            IdentityRef.retired_at.is_(None),
            _sector_clause(sector),
        )
        .values(retired_at=moment)
    )
    return await ensure_ref(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        purpose=purpose,
        sector_guild_id=sector_guild_id,
        sector_id=sector_id,
    )


async def reissue_all_refs(
    session: AsyncSession,
    *,
    entity_type: IdentityEntity,
    purpose: IdentityPurpose,
    sector_guild_id: int | None = None,
    sector_id: int | None = None,
    now: datetime | None = None,
) -> int:
    """Replace every entity's reference for one sector. Returns the count.

    The coarse lever, for references that have to move together rather than one
    holder at a time. Resumable: retiring and re-minting are separate steps, so
    a run interrupted between them is completed by the next one — an entity left
    with no live reference gets a fresh one, and an entity already re-minted is
    skipped.
    """
    moment = now or datetime.now(timezone.utc)
    sector = (sector_guild_id, sector_id)
    retired = await session.exec(
        update(IdentityRef)
        .where(
            IdentityRef.entity_type == entity_type,
            IdentityRef.purpose == purpose,
            IdentityRef.retired_at.is_(None),
            _sector_clause(sector),
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
            _sector_clause(sector),
        )
        .group_by(IdentityRef.entity_id)
        .having(func.count().filter(IdentityRef.retired_at.is_(None)) == 0)
    )
    entity_ids.update(stranded.all())

    for entity_id in sorted(entity_ids):
        await ensure_ref(
            session,
            entity_type=entity_type,
            entity_id=entity_id,
            purpose=purpose,
            sector_guild_id=sector_guild_id,
            sector_id=sector_id,
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


async def drop_sector_refs(
    session: AsyncSession, *, sector_guild_id: int, sector_id: int | None = None
) -> int:
    """Remove every reference minted for one sector. Returns the count.

    ``sector_id`` omitted takes the whole guild's sectors, which is what guild
    deletion needs. Neither column is a foreign key — the thing a sector names
    lives in a guild schema and this table does not — so this stands in for the
    cascade.
    """
    clause = IdentityRef.sector_guild_id == sector_guild_id
    if sector_id is not None:
        clause = and_(clause, IdentityRef.sector_id == sector_id)
    result = await session.exec(delete(IdentityRef).where(clause))
    return result.rowcount or 0


async def purge_orphaned_sector_refs(session: AsyncSession) -> int:
    """Drop references whose sector guild no longer exists. Returns the count.

    The sector columns cannot be foreign keys, so a guild's references are
    removed by the deletion path rather than by a cascade. This reclaims the
    ones that path did not manage to remove — it runs after the deletion has
    committed, where there is nothing left to roll back.
    """
    result = await session.exec(
        delete(IdentityRef).where(
            IdentityRef.sector_guild_id.is_not(None),
            ~exists(select(Guild.id).where(Guild.id == IdentityRef.sector_guild_id)),
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
    purpose: IdentityPurpose,
    sector: tuple[int | None, int | None],
) -> IdentityRef | None:
    return (
        await session.exec(
            select(IdentityRef).where(
                IdentityRef.entity_type == entity_type,
                IdentityRef.entity_id == entity_id,
                IdentityRef.purpose == purpose,
                IdentityRef.retired_at.is_(None),
                _sector_clause(sector),
            )
        )
    ).first()
