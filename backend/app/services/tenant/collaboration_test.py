"""Unit tests for the collaboration room registry.

The rooms themselves are exercised through the WebSocket endpoint; what is
covered here is how they are *addressed*. Document ids are per-guild-schema
sequences, so the id alone does not name a document and the registry key has to
carry the guild with it.
"""

import asyncio

import pytest

from app.services.tenant.collaboration import CollaborationManager, DocumentRoom


class FakeResult:
    def __init__(self, value):
        self._value = value

    def one_or_none(self):
        return self._value


class SlowSession:
    """A session whose read takes as long as the test says it does.

    Standing in for the database lets a test say what the registry does *while*
    a room is being read in, which is the whole point of doing that read outside
    the registry's lock.
    """

    def __init__(self, document=None, delay: float = 0.05):
        self.document = document
        self.delay = delay
        self.reads = 0

    async def exec(self, _statement):
        self.reads += 1
        await asyncio.sleep(self.delay)
        return FakeResult(self.document)


def loaded_room(document_id: int) -> DocumentRoom:
    """A room as it stands once its one read of the database is done."""
    room = DocumentRoom(document_id)
    room._loaded = True
    return room


@pytest.mark.unit
async def test_the_same_document_id_in_two_guilds_is_two_rooms() -> None:
    manager = CollaborationManager()
    manager._rooms[(1, 5)] = loaded_room(5)
    manager._rooms[(2, 5)] = loaded_room(5)

    first = manager.get_room(1, 5)
    second = manager.get_room(2, 5)

    assert first is not None
    assert second is not None
    assert first is not second
    assert manager.get_active_rooms() == {(1, 5), (2, 5)}


@pytest.mark.unit
async def test_a_room_is_reached_only_from_its_own_guild() -> None:
    manager = CollaborationManager()
    manager._rooms[(1, 5)] = loaded_room(5)

    assert manager.get_room(1, 5) is not None
    assert manager.get_room(2, 5) is None
    assert manager.has_active_collaborators(2, 5) is False


@pytest.mark.unit
async def test_removing_a_room_leaves_the_other_guild_alone() -> None:
    manager = CollaborationManager()
    manager._rooms[(1, 5)] = loaded_room(5)
    manager._rooms[(2, 5)] = loaded_room(5)

    # Both are empty of collaborators, so both are removable — only the one
    # named should go.
    await manager.remove_room(1, 5)

    assert manager.get_room(1, 5) is None
    assert manager.get_room(2, 5) is not None


@pytest.mark.unit
async def test_invalidating_a_room_leaves_the_other_guild_alone() -> None:
    manager = CollaborationManager()
    manager._rooms[(1, 5)] = loaded_room(5)
    manager._rooms[(2, 5)] = loaded_room(5)

    assert await manager.invalidate_room_if_empty(1, 5) is True

    assert manager.get_room(1, 5) is None
    assert manager.get_room(2, 5) is not None


@pytest.mark.unit
async def test_loading_one_room_does_not_stall_another() -> None:
    """The registry lock is not held across the read.

    A slow document in one guild must not hold up a room in another, which is
    what a lock held across I/O would do.
    """
    manager = CollaborationManager()
    slow = SlowSession(delay=0.2)
    quick = SlowSession(delay=0.0)

    async def open_slow():
        await manager.get_or_create_room(1, 5, slow)

    slow_task = asyncio.create_task(open_slow())
    await asyncio.sleep(0.01)  # let it get as far as the read

    # While that one is still reading, another room opens and returns.
    await asyncio.wait_for(manager.get_or_create_room(2, 9, quick), timeout=0.1)

    await slow_task
    assert manager.get_active_rooms() == {(1, 5), (2, 9)}


@pytest.mark.unit
async def test_a_room_is_read_once_however_many_arrive_together() -> None:
    """Two callers on the same new room make one read between them."""
    manager = CollaborationManager()
    session = SlowSession(delay=0.05)

    first, second = await asyncio.gather(
        manager.get_or_create_room(1, 5, session),
        manager.get_or_create_room(1, 5, session),
    )

    assert first is second
    assert session.reads == 1
    # And a later arrival does not read again.
    await manager.get_or_create_room(1, 5, session)
    assert session.reads == 1


@pytest.mark.unit
async def test_a_room_being_read_in_is_not_collected_as_idle() -> None:
    """An unread room is empty because nobody has arrived, not because they left."""
    manager = CollaborationManager()
    slow = SlowSession(delay=0.2)

    opening = asyncio.create_task(manager.get_or_create_room(1, 5, slow))
    await asyncio.sleep(0.01)

    await manager.remove_room(1, 5)
    assert await manager.invalidate_room_if_empty(1, 5) is False
    assert manager.get_room(1, 5) is not None

    room = await opening
    assert room is manager.get_room(1, 5)

    # Once it has been read in, an empty room is collectable as before.
    assert await manager.invalidate_room_if_empty(1, 5) is True
    assert manager.get_room(1, 5) is None
