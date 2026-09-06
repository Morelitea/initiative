"""Tests for the publication worker — the moment a scheduled notice goes up.

Three things matter here and nothing else does: a notice due now is published
exactly once, a notice not yet due is left alone, and the people it reaches are
the ones it was shared with.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.notification import Notification, NotificationType
from app.models.tenant.post import Post
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.services.tenant.post_publication import publish_due_posts
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_post,
    create_user,
    route_session_to_guild,
)

pytestmark = pytest.mark.integration


async def _board(session: AsyncSession):
    """An author, a reader who shares their initiative, that initiative with
    posts turned on, and the guild holding it."""
    author = await create_user(session)
    guild = await create_guild(session, creator=author)
    reader = await create_user(session)
    await create_guild_membership(session, user=reader, guild=guild)
    initiative = await create_initiative(session, guild, author)
    await create_initiative_member(session, initiative, reader)
    initiative.posts_enabled = True
    session.add(initiative)
    await session.commit()
    return author, reader, initiative, guild


async def _draft(session, initiative, author, *, due_in: timedelta, **kw) -> Post:
    """A scheduled notice, shared with the whole initiative the way the create
    endpoint shares one."""
    post = await create_post(
        session,
        initiative,
        author,
        published_at=None,
        scheduled_for=datetime.now(timezone.utc) + due_in,
        **kw,
    )
    return post


async def _notifications(session: AsyncSession, user_id: int) -> list[Notification]:
    return list(
        await session.exec(
            select(Notification).where(
                Notification.user_id == user_id,
                Notification.type == NotificationType.post_published,
            )
        )
    )


async def test_a_due_notice_is_published_and_announced(session: AsyncSession):
    author, reader, initiative, _ = await _board(session)
    post = await _draft(session, initiative, author, due_in=timedelta(minutes=-1))

    await route_session_to_guild(session, initiative.guild_id)
    published = await publish_due_posts(session, now=datetime.now(timezone.utc))
    await session.commit()

    assert published == [post.id]
    refreshed = (await session.exec(select(Post).where(Post.id == post.id))).one()
    assert refreshed.published_at is not None
    # The schedule stays: it is the record of when this was meant to land.
    assert refreshed.scheduled_for is not None
    assert len(await _notifications(session, reader.id)) == 1
    assert await _notifications(session, author.id) == []


async def test_a_notice_not_yet_due_is_left_alone(session: AsyncSession):
    author, reader, initiative, _ = await _board(session)
    post = await _draft(session, initiative, author, due_in=timedelta(days=1))

    await route_session_to_guild(session, initiative.guild_id)
    assert await publish_due_posts(session, now=datetime.now(timezone.utc)) == []
    await session.commit()

    refreshed = (await session.exec(select(Post).where(Post.id == post.id))).one()
    assert refreshed.published_at is None
    assert await _notifications(session, reader.id) == []


async def test_a_second_pass_publishes_nothing_twice(session: AsyncSession):
    """The claim is the ``published_at IS NULL`` predicate on the UPDATE, so a
    pass that overlaps another — or retries after a crash — announces once."""
    author, reader, initiative, _ = await _board(session)
    await _draft(session, initiative, author, due_in=timedelta(minutes=-1))

    await route_session_to_guild(session, initiative.guild_id)
    now = datetime.now(timezone.utc)
    assert len(await publish_due_posts(session, now=now)) == 1
    await session.commit()
    assert await publish_due_posts(session, now=now) == []
    await session.commit()

    assert len(await _notifications(session, reader.id)) == 1


async def test_a_trashed_draft_does_not_go_up(session: AsyncSession):
    """A notice somebody threw away must not publish itself on schedule."""
    author, reader, initiative, _ = await _board(session)
    post = await _draft(session, initiative, author, due_in=timedelta(minutes=-1))
    await route_session_to_guild(session, initiative.guild_id)
    row = (await session.exec(select(Post).where(Post.id == post.id))).one()
    row.deleted_at = datetime.now(timezone.utc)
    session.add(row)
    await session.commit()

    assert await publish_due_posts(session, now=datetime.now(timezone.utc)) == []
    await session.commit()
    assert await _notifications(session, reader.id) == []


async def test_the_announcement_follows_the_sharing_not_the_roster(
    session: AsyncSession,
):
    """The gate the feature hangs on: a notice shared with one person
    interrupts one person, however many are in the initiative."""
    author, bystander, initiative, guild = await _board(session)
    named = await create_user(session)
    await create_guild_membership(session, user=named, guild=guild)
    await create_initiative_member(session, initiative, named)

    post = await _draft(session, initiative, author, due_in=timedelta(minutes=-1))
    await route_session_to_guild(session, initiative.guild_id)
    # Replace the factory's all-members grant with one naming a single reader.
    grants = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == "post",
                ResourceGrant.resource_id == post.id,
                ResourceGrant.all_initiative_members.is_(True),
            )
        )
    ).all()
    for grant in grants:
        await session.delete(grant)
    session.add(
        ResourceGrant(
            resource_type="post",
            resource_id=post.id,
            user_id=named.id,
            level=ResourceAccessLevel.read,
            guild_id=post.guild_id,
            initiative_id=initiative.id,
        )
    )
    await session.commit()

    await publish_due_posts(session, now=datetime.now(timezone.utc))
    await session.commit()

    assert len(await _notifications(session, named.id)) == 1
    assert await _notifications(session, bystander.id) == []


async def test_somebody_who_ignores_the_author_is_not_told(session: AsyncSession):
    """Ignoring is about contact: a notice the author writes still reaches the
    board, and does not reach the bell of somebody who has stopped hearing
    from them."""
    from app.models.platform.user_ignore import UserIgnore

    author, reader, initiative, _ = await _board(session)
    await session.exec(text("SET search_path TO public"))
    session.add(UserIgnore(user_id=reader.id, ignored_user_id=author.id))
    await session.commit()

    await _draft(session, initiative, author, due_in=timedelta(minutes=-1))
    await route_session_to_guild(session, initiative.guild_id)
    await publish_due_posts(session, now=datetime.now(timezone.utc))
    await session.commit()

    assert await _notifications(session, reader.id) == []
