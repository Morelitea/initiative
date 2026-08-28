"""Unit tests for the collaboration room registry.

The rooms themselves are exercised through the WebSocket endpoint; what is
covered here is how they are *addressed*. Document ids are per-guild-schema
sequences, so the id alone does not name a document and the registry key has to
carry the guild with it.
"""

import pytest

from app.services.tenant.collaboration import CollaborationManager, DocumentRoom


@pytest.mark.unit
async def test_the_same_document_id_in_two_guilds_is_two_rooms() -> None:
    manager = CollaborationManager()
    manager._rooms[(1, 5)] = DocumentRoom(5)
    manager._rooms[(2, 5)] = DocumentRoom(5)

    first = manager.get_room(1, 5)
    second = manager.get_room(2, 5)

    assert first is not None
    assert second is not None
    assert first is not second
    assert manager.get_active_rooms() == {(1, 5), (2, 5)}


@pytest.mark.unit
async def test_a_room_is_reached_only_from_its_own_guild() -> None:
    manager = CollaborationManager()
    manager._rooms[(1, 5)] = DocumentRoom(5)

    assert manager.get_room(1, 5) is not None
    assert manager.get_room(2, 5) is None
    assert manager.has_active_collaborators(2, 5) is False


@pytest.mark.unit
async def test_removing_a_room_leaves_the_other_guild_alone() -> None:
    manager = CollaborationManager()
    manager._rooms[(1, 5)] = DocumentRoom(5)
    manager._rooms[(2, 5)] = DocumentRoom(5)

    # Both are empty of collaborators, so both are removable — only the one
    # named should go.
    await manager.remove_room(1, 5)

    assert manager.get_room(1, 5) is None
    assert manager.get_room(2, 5) is not None


@pytest.mark.unit
async def test_invalidating_a_room_leaves_the_other_guild_alone() -> None:
    manager = CollaborationManager()
    manager._rooms[(1, 5)] = DocumentRoom(5)
    manager._rooms[(2, 5)] = DocumentRoom(5)

    assert await manager.invalidate_room_if_empty(1, 5) is True

    assert manager.get_room(1, 5) is None
    assert manager.get_room(2, 5) is not None
