"""The platform settings singleton: where it comes from, and what reading it costs."""

from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.app_setting import AppSetting
from app.services.platform.app_settings import (
    GLOBAL_SETTINGS_ID,
    ensure_settings_row,
    get_app_settings,
    seed_app_settings,
)


async def _stored_ids(session: AsyncSession) -> list[int]:
    return list((await session.exec(select(AppSetting.id))).all())


async def test_seeding_creates_the_singleton(session: AsyncSession):
    """Boot is where the row comes from, and saying so twice changes nothing."""
    assert await _stored_ids(session) == []

    first = await seed_app_settings(session)
    assert first.id == GLOBAL_SETTINGS_ID
    assert await _stored_ids(session) == [GLOBAL_SETTINGS_ID]

    second = await seed_app_settings(session)
    assert second.id == GLOBAL_SETTINGS_ID
    assert await _stored_ids(session) == [GLOBAL_SETTINGS_ID]


async def test_reading_settings_before_the_seed_stores_nothing(session: AsyncSession):
    """Configuration read on a database that has no row yet answers from the env."""
    row = await get_app_settings(session)
    assert row.id == GLOBAL_SETTINGS_ID
    assert row.community_directory_enabled is False
    assert await _stored_ids(session) == []


async def test_reading_settings_leaves_the_transaction_open(session: AsyncSession):
    """A read is a read: the caller's transaction is still theirs afterwards.

    Stated as the transaction id, which is what anything held for the length of
    a transaction — a row lock, an advisory lock — is keyed on.
    """
    before = (await session.exec(text("SELECT txid_current()"))).one()

    await get_app_settings(session)
    assert (await session.exec(text("SELECT txid_current()"))).one() == before

    await seed_app_settings(session)  # the row now exists; read it again
    started = (await session.exec(text("SELECT txid_current()"))).one()
    await get_app_settings(session)
    assert (await session.exec(text("SELECT txid_current()"))).one() == started


async def test_settings_row_for_a_writer_joins_the_transaction(session: AsyncSession):
    """``ensure_settings_row`` puts the row in place without ending the caller."""
    before = (await session.exec(text("SELECT txid_current()"))).one()

    row = await ensure_settings_row(session)
    assert row.id == GLOBAL_SETTINGS_ID
    assert (await session.exec(text("SELECT txid_current()"))).one() == before

    # Still one row, and the same one, when a second caller asks.
    assert (await ensure_settings_row(session)).id == GLOBAL_SETTINGS_ID
    assert await _stored_ids(session) == [GLOBAL_SETTINGS_ID]
