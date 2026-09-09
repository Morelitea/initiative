"""A gallery's realtime signals — a picture reaches a second window on its own.

End to end, like the board's: a real endpoint writes, the capture trigger logs
it, the room sink reads the log, and a socket in that initiative's room hears
about it. A picture has no route of its own, so every change to one — adding,
retitling, retagging, removing — reports as the gallery it is in, which is what
a wall re-reads.
"""

import io

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.services.realtime import manager
from app.services.realtime_test import FakeWebSocket
from app.services.tenant import room_sink
from app.testing import create_gallery, create_gallery_image, create_tag, png_bytes

pytestmark = pytest.mark.integration


async def _galleries_enabled(session: AsyncSession, initiative) -> None:
    initiative.galleries_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


class _Room:
    def __init__(self, guild_id: int, initiative_id: int, user_id: int = 1) -> None:
        self._guild_id = guild_id
        self._initiative_id = initiative_id
        self._user_id = user_id
        self.socket = FakeWebSocket()

    async def __aenter__(self) -> "_Room":
        await manager.connect(
            self._guild_id, [self._initiative_id], self.socket, user_id=self._user_id
        )
        await room_sink.process_room_sweep()
        return self

    async def __aexit__(self, *exc) -> None:
        await manager.disconnect(self.socket)
        room_sink._delivered.pop(self._guild_id, None)

    async def catch_up(self) -> None:
        await room_sink.process_room_sweep()

    def changes(self, resource_type: str = "galleries") -> list[dict]:
        return [
            change
            for frame in self.socket.sent
            for change in frame.get("changes", [])
            if change["resource"]["type"] == resource_type
        ]


@pytest.mark.asyncio
async def test_a_picture_arriving_tells_the_room_about_its_gallery(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)

    async with _Room(a.guild.id, a.initiative.id) as room:
        response = await client.post(
            a.g(f"/galleries/{gallery.id}/images"),
            headers=a.headers,
            files={"file": ("shot.png", io.BytesIO(png_bytes()), "image/png")},
        )
        assert response.status_code == 201, response.text
        await room.catch_up()

        changes = room.changes()
        assert changes, "the room heard nothing"
        # The picture reports as its gallery: that is the address a wall
        # re-reads, and the picture itself is not on the bus.
        assert all(
            c["resource"] == {"type": "galleries", "id": gallery.id} for c in changes
        )
        assert all(set(c) == {"resource", "parents", "action"} for c in changes)


@pytest.mark.asyncio
async def test_retagging_and_removing_a_picture_each_tell_the_room(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)
    image = await create_gallery_image(session, gallery, a.user, write_blob=False)
    tag = await create_tag(session, a.guild, name="picked")

    async with _Room(a.guild.id, a.initiative.id) as room:
        retagged = await client.patch(
            a.g(f"/galleries/{gallery.id}/images/{image.id}"),
            headers=a.headers,
            json={"tag_ids": [tag.id], "title": "Hero"},
        )
        assert retagged.status_code == 200, retagged.text
        await room.catch_up()
        assert room.changes(), "retagging said nothing"
        heard = len(room.changes())

        removed = await client.delete(
            a.g(f"/galleries/{gallery.id}/images/{image.id}"), headers=a.headers
        )
        assert removed.status_code == 204
        await room.catch_up()
        assert len(room.changes()) > heard, "removing said nothing"
        assert all(
            c["resource"] == {"type": "galleries", "id": gallery.id}
            for c in room.changes()
        )


@pytest.mark.asyncio
async def test_a_comment_on_a_gallery_names_it_as_the_parent(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)

    async with _Room(a.guild.id, a.initiative.id) as room:
        response = await client.post(
            a.g("/comments/"),
            headers=a.headers,
            json={"gallery_id": gallery.id, "content": "The blue one."},
        )
        assert response.status_code == 201, response.text
        await room.catch_up()

        comments = room.changes("comments")
        assert comments, "the room heard no comment"
        assert all(
            {"type": "galleries", "id": gallery.id} in c["parents"] for c in comments
        )
