"""The account channel: who gets poked, when, and what the frame carries.

The point of the channel is that a tab learns its account changed even when
its owner did nothing — so most of these are about somebody *else's* action
reaching a socket.
"""

import asyncio

import pytest

from app.models.platform.guild import GuildRole
from app.services.platform import account_stream, user_stream
from app.services.platform import app_settings as app_settings_service
from app.services.platform import guilds as guilds_service
from app.services.platform.user_stream import UserStream
from app.testing import create_guild, create_guild_membership, create_user


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)


async def _drain_tasks() -> None:
    """Let the after-commit hook's fire-and-forget sends finish."""
    for _ in range(3):
        await asyncio.sleep(0)


@pytest.fixture
def published_remotely(monkeypatch):
    """The ids this worker handed to the bus for the other workers to deliver."""
    seen: list[int] = []

    async def _record(user_id: int, _frame) -> None:
        seen.append(user_id)

    monkeypatch.setattr(user_stream, "_publish_remote", _record)
    return seen


@pytest.fixture
def captured_stream(monkeypatch):
    """A registry of this test's own, patched where the sockets really live."""
    stream = UserStream()
    monkeypatch.setattr(user_stream, "stream", stream)
    return stream


@pytest.fixture(autouse=True)
def bus_off(monkeypatch):
    """No cross-process half in these tests.

    The bus is additive and its absence must change nothing, which is also what
    makes it safe to leave out here — the local path is what is under test.
    """

    async def _unavailable(_payload: str) -> None:
        raise RuntimeError("bus not connected")

    from app.services.platform import user_stream_bus

    monkeypatch.setattr(user_stream_bus, "notify", _unavailable)


@pytest.mark.unit
async def test_the_frame_says_nothing_about_the_account(captured_stream) -> None:
    """It names the channel and nothing else — the client re-reads to learn."""
    tab = FakeWebSocket()
    await captured_stream.connect(7, tab)

    await account_stream.signal_account(7, "membership")

    frame = tab.sent[0]
    assert frame["resource"] == "account"
    assert frame["action"] == "membership"
    assert frame["ids"] == {}
    assert set(frame) == {"resource", "action", "ids", "timestamp"}


@pytest.mark.unit
async def test_a_frame_never_reaches_another_account(captured_stream) -> None:
    mine, theirs = FakeWebSocket(), FakeWebSocket()
    await captured_stream.connect(7, mine)
    await captured_stream.connect(8, theirs)

    await account_stream.signal_account(7)

    assert len(mine.sent) == 1
    assert theirs.sent == []


@pytest.mark.integration
async def test_no_frame_before_the_commit(session, captured_stream) -> None:
    """A tab told to re-read before the COMMIT reads the state being replaced."""
    user = await create_user(session)
    tab = FakeWebSocket()
    await captured_stream.connect(user.id, tab)

    account_stream.queue_account_signal(session, user.id, "membership")
    await _drain_tasks()

    assert tab.sent == []


@pytest.mark.integration
async def test_rollback_pokes_nobody(session, captured_stream) -> None:
    user = await create_user(session)
    tab = FakeWebSocket()
    await captured_stream.connect(user.id, tab)

    account_stream.queue_account_signal(session, user.id, "membership")
    await session.rollback()
    await _drain_tasks()

    assert tab.sent == []


@pytest.mark.integration
async def test_one_frame_per_channel_per_transaction(session, captured_stream) -> None:
    """Three reasons to re-read one account is still one refetch."""
    user = await create_user(session)
    tab = FakeWebSocket()
    await captured_stream.connect(user.id, tab)

    for reason in ("membership", "role", "community"):
        account_stream.queue_account_signal(session, user.id, reason)
    await session.commit()
    await _drain_tasks()

    assert len(tab.sent) == 1


@pytest.mark.integration
async def test_the_inbox_and_the_account_are_not_the_same_frame(
    session, captured_stream
) -> None:
    """Two channels over one socket: one must not swallow the other."""
    from app.services.platform import notification_stream

    user = await create_user(session)
    tab = FakeWebSocket()
    await captured_stream.connect(user.id, tab)

    account_stream.queue_account_signal(session, user.id, "membership")
    notification_stream.queue_signal(session, user.id, "created")
    await session.commit()
    await _drain_tasks()

    assert {frame["resource"] for frame in tab.sent} == {"account", "notification"}


@pytest.mark.integration
async def test_being_added_to_a_guild_pokes_the_arrival(
    session, captured_stream
) -> None:
    """The case this channel exists for: somebody else put them there."""
    user = await create_user(session)
    guild = await create_guild(session)
    tab = FakeWebSocket()
    await captured_stream.connect(user.id, tab)

    await guilds_service.ensure_membership(
        session, guild_id=guild.id, user_id=user.id, role=GuildRole.member
    )
    await session.commit()
    await _drain_tasks()

    assert [frame["resource"] for frame in tab.sent] == ["account"]


@pytest.mark.integration
async def test_re_adding_an_existing_member_pokes_nobody(
    session, captured_stream
) -> None:
    """Nothing changed, so there is nothing to re-read."""
    user = await create_user(session)
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)
    await session.commit()
    tab = FakeWebSocket()
    await captured_stream.connect(user.id, tab)

    await guilds_service.ensure_membership(
        session, guild_id=guild.id, user_id=user.id, role=GuildRole.member
    )
    await session.commit()
    await _drain_tasks()

    assert tab.sent == []


@pytest.mark.integration
async def test_listing_a_community_pokes_every_member(
    session, captured_stream, published_remotely
) -> None:
    """The fan-out: nobody in the guild did anything, and it changes them all.

    Addressed to the whole roster rather than to the sockets this process is
    holding. A member sitting on another worker has no socket *here*, and the
    frame that reaches them is the one this worker puts on the bus — so a
    roster narrowed by local sockets first would be deciding, from one
    process, that everybody else is absent.
    """
    here = await create_user(session)
    away = await create_user(session)
    guild = await create_guild(session)
    await create_guild_membership(session, user=here, guild=guild)
    await create_guild_membership(session, user=away, guild=guild)
    await session.commit()

    # The directory is a platform-owner switch and starts off, so listing a
    # community is refused until it is on.
    await app_settings_service.update_community_settings(
        session, community_directory_enabled=True
    )

    tab = FakeWebSocket()
    await captured_stream.connect(here.id, tab)

    await guilds_service.update_guild(
        session,
        guild_id=guild.id,
        name=None,
        description=None,
        retention_days=None,
        retention_days_provided=False,
        is_community=True,
        categories=["other"],
        categories_provided=True,
        has_adult_content=False,
        has_adult_content_provided=True,
    )
    await session.commit()
    await _drain_tasks()

    assert [frame["resource"] for frame in tab.sent] == ["account"]
    # And the one this worker holds nothing for: published, for whichever
    # worker does hold them. Without it their tab would sit on the old answer
    # until they navigated.
    assert away.id in published_remotely
    assert here.id in published_remotely
