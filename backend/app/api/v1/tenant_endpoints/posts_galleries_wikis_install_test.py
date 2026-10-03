"""Posts, galleries and wikis as an installed app calls them.

Each test installs an app the way a community does (``install_app``: placed in
initiative A and not in B, granted scopes by the seat), seals an installation
token for it, and calls the routes of these three tools that name a scope: the
list, read, create and update, a post's pin, a wiki's pages and a gallery's
pictures.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import pytest
from sqlmodel import select

from app.core.messages import AppMessages
from app.main import app_openapi
from app.models.tenant.post import Post
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.testing import (
    create_resource_grant,
    guild_url,
    create_gallery,
    create_gallery_image,
    create_post,
    create_post_poll,
    create_wiki,
    create_wiki_page,
    guild_of,
    route_session_to_guild,
)
from app.testing.app_clients import (
    assert_names_nobody,
    install_app,
    install_headers,
    lift_person_and_guild_ids,
)


@dataclass(frozen=True)
class _Tool:
    """What the tests below vary per tool."""

    plural: str
    #: What a grant on one calls it.
    resource_type: str
    #: The initiative's switch for the tool.
    switch: str
    #: Makes one open to its initiative's members, as its seat.
    make: Callable[..., Awaitable[Any]]
    #: A change the tool's PATCH takes, and the field it shows up in.
    patch: dict[str, Any]


TOOLS = [
    _Tool("posts", "post", "posts_enabled", create_post, {"name": "Renamed"}),
    _Tool(
        "galleries", "gallery", "galleries_enabled", create_gallery, {"name": "Renamed"}
    ),
    _Tool("wikis", "wiki", "wikis_enabled", create_wiki, {"name": "Renamed"}),
]


async def _switch_on(session: Any, tool: _Tool, *initiatives: Any) -> None:
    """Turn ``tool`` on in each of ``initiatives``."""
    await route_session_to_guild(session, guild_of(initiatives[0]))
    for initiative in initiatives:
        setattr(initiative, tool.switch, True)
        session.add(initiative)
    await session.commit()


# ---------------------------------------------------------------------------
# Reach
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool", TOOLS, ids=[t.plural for t in TOOLS])
async def test_reads_what_is_open_to_its_initiative(
    tool, client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_app(
        session, acting_user, role_session, granted=[f"{tool.plural}:read"]
    )
    seat = installed.seat
    guild_id = installed.guild.id
    await _switch_on(session, tool, installed.placed, installed.unplaced)
    # Both are open to their initiative's members (the factory's default).
    in_a = await tool.make(session, installed.placed, seat.user, name="In A")
    in_b = await tool.make(session, installed.unplaced, seat.user, name="In B")
    headers = install_headers(installed, [f"{tool.plural}:read"])

    listed = await client.get(guild_url(guild_id, f"/{tool.plural}/"), headers=headers)
    assert listed.status_code == 200, listed.text
    assert [row["name"] for row in listed.json()["items"]] == ["In A"]
    assert_names_nobody(listed.text, [seat.user.id, guild_id])

    read = await client.get(
        guild_url(guild_id, f"/{tool.plural}/{in_a.id}"), headers=headers
    )
    assert read.status_code == 200, read.text
    body = read.json()
    assert body["name"] == "In A"
    assert body["can"]["edit"] is False
    # The seat is named by this install's reference, and the community by its
    # own.
    assert isinstance(body["created_by"], str)
    assert isinstance(body["guild_id"], str)
    assert listed.json()["items"][0]["created_by"] == body["created_by"]
    assert_names_nobody(read.text, [seat.user.id, guild_id])

    other = await client.get(
        guild_url(guild_id, f"/{tool.plural}/{in_b.id}"), headers=headers
    )
    assert other.status_code == 404, other.text

    # A person reading the same row is served row ids, as always.
    person = await client.get(
        guild_url(guild_id, f"/{tool.plural}/{in_a.id}"), headers=seat.headers
    )
    assert person.status_code == 200, person.text
    assert person.json()["created_by"] == seat.user.id
    assert person.json()["guild_id"] == guild_id


async def test_a_post_it_reads_carries_no_one_s_own_state(
    client, session, acting_user, role_session
):
    """Reactions, read markers and ballots are people's own rows, so a post an
    installed app reads carries the empty form of each."""
    await lift_person_and_guild_ids(session)
    installed = await install_app(
        session, acting_user, role_session, granted=["posts:read"]
    )
    seat = installed.seat
    guild_id = installed.guild.id
    await _switch_on(session, TOOLS[0], installed.placed)
    post = await create_post(session, installed.placed, seat.user, name="Asks")
    await create_post_poll(session, post)
    headers = install_headers(installed, ["posts:read"])

    for path in ("/posts/", f"/posts/{post.id}", "/posts/?unread=true"):
        response = await client.get(guild_url(guild_id, path), headers=headers)
        assert response.status_code == 200, (path, response.text)
        body = response.json()
        row = body["items"][0] if "items" in body else body
        assert row["name"] == "Asks"
        assert row["is_read"] is False
        assert row["read_count"] == 0
        assert row["reactions"] == []
        assert row["poll"]["options"][0]["text"] == "Tuesday"
        assert_names_nobody(response.text, [seat.user.id, guild_id])


async def test_lists_a_wiki_s_pages_with_the_read_scope(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_app(
        session, acting_user, role_session, granted=["wikis:read"]
    )
    seat = installed.seat
    guild_id = installed.guild.id
    await _switch_on(session, TOOLS[2], installed.placed)
    wiki = await create_wiki(session, installed.placed, seat.user)
    await create_wiki_page(session, wiki, seat.user, title="Start here")
    path = guild_url(guild_id, f"/wikis/{wiki.id}/pages")

    listed = await client.get(path, headers=install_headers(installed, ["wikis:read"]))
    assert listed.status_code == 200, listed.text
    (page,) = listed.json()["items"]
    assert page["title"] == "Start here"
    assert isinstance(page["created_by"], str)
    assert_names_nobody(listed.text, [seat.user.id, guild_id])

    refused = await client.get(
        path, headers=install_headers(installed, ["galleries:read"])
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == AppMessages.SCOPE_REQUIRED


async def test_lists_a_gallery_s_pictures_with_the_read_scope(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_app(
        session, acting_user, role_session, granted=["galleries:read"]
    )
    seat = installed.seat
    guild_id = installed.guild.id
    await _switch_on(session, TOOLS[1], installed.placed)
    gallery = await create_gallery(session, installed.placed, seat.user)
    await create_gallery_image(
        session, gallery, seat.user, title="Harbour", write_blob=False
    )
    path = guild_url(guild_id, f"/galleries/{gallery.id}/images")

    listed = await client.get(
        path, headers=install_headers(installed, ["galleries:read"])
    )
    assert listed.status_code == 200, listed.text
    (image,) = listed.json()["items"]
    assert image["title"] == "Harbour"
    assert isinstance(image["created_by"], str)
    assert isinstance(image["guild_id"], str)
    assert isinstance(image["uploader"]["id"], str)
    # A picture's URLs are paths on the community's upload route, which name
    # the community; everything else names nobody.
    assert image.pop("file_url").startswith(f"/uploads/{guild_id}/")
    image.pop("thumbnail_url")
    assert_names_nobody(str(image), [seat.user.id, guild_id])

    refused = await client.get(path, headers=install_headers(installed, ["wikis:read"]))
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == AppMessages.SCOPE_REQUIRED


def test_the_app_document_lists_a_wiki_s_pages_and_a_gallery_s_pictures():
    operations = {
        operation["operationId"]: operation
        for item in app_openapi()["paths"].values()
        for operation in item.values()
    }
    assert operations["list_wiki_pages"]["x-app-scope"] == "wikis:read"
    assert operations["list_gallery_images"]["x-app-scope"] == "galleries:read"


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool", TOOLS, ids=[t.plural for t in TOOLS])
async def test_changing_anything_needs_the_write_scope(
    tool, client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=[f"{tool.plural}:read"]
    )
    seat = installed.seat
    guild_id = installed.guild.id
    await _switch_on(session, tool, installed.placed)
    row = await tool.make(session, installed.placed, seat.user, name="Theirs")
    headers = install_headers(installed, [f"{tool.plural}:read"])

    attempts = [
        (
            "POST",
            f"/{tool.plural}/",
            {"name": "New", "initiative_id": seat.initiative.id},
        ),
        ("PATCH", f"/{tool.plural}/{row.id}", tool.patch),
    ]
    if tool.plural == "posts":
        attempts.append(("PUT", f"/posts/{row.id}/pin", {"pinned": True}))
    for method, path, payload in attempts:
        response = await client.request(
            method, guild_url(guild_id, path), headers=headers, json=payload
        )
        assert response.status_code == 403, (method, path, response.text)
        assert response.json()["detail"] == AppMessages.SCOPE_REQUIRED


@pytest.mark.parametrize("tool", TOOLS, ids=[t.plural for t in TOOLS])
async def test_what_it_creates_is_its_own(
    tool, client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_app(
        session, acting_user, role_session, granted=[f"{tool.plural}:write"]
    )
    seat = installed.seat
    guild_id = installed.guild.id
    await _switch_on(session, tool, installed.placed)
    headers = install_headers(installed, [f"{tool.plural}:write"])
    create = {"name": "Made by the app", "initiative_id": installed.placed.id}

    # It shares nothing: an explicit grant list is refused.
    shared = await client.post(
        guild_url(guild_id, f"/{tool.plural}/"),
        headers=headers,
        json={**create, "grants": [{"all_initiative_members": True, "level": "read"}]},
    )
    assert shared.status_code == 403, shared.text
    assert shared.json()["detail"] == AppMessages.SHARING_NOT_AVAILABLE

    created = await client.post(
        guild_url(guild_id, f"/{tool.plural}/"), headers=headers, json=create
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["created_by"] is None
    assert isinstance(body["guild_id"], str)
    assert body["can"]["delete"] is True
    assert_names_nobody(created.text, [seat.user.id, guild_id])

    await route_session_to_guild(session, guild_id)
    grants = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == tool.resource_type,
                ResourceGrant.resource_id == body["id"],
            )
        )
    ).all()
    assert [(g.level, g.app_install_id, g.user_id) for g in grants] == [
        (ResourceAccessLevel.owner, installed.app.id, None)
    ]

    updated = await client.patch(
        guild_url(guild_id, f"/{tool.plural}/{body['id']}"),
        headers=headers,
        json=tool.patch,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Renamed"
    assert_names_nobody(updated.text, [seat.user.id, guild_id])


async def test_pins_the_posts_it_may_write(client, session, acting_user, role_session):
    await lift_person_and_guild_ids(session)
    installed = await install_app(
        session, acting_user, role_session, granted=["posts:write"]
    )
    seat = installed.seat
    guild_id = installed.guild.id
    await _switch_on(session, TOOLS[0], installed.placed)
    headers = install_headers(installed, ["posts:write"])

    created = await client.post(
        guild_url(guild_id, "/posts/"),
        headers=headers,
        json={"name": "Notice", "initiative_id": installed.placed.id},
    )
    assert created.status_code == 201, created.text
    own_id = created.json()["id"]

    pinned = await client.put(
        guild_url(guild_id, f"/posts/{own_id}/pin"),
        headers=headers,
        json={"pinned": True},
    )
    assert pinned.status_code == 200, pinned.text
    assert pinned.json()["is_pinned"] is True
    assert pinned.json()["pinned_by"] is None
    assert_names_nobody(pinned.text, [seat.user.id, guild_id])

    # One of the seat's, open to A's members at read: it reads it, and does
    # not pin it.
    theirs = await create_post(session, installed.placed, seat.user, name="Theirs")
    refused = await client.put(
        guild_url(guild_id, f"/posts/{theirs.id}/pin"),
        headers=headers,
        json={"pinned": True},
    )
    assert refused.status_code == 403, refused.text

    # Shared with the app at write, it does.
    await create_resource_grant(
        session,
        theirs,
        app_install_id=installed.app.id,
        level=ResourceAccessLevel.write,
    )
    allowed = await client.put(
        guild_url(guild_id, f"/posts/{theirs.id}/pin"),
        headers=headers,
        json={"pinned": True},
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["is_pinned"] is True
    assert isinstance(allowed.json()["created_by"], str)
    assert_names_nobody(allowed.text, [seat.user.id, guild_id])

    await route_session_to_guild(session, guild_id)
    row = await session.get(Post, theirs.id, populate_existing=True)
    assert row is not None and row.pinned_at is not None and row.pinned_by is None
