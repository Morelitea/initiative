"""Work registered for a commit: when it runs, and what a rollback takes."""

import asyncio

from sqlalchemy import text

from app.db import cohorts, post_commit


async def test_a_step_runs_once_its_transaction_commits():
    ran: list[str] = []

    def step(name: str) -> post_commit.Step:
        async def record() -> None:
            await asyncio.sleep(0.01)
            ran.append(name)

        return record

    async with cohorts.system_session(None) as session:
        await session.exec(text("SELECT 1"))
        post_commit.after_commit(session, step("rolled back"))
        await session.rollback()

        await session.exec(text("SELECT 1"))
        savepoint = await session.begin_nested()
        post_commit.after_commit(session, step("savepoint rolled back"))
        await savepoint.rollback()
        savepoint = await session.begin_nested()
        post_commit.after_commit(session, step("savepoint released"))
        keyed = post_commit.after_commit(session, step("keyed"), key="once")
        assert post_commit.after_commit(session, step("again"), key="once") is keyed
        post_commit.after_commit(session, lambda: ran.append("in the commit"))
        await savepoint.commit()
        await post_commit.settle(session)
        assert ran == []

        await session.commit()
        assert ran == ["in the commit"]
        await post_commit.settle(session)
    assert sorted(ran) == ["in the commit", "keyed", "savepoint released"]


async def test_settle_all_cancels_long_work_and_waits_for_the_rest():
    finished: list[str] = []

    async def work(name: str, seconds: float) -> None:
        await asyncio.sleep(seconds)
        finished.append(name)

    post_commit.spawn(work("long", 60), cancel_on_settle=True)
    post_commit.spawn(work("short", 0.01))
    await asyncio.wait_for(post_commit.settle_all(), timeout=5)
    assert finished == ["short"]
