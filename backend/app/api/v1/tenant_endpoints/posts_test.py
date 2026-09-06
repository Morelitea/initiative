"""Tests for the post endpoints — CRUD, the board's order, pinning, scheduling,
and the authorization gates (feature gate, role create gate, DAC levels).

The post-specific concerns beyond the usual tool contract are the three things
the board owns: what order notices come back in, who may lift one above the
others, and when a notice becomes something other people can see.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import delete as sa_delete, text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.models.platform.notification import Notification, NotificationType
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
async def test_pin_requires_read_access_before_the_manager_check(
    client: AsyncClient, acting_user, session
):
    """The two gates run in order: read access on the post, then initiative
    authority. A caller without the first is refused at it."""
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
    # Refused at the read gate, so it never reaches the manager check.
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


# ---------------------------------------------------------------------------
# Scheduling and publication
# ---------------------------------------------------------------------------


async def _notifications_for(
    session: AsyncSession, user_id: int, ntype: NotificationType
) -> list[Notification]:
    await session.exec(text("SET search_path TO public"))
    result = await session.exec(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.type == ntype,
        )
    )
    return list(result.all())


@pytest.mark.integration
async def test_posting_now_notifies_the_people_it_is_shared_with(
    client: AsyncClient, acting_user, session
):
    """The default sharing is the whole initiative, so the whole initiative
    hears about it — everyone except the author."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    b = await acting_user(
        guild_role=GuildRole.member, guild=a.guild, initiative=a.initiative
    )
    await _posts_enabled(session, a.initiative)

    response = await client.post(
        a.g("/posts/"),
        headers=a.headers,
        json={
            "name": "Doors open at seven",
            "initiative_id": a.initiative.id,
            "body": lexical_body("Bring a chair."),
        },
    )
    assert response.status_code == 201
    assert response.json()["is_published"] is True

    assert (
        len(
            await _notifications_for(
                session, b.user.id, NotificationType.post_published
            )
        )
        == 1
    )
    assert (
        await _notifications_for(session, a.user.id, NotificationType.post_published)
        == []
    )


@pytest.mark.integration
async def test_a_notice_only_notifies_who_it_was_shared_with(
    client: AsyncClient, acting_user, session
):
    """The fan-out follows the post's own grants, not the initiative roster.

    This is the gate the whole feature hangs on: sharing a notice with one
    person must not ring the bell of everybody who happens to be in the
    initiative.
    """
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    named = await acting_user(
        guild_role=GuildRole.member, guild=a.guild, initiative=a.initiative
    )
    bystander = await acting_user(
        guild_role=GuildRole.member, guild=a.guild, initiative=a.initiative
    )
    await _posts_enabled(session, a.initiative)

    response = await client.post(
        a.g("/posts/"),
        headers=a.headers,
        json={
            "name": "Just for you",
            "initiative_id": a.initiative.id,
            "body": lexical_body("A word in private."),
            "grants": [{"user_id": named.user.id, "level": "read"}],
        },
    )
    assert response.status_code == 201

    assert (
        len(
            await _notifications_for(
                session, named.user.id, NotificationType.post_published
            )
        )
        == 1
    )
    assert (
        await _notifications_for(
            session, bystander.user.id, NotificationType.post_published
        )
        == []
    )


