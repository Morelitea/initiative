"""A wake reaches its kind's drain once the transaction that sent it commits."""

import asyncio

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services import data_jobs, guild_work
from app.services.platform import notify_bus, user_stream

pytestmark = pytest.mark.integration


async def test_a_wake_reaches_its_drain_once_committed(
    session: AsyncSession, monkeypatch
):
    sent: list[str] = []

    async def echo(_channel: str, payload: str) -> None:
        sent.append(payload)
        await guild_work.deliver(payload)

    monkeypatch.setattr(notify_bus, "notify", echo)
    monkeypatch.setattr(data_jobs.drain, "pending", set())

    guild_work.wake(session, guild_work.DATA_JOBS, 42)
    assert sent == []

    await session.commit()
    await asyncio.gather(*user_stream._inflight)

    assert sent == ["data_jobs:42"]
    assert data_jobs.drain.pending == {42}
