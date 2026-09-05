"""Tests for the post endpoints — CRUD, the board's order, pinning, and the
authorization gates (feature gate, role create gate, DAC levels).

The post-specific concerns beyond the usual tool contract are the two things
the board owns: what order notices come back in, and who may lift one above
the others.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import delete as sa_delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.models.tenant.resource_grant import ResourceGrant
from app.schemas.tenant.post import MAX_POST_TEXT_CHARS, post_excerpt
from app.testing import create_comment, create_post, lexical_body


async def _posts_enabled(session: AsyncSession, initiative) -> None:
    initiative.posts_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


async def _strip_non_owner_grants(session, post, owner_id: int) -> None:
    """Remove every grant except the owner's own — the post becomes invisible
    to other members."""
    await session.exec(
        sa_delete(ResourceGrant).where(
            ResourceGrant.resource_type == "post",
            ResourceGrant.resource_id == post.id,
            ResourceGrant.user_id.is_distinct_from(owner_id),
        )
    )
    await session.commit()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_post(client: AsyncClient, acting_user, session):
    """Posting seeds the author's owner grant plus the default all-members read
    grant — a notice nobody could read is not a notice."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)

    response = await client.post(
        a.g("/posts/"),
        headers=a.headers,
        json={
            "name": "Server maintenance Sunday",
            "initiative_id": a.initiative.id,
            "body": lexical_body("We are upgrading at 9am."),
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Server maintenance Sunday"
    assert body["my_permission_level"] == "owner"
    assert body["is_pinned"] is False
    assert body["pinned_at"] is None
    assert body["excerpt"] == "We are upgrading at 9am."


@pytest.mark.integration
async def test_create_requires_feature_enabled(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    # posts_enabled defaults to False.

    response = await client.post(
        a.g("/posts/"),
        headers=a.headers,
        json={"name": "Nope", "initiative_id": a.initiative.id},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "POSTS_NOT_ENABLED"


@pytest.mark.integration
async def test_create_requires_the_create_permission(
    client: AsyncClient, acting_user, session
):
    """A plain member cannot post to the board unless their role says so."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    response = await client.post(
        b.g("/posts/"),
        headers=b.headers,
        json={"name": "Unauthorized", "initiative_id": a.initiative.id},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "POST_CREATE_PERMISSION_REQUIRED"


@pytest.mark.integration
async def test_list_carries_bodies_and_read_matches(
    client: AsyncClient, acting_user, session
):
    """A board renders its notices, so the list carries whole posts — unlike
    every other tool list, which omits the body."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(
        session, a.initiative, a.user, name="Ops", body=lexical_body("All clear.")
    )

    listing = await client.get(a.g("/posts/"), headers=a.headers)
    assert listing.status_code == 200
    (item,) = listing.json()["items"]
    assert item["name"] == "Ops"
    assert item["body"]["root"]["children"][0]["children"][0]["text"] == "All clear."
    assert item["excerpt"] == "All clear."

    detail = await client.get(a.g(f"/posts/{post.id}"), headers=a.headers)
    assert detail.status_code == 200
    assert detail.json()["body"] == item["body"]


@pytest.mark.integration
async def test_board_pages_in_twenties_by_default(
    client: AsyncClient, acting_user, session
):
    """The default page is small on purpose: each row is a body the client
    mounts an editor for."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    for i in range(22):
        await create_post(session, a.initiative, a.user, name=f"Notice {i}")

    listing = await client.get(a.g("/posts/"), headers=a.headers)
    assert listing.status_code == 200
    payload = listing.json()
    assert payload["page_size"] == 20
    assert len(payload["items"]) == 20
    assert payload["total_count"] == 22
    assert payload["has_next"] is True


@pytest.mark.integration
async def test_a_page_larger_than_the_cap_is_refused(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)

    response = await client.get(a.g("/posts/?page_size=200"), headers=a.headers)
    assert response.status_code == 422


@pytest.mark.integration
async def test_update_post(client: AsyncClient, acting_user, session):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user, name="Draft")

    response = await client.patch(
        a.g(f"/posts/{post.id}"),
        headers=a.headers,
        json={"name": "Final", "body": lexical_body("Rewritten.")},
    )

    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Final"
    assert response.json()["excerpt"] == "Rewritten."


@pytest.mark.integration
async def test_delete_post_requires_owner(client: AsyncClient, acting_user, session):
    """A reader cannot delete somebody else's notice."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    denied = await client.delete(b.g(f"/posts/{post.id}"), headers=b.headers)
    assert denied.status_code == 403

    allowed = await client.delete(a.g(f"/posts/{post.id}"), headers=a.headers)
    assert allowed.status_code == 204


@pytest.mark.integration
async def test_a_post_not_shared_is_not_listed(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user, name="Private")
    await _strip_non_owner_grants(session, post, a.user.id)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    listing = await client.get(b.g("/posts/"), headers=b.headers)
    assert listing.status_code == 200
    assert listing.json()["items"] == []


@pytest.mark.integration
async def test_the_board_carries_each_post_s_comment_count(
    client: AsyncClient, acting_user, session
):
    """A reader sees there is a conversation without opening the post."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    talked_about = await create_post(session, a.initiative, a.user, name="Busy")
    await create_post(session, a.initiative, a.user, name="Quiet")
    await create_comment(session, a.user, post=talked_about)
    await create_comment(session, a.user, post=talked_about)

    listing = await client.get(a.g("/posts/"), headers=a.headers)
    assert listing.status_code == 200
    counts = {p["name"]: p["comment_count"] for p in listing.json()["items"]}
    assert counts == {"Busy": 2, "Quiet": 0}


@pytest.mark.integration
async def test_a_trashed_comment_leaves_the_count(
    client: AsyncClient, acting_user, session
):
    """A thread that was cleared out reads as empty, not as history."""
    from app.services.tenant.soft_delete import soft_delete_entity

    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    comment = await create_comment(session, a.user, post=post)
    await soft_delete_entity(
        session, comment, deleted_by_user_id=a.user.id, retention_days=30
    )
    await session.commit()

    detail = await client.get(a.g(f"/posts/{post.id}"), headers=a.headers)
    assert detail.status_code == 200
    assert detail.json()["comment_count"] == 0


# ---------------------------------------------------------------------------
# The board's order
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_board_orders_pins_first_then_newest(
    client: AsyncClient, acting_user, session
):
    """The default order is the board: live pins on top, then reverse
    chronological."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    old = await create_post(session, a.initiative, a.user, name="Old", created_at=base)
    await create_post(
        session, a.initiative, a.user, name="New", created_at=base + timedelta(days=2)
    )

    unpinned = await client.get(a.g("/posts/"), headers=a.headers)
    assert [p["name"] for p in unpinned.json()["items"]] == ["New", "Old"]

    pinned = await client.put(
        a.g(f"/posts/{old.id}/pin"), headers=a.headers, json={"pinned": True}
    )
    assert pinned.status_code == 200, pinned.text

    board = await client.get(a.g("/posts/"), headers=a.headers)
    assert [p["name"] for p in board.json()["items"]] == ["Old", "New"]


@pytest.mark.integration
async def test_a_lapsed_pin_falls_back_into_the_feed(
    client: AsyncClient, acting_user, session
):
    """An expiry in the past reads exactly like no pin: the post orders by its
    own age again, and nothing had to sweep the columns."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    old = await create_post(
        session,
        a.initiative,
        a.user,
        name="Old",
        created_at=base,
        pinned_at=base,
        pinned_by=a.user.id,
        pin_expires_at=base + timedelta(days=1),
    )
    await create_post(
        session, a.initiative, a.user, name="New", created_at=base + timedelta(days=2)
    )

    board = await client.get(a.g("/posts/"), headers=a.headers)
    items = board.json()["items"]
    assert [p["name"] for p in items] == ["New", "Old"]
    # The record of the pin survives; only its force has lapsed.
    lapsed = next(p for p in items if p["name"] == "Old")
    assert lapsed["is_pinned"] is False
    assert lapsed["pinned_at"] is not None
    assert lapsed["pinned_by"] == old.pinned_by


@pytest.mark.integration
async def test_sort_by_opts_out_of_the_board_order(
    client: AsyncClient, acting_user, session
):
    """The guild-wide table needs an ordinary tool sort, so naming one wins
    over the pinned band."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    await create_post(session, a.initiative, a.user, name="Beta")
    alpha = await create_post(session, a.initiative, a.user, name="Alpha")
    await client.put(
        a.g(f"/posts/{alpha.id}/pin"), headers=a.headers, json={"pinned": True}
    )

    listing = await client.get(a.g("/posts/?sort_by=name"), headers=a.headers)
    assert [p["name"] for p in listing.json()["items"]] == ["Alpha", "Beta"]


# ---------------------------------------------------------------------------
# Pinning
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_pin_requires_manager_not_write_access(
    client: AsyncClient, acting_user, session
):
    """A pin puts one notice above everyone else's, so writing your own post is
    not enough — this is initiative authority."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    # b owns the post outright and still may not pin it.
    post = await create_post(session, a.initiative, b.user)

    denied = await client.put(
        b.g(f"/posts/{post.id}/pin"), headers=b.headers, json={"pinned": True}
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "POST_PIN_MANAGER_REQUIRED"

    allowed = await client.put(
        a.g(f"/posts/{post.id}/pin"), headers=a.headers, json={"pinned": True}
    )
    assert allowed.status_code == 200
    assert allowed.json()["is_pinned"] is True
    assert allowed.json()["pinned_by"] == a.user.id


@pytest.mark.integration
async def test_unpin_clears_the_expiry_with_it(
    client: AsyncClient, acting_user, session
):
    """An expiry belongs to a pin; leaving one behind would silently apply to
    the next one."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    expires = datetime.now(timezone.utc) + timedelta(days=3)

    await client.put(
        a.g(f"/posts/{post.id}/pin"),
        headers=a.headers,
        json={"pinned": True, "expires_at": expires.isoformat()},
    )
    response = await client.put(
        a.g(f"/posts/{post.id}/pin"), headers=a.headers, json={"pinned": False}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["pinned_at"] is None
    assert body["pinned_by"] is None
    assert body["pin_expires_at"] is None
    assert body["is_pinned"] is False


@pytest.mark.integration
async def test_pin_refuses_an_expiry_already_past(
    client: AsyncClient, acting_user, session
):
    """A pin that is already over is a no-op that reads as a pin — refused
    rather than stored."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    past = datetime.now(timezone.utc) - timedelta(days=1)

    response = await client.put(
        a.g(f"/posts/{post.id}/pin"),
        headers=a.headers,
        json={"pinned": True, "expires_at": past.isoformat()},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "POST_PIN_EXPIRY_IN_PAST"


@pytest.mark.integration
async def test_pin_on_an_unreadable_post_is_not_confirmed(
    client: AsyncClient, acting_user, session
):
    """Read access is checked before the manager check, so the route never
    tells a stranger that a post they cannot see exists."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    await _strip_non_owner_grants(session, post, a.user.id)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    response = await client.put(
        b.g(f"/posts/{post.id}/pin"), headers=b.headers, json={"pinned": True}
    )
    assert response.status_code in (403, 404)
    assert response.json()["detail"] != "POST_PIN_MANAGER_REQUIRED"


# ---------------------------------------------------------------------------
# Length
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_post_longer_than_the_limit_is_refused(
    client: AsyncClient, acting_user, session
):
    """A board is read, not studied — something this long is a document."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)

    response = await client.post(
        a.g("/posts/"),
        headers=a.headers,
        json={
            "name": "War and Peace",
            "initiative_id": a.initiative.id,
            "body": lexical_body("x" * (MAX_POST_TEXT_CHARS + 1)),
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "POST_BODY_TOO_LONG"


@pytest.mark.integration
async def test_an_edit_cannot_grow_a_post_past_the_limit(
    client: AsyncClient, acting_user, session
):
    """The ceiling is on the body, not on the way it arrived."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)

    response = await client.patch(
        a.g(f"/posts/{post.id}"),
        headers=a.headers,
        json={"body": lexical_body("x" * (MAX_POST_TEXT_CHARS + 1))},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "POST_BODY_TOO_LONG"


@pytest.mark.integration
async def test_a_post_at_the_limit_is_accepted(
    client: AsyncClient, acting_user, session
):
    """The boundary is inclusive — a notice exactly at the ceiling is fine."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)

    response = await client.post(
        a.g("/posts/"),
        headers=a.headers,
        json={
            "name": "Just about",
            "initiative_id": a.initiative.id,
            "body": lexical_body("x" * MAX_POST_TEXT_CHARS),
        },
    )

    assert response.status_code == 201, response.text


# ---------------------------------------------------------------------------
# Reactions
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_post_carries_its_reactions(client: AsyncClient, acting_user, session):
    """Chips ride along with the post, so a board renders them from the one
    list call rather than a request per row."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)

    toggled = await client.put(
        a.g(f"/reactions/post/{post.id}"), headers=a.headers, json={"emoji": "🎉"}
    )
    assert toggled.status_code == 200, toggled.text

    listing = await client.get(a.g("/posts/"), headers=a.headers)
    (item,) = listing.json()["items"]
    assert [(g["emoji"], g["count"], g["reacted"]) for g in item["reactions"]] == [
        ("🎉", 1, True)
    ]

    detail = await client.get(a.g(f"/posts/{post.id}"), headers=a.headers)
    assert detail.json()["reactions"] == item["reactions"]


@pytest.mark.integration
async def test_reacting_needs_only_read_access(
    client: AsyncClient, acting_user, session
):
    """A notice everyone on the board can see is one everyone can react to —
    reacting is a gesture, not an edit."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    response = await client.put(
        b.g(f"/reactions/post/{post.id}"), headers=b.headers, json={"emoji": "👍"}
    )
    assert response.status_code == 200, response.text


@pytest.mark.integration
async def test_reacting_to_an_unreadable_post_is_refused(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    await _strip_non_owner_grants(session, post, a.user.id)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    response = await client.put(
        b.g(f"/reactions/post/{post.id}"), headers=b.headers, json={"emoji": "👍"}
    )
    assert response.status_code in (403, 404)


# ---------------------------------------------------------------------------
# Excerpts
# ---------------------------------------------------------------------------


def test_excerpt_reads_every_kind_of_text_node():
    """Mentions and chips keep their words in ``text`` like a text node, so the
    excerpt reads what the post says rather than only its plain runs."""
    body = {
        "root": {
            "children": [
                {
                    "type": "paragraph",
                    "children": [
                        {"type": "text", "text": "Ping"},
                        {"type": "mention", "text": "@Ada"},
                        {"type": "text", "text": "about"},
                        {"type": "smart-chip", "text": "Ship it"},
                    ],
                }
            ]
        }
    }
    assert post_excerpt(body) == "Ping @Ada about Ship it"


def test_excerpt_of_a_body_with_no_words_is_empty():
    """A notice that is only a picture has nothing to excerpt — it shows as its
    headline, which is what there is."""
    body = {"root": {"children": [{"type": "image", "src": "/x.png"}]}}
    assert post_excerpt(body) == ""
    assert post_excerpt({}) == ""


def test_excerpt_truncates_on_a_word_boundary():
    body = {
        "root": {
            "children": [
                {
                    "type": "paragraph",
                    "children": [{"type": "text", "text": "wo " * 200}],
                }
            ]
        }
    }
    excerpt = post_excerpt(body, limit=20)
    assert len(excerpt) <= 20
    assert excerpt.endswith("…")
    assert not excerpt.endswith("w…")