@pytest.mark.integration
async def test_a_scheduled_notice_is_not_published_and_notifies_nobody(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    b = await acting_user(
        guild_role=GuildRole.member, guild=a.guild, initiative=a.initiative
    )
    await _posts_enabled(session, a.initiative)
    when = datetime.now(timezone.utc) + timedelta(days=1)

    response = await client.post(
        a.g("/posts/"),
        headers=a.headers,
        json={
            "name": "Tomorrow's news",
            "initiative_id": a.initiative.id,
            "body": lexical_body("Not yet."),
            "scheduled_for": when.isoformat(),
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["is_published"] is False
    assert payload["published_at"] is None
    assert payload["scheduled_for"] is not None

    assert (
        await _notifications_for(session, b.user.id, NotificationType.post_published)
        == []
    )


@pytest.mark.integration
async def test_a_schedule_in_the_past_posts_it_now(
    client: AsyncClient, acting_user, session
):
    """An instant that has already gone is somebody asking for it now — the
    same thing an omitted schedule means, so it takes the same branch."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    when = datetime.now(timezone.utc) - timedelta(minutes=5)

    response = await client.post(
        a.g("/posts/"),
        headers=a.headers,
        json={
            "name": "Backdated",
            "initiative_id": a.initiative.id,
            "body": lexical_body("Now."),
            "scheduled_for": when.isoformat(),
        },
    )
    assert response.status_code == 201
    assert response.json()["is_published"] is True
    assert response.json()["scheduled_for"] is None


@pytest.mark.integration
async def test_a_draft_is_invisible_to_a_reader_but_not_to_its_author(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    reader = await acting_user(
        guild_role=GuildRole.member, guild=a.guild, initiative=a.initiative
    )
    await _posts_enabled(session, a.initiative)
    draft = await create_post(
        session,
        a.initiative,
        a.user,
        name="Not yet",
        published_at=None,
        scheduled_for=datetime.now(timezone.utc) + timedelta(days=1),
    )

    mine = await client.get(a.g("/posts/"), headers=a.headers)
    assert [p["id"] for p in mine.json()["items"]] == [draft.id]

    theirs = await client.get(reader.g("/posts/"), headers=reader.headers)
    assert theirs.json()["items"] == []
    assert theirs.json()["total_count"] == 0

    direct = await client.get(reader.g(f"/posts/{draft.id}"), headers=reader.headers)
    assert direct.status_code == 404
    assert (
        await client.get(a.g(f"/posts/{draft.id}"), headers=a.headers)
    ).status_code == 200


@pytest.mark.integration
async def test_a_draft_is_out_of_the_sidebar_counts(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    reader = await acting_user(
        guild_role=GuildRole.member, guild=a.guild, initiative=a.initiative
    )
    await _posts_enabled(session, a.initiative)
    await create_post(session, a.initiative, a.user, name="Live one")
    await create_post(
        session,
        a.initiative,
        a.user,
        name="Draft one",
        published_at=None,
        scheduled_for=datetime.now(timezone.utc) + timedelta(days=1),
    )

    counts = await client.get(
        reader.g("/posts/counts/by-initiative"), headers=reader.headers
    )
    assert counts.json()["counts"][str(a.initiative.id)] == 1


@pytest.mark.integration
async def test_a_read_only_grantee_cannot_see_a_draft(
    client: AsyncClient, acting_user, session
):
    """The draft leg is write access, not any access. Someone the notice is
    already shared with still does not get it early."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    reader = await acting_user(
        guild_role=GuildRole.member, guild=a.guild, initiative=a.initiative
    )
    await _posts_enabled(session, a.initiative)
    draft = await create_post(
        session,
        a.initiative,
        a.user,
        name="Shared but not up",
        published_at=None,
        scheduled_for=datetime.now(timezone.utc) + timedelta(days=1),
    )

    listing = await client.get(reader.g("/posts/"), headers=reader.headers)
    assert [p["id"] for p in listing.json()["items"]] == []
    assert (
        await client.get(reader.g(f"/posts/{draft.id}"), headers=reader.headers)
    ).status_code == 404


@pytest.mark.integration
async def test_an_editor_can_see_a_draft(client: AsyncClient, acting_user, session):
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    editor = await acting_user(
        guild_role=GuildRole.member, guild=a.guild, initiative=a.initiative
    )
    await _posts_enabled(session, a.initiative)
    draft = await create_post(
        session,
        a.initiative,
        a.user,
        name="Co-written",
        published_at=None,
        scheduled_for=datetime.now(timezone.utc) + timedelta(days=1),
    )
    session.add(
        ResourceGrant(
            resource_type="post",
            resource_id=draft.id,
            user_id=editor.user.id,
            level="write",
            guild_id=a.guild.id,
            initiative_id=a.initiative.id,
        )
    )
    await session.commit()

    listing = await client.get(editor.g("/posts/"), headers=editor.headers)
    assert [p["id"] for p in listing.json()["items"]] == [draft.id]


@pytest.mark.integration
async def test_clearing_the_schedule_publishes_and_notifies(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    b = await acting_user(
        guild_role=GuildRole.member, guild=a.guild, initiative=a.initiative
    )
    await _posts_enabled(session, a.initiative)
    draft = await create_post(
        session,
        a.initiative,
        a.user,
        name="Post it now",
        published_at=None,
        scheduled_for=datetime.now(timezone.utc) + timedelta(days=1),
    )

    response = await client.patch(
        a.g(f"/posts/{draft.id}"),
        headers=a.headers,
        json={"scheduled_for": None},
    )
    assert response.status_code == 200
    assert response.json()["is_published"] is True
    assert (
        len(
            await _notifications_for(
                session, b.user.id, NotificationType.post_published
            )
        )
        == 1
    )


@pytest.mark.integration
async def test_a_published_notice_cannot_be_rescheduled(
    client: AsyncClient, acting_user, session
):
    """Publication is not reversible — the people it was announced to have
    already been told."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user, name="Already up")

    response = await client.patch(
        a.g(f"/posts/{post.id}"),
        headers=a.headers,
        json={
            "scheduled_for": (
                datetime.now(timezone.utc) + timedelta(days=1)
            ).isoformat()
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "POST_ALREADY_PUBLISHED"


@pytest.mark.integration
async def test_posting_an_already_posted_notice_now_is_nothing_to_do(
    client: AsyncClient, acting_user, session
):
    """ "Post now" twice is a double click, not a conflict — and it must not
    announce the notice a second time."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    b = await acting_user(
        guild_role=GuildRole.member, guild=a.guild, initiative=a.initiative
    )
    await _posts_enabled(session, a.initiative)
    draft = await create_post(
        session,
        a.initiative,
        a.user,
        name="Twice",
        published_at=None,
        scheduled_for=datetime.now(timezone.utc) + timedelta(days=1),
    )
    body = {"scheduled_for": None}

    first = await client.patch(a.g(f"/posts/{draft.id}"), headers=a.headers, json=body)
    second = await client.patch(a.g(f"/posts/{draft.id}"), headers=a.headers, json=body)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["is_published"] is True
    assert (
        len(
            await _notifications_for(
                session, b.user.id, NotificationType.post_published
            )
        )
        == 1
    )


@pytest.mark.integration
async def test_the_board_dates_a_notice_by_when_it_went_up(
    client: AsyncClient, acting_user, session
):
    """A notice written last week and published today leads a notice written
    yesterday — the board is a feed of what has been said, not of drafting."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    now = datetime.now(timezone.utc)
    await create_post(
        session,
        a.initiative,
        a.user,
        name="Written yesterday",
        created_at=now - timedelta(days=1),
        published_at=now - timedelta(days=1),
    )
    await create_post(
        session,
        a.initiative,
        a.user,
        name="Written last week, up today",
        created_at=now - timedelta(days=7),
        published_at=now,
    )

    response = await client.get(a.g("/posts/"), headers=a.headers)
    assert [p["name"] for p in response.json()["items"]] == [
        "Written last week, up today",
        "Written yesterday",
    ]


@pytest.mark.integration
async def test_a_draft_is_not_exported(client: AsyncClient, acting_user, session):
    """An export is a record of what a board has said, and a draft has said
    nothing yet."""
    from app.services.tenant.posts import list_post_ids_for_export

    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    live = await create_post(session, a.initiative, a.user, name="Up")
    await create_post(
        session,
        a.initiative,
        a.user,
        name="Not up",
        published_at=None,
        scheduled_for=datetime.now(timezone.utc) + timedelta(days=1),
    )

    ids = await list_post_ids_for_export(
        session, a.user, a.guild.id, initiative_ids=[a.initiative.id]
    )
    assert ids == [live.id]


@pytest.mark.integration
async def test_setting_an_expiry_does_not_re_pin(
    client: AsyncClient, acting_user, session
):
    """Putting an end date on a live pin changes the end date and nothing else.

    Re-stamping ``pinned_at`` would vault a three-day-old pin over the pins
    made since it, which is the band's ordering key.
    """
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user, name="Long-standing")

    first = await client.put(
        a.g(f"/posts/{post.id}/pin"), headers=a.headers, json={"pinned": True}
    )
    assert first.status_code == 200
    pinned_at = first.json()["pinned_at"]

    second = await client.put(
        a.g(f"/posts/{post.id}/pin"),
        headers=a.headers,
        json={
            "pinned": True,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
        },
    )
    assert second.status_code == 200
    assert second.json()["pinned_at"] == pinned_at
    assert second.json()["pin_expires_at"] is not None


@pytest.mark.integration
async def test_re_pinning_a_lapsed_pin_starts_a_new_one(
    client: AsyncClient, acting_user, session
):
    """A pin whose expiry has passed reads as no pin at all, so pinning again
    is a new pin and takes today's date."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    stale = datetime.now(timezone.utc) - timedelta(days=5)
    post = await create_post(
        session,
        a.initiative,
        a.user,
        name="Lapsed",
        pinned_at=stale,
        pinned_by=a.user.id,
        pin_expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )

    response = await client.put(
        a.g(f"/posts/{post.id}/pin"), headers=a.headers, json={"pinned": True}
    )
    assert response.status_code == 200
    assert response.json()["pinned_at"] != stale.isoformat()
    assert response.json()["is_pinned"] is True
    assert response.json()["pin_expires_at"] is None
