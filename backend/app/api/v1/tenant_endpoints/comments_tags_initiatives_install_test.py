"""Comments, tags, initiatives and property definitions, called by an
installed app on the real-role client.

Each test installs an app the way a community does (``install_app``: placed in
initiative A and not in B, granted scopes by the seat), seals an installation
token for it, and calls the routes these four routers let an app reach.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlmodel import select

from app.core.messages import AppMessages
from app.core.relationships import RelationshipType
from app.core.search import SearchEntityType
from app.models.platform.guild import GuildRole
from app.models.platform.notification import Notification
from app.models.tenant.comment import Comment
from app.models.tenant.relationship import EntityRelationship
from app.services.marketplace import app_refs
from app.testing import (
    create_comment,
    create_document,
    create_property_definition,
    create_tag,
    route_session_to_guild,
)
from app.testing.app_clients import (
    assert_names_nobody,
    install_app,
    install_headers,
    lift_person_and_guild_ids,
    share_with_members,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _cold_reference_cache():
    app_refs.forget_cached_install_refs()
    yield
    app_refs.forget_cached_install_refs()


def _g(guild_id: int, path: str) -> str:
    return f"/api/v1/c/{guild_id}{path}"


async def _open_documents(session: Any, installed: Any) -> tuple[Any, Any]:
    """A document open to A's members and one open to B's, both the seat's."""
    in_a = await create_document(
        session, installed.placed, installed.seat.user, name="Open in A"
    )
    await share_with_members(session, in_a, installed.placed.id)
    in_b = await create_document(
        session, installed.unplaced, installed.seat.user, name="Open in B"
    )
    await share_with_members(session, in_b, installed.unplaced.id)
    return in_a, in_b


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


