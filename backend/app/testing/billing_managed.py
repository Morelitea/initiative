"""Turn the database's billing-managed answer on for one block of a test."""

from __future__ import annotations

from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.billing_managed import billing_managed_sql


@asynccontextmanager
async def billing_manages_plans(session: AsyncSession):
    """``public.billing_managed()`` answers true for the duration.

    ``session`` is the superuser fixture. The worker's database outlives the
    test, so the answer is put back whatever happens inside.
    """
    await session.exec(text(billing_managed_sql(True)))
    await session.commit()
    try:
        yield
    finally:
        await session.rollback()
        await session.exec(text(billing_managed_sql(False)))
        await session.commit()
