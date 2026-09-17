"""A challenge stands until it is spent, expires, or runs out of attempts."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.auth import challenges
from app.testing import create_user

pytestmark = pytest.mark.database

FIXED_NOW = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
PURPOSE = challenges.ChallengePurpose.sign_in


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(challenges, "_now", lambda: FIXED_NOW)
    return FIXED_NOW


async def _open(session: AsyncSession, user_id: int) -> challenges.IssuedChallenge:
    issued = await challenges.create(session, user_id=user_id, purpose=PURPOSE)
    await session.commit()
    return issued


async def test_the_value_resolves_to_the_challenge(session: AsyncSession, frozen):
    user = await create_user(session)
    issued = await _open(session, user.id)

    found = await challenges.resolve(session, value=issued.value, purpose=PURPOSE)
    assert found is not None
    assert found.user_id == user.id


async def test_a_value_nobody_issued_resolves_to_nothing(session: AsyncSession, frozen):
    await create_user(session)
    assert (
        await challenges.resolve(session, value="not-a-challenge", purpose=PURPOSE)
        is None
    )


async def test_the_raw_value_is_not_what_is_stored(session: AsyncSession, frozen):
    user = await create_user(session)
    issued = await _open(session, user.id)
    assert issued.challenge.challenge_hash != issued.value.encode("utf-8")
    assert len(issued.challenge.challenge_hash) == 32


async def test_it_is_spent_once(session: AsyncSession, frozen):
    """Two requests answering the same challenge: one of them made the session."""
    user = await create_user(session)
    issued = await _open(session, user.id)

    assert await challenges.consume(session, issued.challenge) is True
    await session.commit()
    assert await challenges.consume(session, issued.challenge) is False


async def test_a_spent_challenge_no_longer_resolves(session: AsyncSession, frozen):
    user = await create_user(session)
    issued = await _open(session, user.id)
    await challenges.consume(session, issued.challenge)
    await session.commit()

    assert (
        await challenges.resolve(session, value=issued.value, purpose=PURPOSE) is None
    )


async def test_it_stops_standing_once_it_has_expired(
    session: AsyncSession, frozen, monkeypatch
):
    user = await create_user(session)
    issued = await _open(session, user.id)

    later = FIXED_NOW + challenges.CHALLENGE_TTL + timedelta(seconds=1)
    monkeypatch.setattr(challenges, "_now", lambda: later)
    assert (
        await challenges.resolve(session, value=issued.value, purpose=PURPOSE) is None
    )


async def test_refused_answers_are_counted_against_it(session: AsyncSession, frozen):
    user = await create_user(session)
    issued = await _open(session, user.id)

    for _ in range(challenges.MAX_ATTEMPTS):
        standing = await challenges.resolve(
            session, value=issued.value, purpose=PURPOSE
        )
        assert standing is not None
        await challenges.note_attempt(session, standing)
    await session.commit()

    assert (
        await challenges.resolve(session, value=issued.value, purpose=PURPOSE) is None
    )


async def test_they_go_when_what_they_rest_on_moves(session: AsyncSession, frozen):
    user = await create_user(session)
    first = await _open(session, user.id)
    second = await _open(session, user.id)

    assert await challenges.revoke_for_user(session, user_id=user.id) == 2
    await session.commit()

    for issued in (first, second):
        assert (
            await challenges.resolve(session, value=issued.value, purpose=PURPOSE)
            is None
        )


async def test_one_account_s_challenges_are_left_alone(session: AsyncSession, frozen):
    mine = await create_user(session)
    theirs = await create_user(session)
    ours = await _open(session, mine.id)
    await _open(session, theirs.id)

    assert await challenges.revoke_for_user(session, user_id=theirs.id) == 1
    await session.commit()
    assert (
        await challenges.resolve(session, value=ours.value, purpose=PURPOSE) is not None
    )


async def test_the_sweep_clears_what_nothing_can_use(
    session: AsyncSession, frozen, monkeypatch
):
    user = await create_user(session)
    issued = await _open(session, user.id)

    later = FIXED_NOW + challenges.CHALLENGE_TTL + timedelta(seconds=1)
    monkeypatch.setattr(challenges, "_now", lambda: later)
    assert await challenges.purge_expired(session) >= 1
    await session.commit()

    monkeypatch.setattr(challenges, "_now", lambda: FIXED_NOW)
    assert (
        await challenges.resolve(session, value=issued.value, purpose=PURPOSE) is None
    )