async def test_reads_the_comments_on_what_it_can_read(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    scopes = ["comments:read", "documents:read"]
    installed = await install_app(session, acting_user, role_session, granted=scopes)
    in_a, in_b = await _open_documents(session, installed)
    on_a = await create_comment(
        session, installed.seat.user, document=in_a, content="Seen in A"
    )
    on_b = await create_comment(
        session, installed.seat.user, document=in_b, content="Seen in B"
    )
    headers = install_headers(installed, scopes)
    guild_id = installed.guild.id

    listed = await client.get(
        _g(guild_id, f"/comments/?document_id={in_a.id}"), headers=headers
    )
    assert listed.status_code == 200, listed.text
    [comment] = listed.json()
    assert comment["content"] == "Seen in A"
    assert comment["reactions"] == []
    # The author is named by the install's own reference for them.
    assert isinstance(comment["created_by"], str)
    assert comment["author"]["id"] == comment["created_by"]
    assert_names_nobody(listed.text, [installed.seat.user.id, guild_id])

    read = await client.get(_g(guild_id, f"/comments/{on_a.id}"), headers=headers)
    assert read.status_code == 200, read.text
    assert read.json()["created_by"] == comment["created_by"]
    assert_names_nobody(read.text, [installed.seat.user.id, guild_id])

    other = await client.get(
        _g(guild_id, f"/comments/?document_id={in_b.id}"), headers=headers
    )
    assert other.status_code == 404, other.text
    other_one = await client.get(_g(guild_id, f"/comments/{on_b.id}"), headers=headers)
    assert other_one.status_code == 404, other_one.text


async def test_without_the_parents_scope_the_thread_is_not_there(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["comments:read"]
    )
    in_a, _in_b = await _open_documents(session, installed)
    await create_comment(session, installed.seat.user, document=in_a)

    listed = await client.get(
        _g(installed.guild.id, f"/comments/?document_id={in_a.id}"),
        headers=install_headers(installed, ["comments:read"]),
    )
    assert listed.status_code == 404, listed.text


async def test_posting_a_comment_needs_the_write_scope(
    client, session, acting_user, role_session
):
    scopes = ["comments:read", "documents:read"]
    installed = await install_app(session, acting_user, role_session, granted=scopes)
    in_a, _in_b = await _open_documents(session, installed)

    posted = await client.post(
        _g(installed.guild.id, "/comments/"),
        headers=install_headers(installed, scopes),
        json={"content": "Hello", "document_id": in_a.id},
    )
    assert posted.status_code == 403, posted.text
    assert posted.json()["detail"] == AppMessages.SCOPE_REQUIRED


async def test_posts_as_itself_and_the_notices_name_the_app(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    scopes = ["comments:write", "documents:read"]
    installed = await install_app(session, acting_user, role_session, granted=scopes)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=installed.guild,
        initiative=installed.placed,
        initiative_role="member",
    )
    in_a, in_b = await _open_documents(session, installed)
    theirs = await create_comment(
        session, member.user, document=in_a, content="A question"
    )
    headers = install_headers(installed, scopes)
    guild_id = installed.guild.id

    posted = await client.post(
        _g(guild_id, "/comments/"),
        headers=headers,
        json={
            "content": "An answer",
            "document_id": in_a.id,
            "parent_comment_id": theirs.id,
        },
    )
    assert posted.status_code == 201, posted.text
    body = posted.json()
    assert body["created_by"] is None
    assert body["author"] is None
    assert body["parent_comment_id"] == theirs.id
    assert_names_nobody(posted.text, [installed.seat.user.id, member.user.id, guild_id])

    await route_session_to_guild(session, guild_id)
    stored = await session.get(Comment, body["id"])
    assert stored is not None and stored.created_by is None

    # The member it answered hears of the reply, and the document's owner of
    # the comment: both from the app, by its name.
    notices = (
        await session.exec(
            select(Notification).where(
                Notification.user_id.in_([member.user.id, installed.seat.user.id])
            )
        )
    ).all()
    by_person = {n.user_id: n for n in notices}
    assert by_person[member.user.id].data["replier_name"] == installed.app.name
    assert by_person[member.user.id].data["replier_id"] is None
    owner_notice = by_person[installed.seat.user.id]
    assert owner_notice.data["commenter_name"] == installed.app.name
    assert owner_notice.data["commenter_id"] is None

    elsewhere = await client.post(
        _g(guild_id, "/comments/"),
        headers=headers,
        json={"content": "Not here", "document_id": in_b.id},
    )
    assert elsewhere.status_code == 404, elsewhere.text


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------


async def test_lists_the_tags_naming_the_community_by_reference(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_app(
        session, acting_user, role_session, granted=["tags:read"]
    )
    await create_tag(session, installed.guild, name="alpha")
    await create_tag(session, installed.guild, name="beta")

    listed = await client.get(
        _g(installed.guild.id, "/tags/"),
        headers=install_headers(installed, ["tags:read"]),
    )
    assert listed.status_code == 200, listed.text
    assert [t["name"] for t in listed.json()] == ["alpha", "beta"]
    assert all(isinstance(t["guild_id"], str) for t in listed.json())
    assert_names_nobody(listed.text, [installed.seat.user.id, installed.guild.id])


async def test_tags_what_it_may_write_in_bulk(
    client, session, acting_user, role_session
):
    scopes = ["tags:write", "documents:write", "relationships:write"]
    installed = await install_app(session, acting_user, role_session, granted=scopes)
    tag = await create_tag(session, installed.guild, name="triaged")
    headers = install_headers(installed, scopes)
    guild_id = installed.guild.id

    created = await client.post(
        _g(guild_id, "/documents/"),
        headers=headers,
        json={"name": "Its own", "initiative_id": installed.placed.id},
    )
    assert created.status_code == 201, created.text
    document_id = created.json()["id"]

    tagged = await client.post(
        _g(guild_id, "/tags/bulk"),
        headers=headers,
        json={
            "target_type": "document",
            "target_ids": [document_id],
            "add_tag_ids": [tag.id],
        },
    )
    assert tagged.status_code == 200, tagged.text
    assert tagged.json() == {"updated_count": 1}

    await route_session_to_guild(session, guild_id)
    edges = (
        await session.exec(
            select(EntityRelationship).where(
                EntityRelationship.source_type == SearchEntityType.document.value,
                EntityRelationship.source_id == document_id,
                EntityRelationship.relationship_type
                == RelationshipType.tagged_with.value,
            )
        )
    ).all()
    assert [edge.target_id for edge in edges] == [tag.id]


@pytest.mark.parametrize(
    "scopes",
    [
        ["tags:write"],
        ["tags:write", "documents:write"],
        ["tags:write", "relationships:write"],
    ],
)
async def test_bulk_tagging_needs_every_scope_it_writes_under(
    client, session, acting_user, role_session, scopes
):
    installed = await install_app(session, acting_user, role_session, granted=scopes)
    tag = await create_tag(session, installed.guild, name="triaged")
    in_a, _in_b = await _open_documents(session, installed)

    tagged = await client.post(
        _g(installed.guild.id, "/tags/bulk"),
        headers=install_headers(installed, scopes),
        json={
            "target_type": "document",
            "target_ids": [in_a.id],
            "add_tag_ids": [tag.id],
        },
    )
    assert tagged.status_code == 403, tagged.text
    assert tagged.json()["detail"] == AppMessages.SCOPE_REQUIRED


async def test_bulk_tagging_with_a_read_token_is_refused(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["tags:read"]
    )
    tag = await create_tag(session, installed.guild, name="triaged")

    tagged = await client.post(
        _g(installed.guild.id, "/tags/bulk"),
        headers=install_headers(installed, ["tags:read"]),
        json={"target_type": "document", "target_ids": [1], "add_tag_ids": [tag.id]},
    )
    assert tagged.status_code == 403, tagged.text
    assert tagged.json()["detail"] == AppMessages.SCOPE_REQUIRED


async def test_bulk_tagging_what_it_cannot_write_is_refused(
    client, session, acting_user, role_session
):
    scopes = ["tags:write", "documents:write", "relationships:write"]
    installed = await install_app(session, acting_user, role_session, granted=scopes)
    tag = await create_tag(session, installed.guild, name="triaged")
    in_a, in_b = await _open_documents(session, installed)
    headers = install_headers(installed, scopes)

    # Open to A's members to read, which is not to write.
    readable = await client.post(
        _g(installed.guild.id, "/tags/bulk"),
        headers=headers,
        json={
            "target_type": "document",
            "target_ids": [in_a.id],
            "add_tag_ids": [tag.id],
        },
    )
    assert readable.status_code == 403, readable.text

    elsewhere = await client.post(
        _g(installed.guild.id, "/tags/bulk"),
        headers=headers,
        json={
            "target_type": "document",
            "target_ids": [in_b.id],
            "add_tag_ids": [tag.id],
        },
    )
    assert elsewhere.status_code == 404, elsewhere.text


# ---------------------------------------------------------------------------
# Initiatives
# ---------------------------------------------------------------------------


async def test_reads_the_initiatives_it_is_placed_in(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_app(
        session, acting_user, role_session, granted=["initiatives:read"]
    )
    headers = install_headers(installed, ["initiatives:read"])
    guild_id = installed.guild.id

    listed = await client.get(_g(guild_id, "/initiatives/"), headers=headers)
    assert listed.status_code == 200, listed.text
    [only] = listed.json()
    assert only["id"] == installed.placed.id
    assert isinstance(only["guild_id"], str)
    # The roster is the members scope's to read.
    assert only["members"] == []
    assert_names_nobody(listed.text, [installed.seat.user.id, guild_id])

    read = await client.get(
        _g(guild_id, f"/initiatives/{installed.placed.id}"), headers=headers
    )
    assert read.status_code == 200, read.text
    assert read.json()["name"] == installed.placed.name
    assert read.json()["members"] == []
    assert_names_nobody(read.text, [installed.seat.user.id, guild_id])

    other = await client.get(
        _g(guild_id, f"/initiatives/{installed.unplaced.id}"), headers=headers
    )
    assert other.status_code == 404, other.text

    whole_guild = await client.get(
        _g(guild_id, "/initiatives/?scope=guild"), headers=headers
    )
    assert whole_guild.status_code == 403, whole_guild.text


async def test_with_the_members_scope_the_roster_names_people_by_reference(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    scopes = ["initiatives:read", "members:read"]
    installed = await install_app(session, acting_user, role_session, granted=scopes)

    read = await client.get(
        _g(installed.guild.id, f"/initiatives/{installed.placed.id}"),
        headers=install_headers(installed, scopes),
    )
    assert read.status_code == 200, read.text
    members = read.json()["members"]
    assert len(members) == 1
    assert isinstance(members[0]["user"]["id"], str)
    assert_names_nobody(read.text, [installed.seat.user.id, installed.guild.id])


async def test_initiatives_need_the_initiatives_scope(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["comments:read"]
    )
    listed = await client.get(
        _g(installed.guild.id, "/initiatives/"),
        headers=install_headers(installed, ["comments:read"]),
    )
    assert listed.status_code == 403, listed.text
    assert listed.json()["detail"] == AppMessages.SCOPE_REQUIRED


# ---------------------------------------------------------------------------
# Property definitions
# ---------------------------------------------------------------------------


async def test_lists_the_property_definitions_of_its_initiatives(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["initiatives:read"]
    )
    await create_property_definition(session, installed.placed, name="Estimate")
    await create_property_definition(session, installed.unplaced, name="Hidden")
    headers = install_headers(installed, ["initiatives:read"])
    guild_id = installed.guild.id

    listed = await client.get(_g(guild_id, "/property-definitions/"), headers=headers)
    assert listed.status_code == 200, listed.text
    assert [d["name"] for d in listed.json()] == ["Estimate"]

    narrowed = await client.get(
        _g(guild_id, f"/property-definitions/?initiative_id={installed.unplaced.id}"),
        headers=headers,
    )
    assert narrowed.status_code == 200, narrowed.text
    assert narrowed.json() == []
