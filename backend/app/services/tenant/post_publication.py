"""Publication of bulletin-board notices — the moment a post goes live.

A post carries two instants: ``scheduled_for``, when its author asked for it to
go up, and ``published_at``, when it did. Everything else keys off the second
one, so "has this been published" is a column test rather than a comparison
against the clock, and the surfaces that list posts cannot disagree with this
worker about what exists.

Two ways in, one fan-out:

* **Posted now** — the endpoint stamps ``published_at`` itself and calls
  :func:`announce_post` before it commits, so the notice and the notices about
  it land together.
* **Scheduled** — the row is written with neither column resolved, and
  :func:`publish_due_posts` stamps it when its time comes. The stamp is an
  ``UPDATE … WHERE published_at IS NULL … RETURNING``, so a row is claimed by
  exactly one worker however many are running, and it is **committed before
  anything is sent**. Email and push leave the building; a rollback cannot
  call them back. Committing the claim first means a crash mid-announce costs
  some notifications, where the other order would send the whole board a
  second set on the next pass. The fan-out isolates each recipient so that
  cost is bounded by an actual crash rather than by one bad address — which is
  already better than every other notifier in the app, all of which fan out
  inline before their own commit. Making delivery exactly-once needs a
  per-recipient ledger, and that is a bar to raise everywhere at once rather
  than for one tool.

Publishing is also what puts a notice into the search index. The index is
maintained by triggers, and no trigger fires on the passage of time — but the
claim above is a real write to the row, and ``published_at`` is one of the
columns the search trigger watches. The statement that publishes is therefore
the statement that indexes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.user_display import handle_of
from app.db.session import AdminSessionLocal, set_rls_context
from app.models.platform.guild import Guild, GuildStatus
from app.models.platform.user import User
from app.models.tenant.post import Post
from app.schemas.tenant.post import post_excerpt
from app.services import notifications as notifications_service
from app.services.platform import accounts as accounts_service
from app.services.tenant import posts as posts_service

logger = logging.getLogger(__name__)

#: A minute is close enough for a bulletin board: nobody schedules a notice to
#: the second, and a shorter poll would buy nothing but load.
POST_PUBLISH_POLL_SECONDS = 60


async def announce_post(
    session: AsyncSession,
    post: Post,
    *,
    author: User,
    guild_id: int,
) -> int:
    """Tell everyone the notice was shared with that it is up. Returns how many
    were actually told.

    The audience is the post's own sharing — :func:`posts.audience_user_ids`,
    which resolves the same grant rows the per-request check reads. A notice
    shared with three people interrupts three people; posting to a subset of a
    large initiative does not ring everyone's bell.

    Recipients are loaded on the system engine: an account's notification
    settings and address are not a guild's to read. That load is also where
    somebody who ignores the author drops out — the one place a recipient is
    resolved, so a person who has stopped hearing from them is not one.
    """
    recipient_ids = posts_service.audience_user_ids(post, exclude=author.id)
    if not recipient_ids:
        return 0
    author_name = handle_of(author)
    excerpt = post_excerpt(post.body)
    recipients = await accounts_service.load_all(
        sorted(recipient_ids), excluding_ignorers_of=author.id
    )
    delivered = 0
    for recipient in recipients:
        # One recipient at a time, and one recipient's failure costs only
        # theirs. By here the publication is already committed, so an exception
        # raised out of this loop would leave the notice up and unclaimable
        # with the rest of the board never told — a whole audience lost to one
        # bad address.
        try:
            await notifications_service.notify_post_published(
                session,
                recipient=recipient,
                post_id=post.id,
                post_name=post.name,
                excerpt=excerpt,
                author_name=author_name,
                author_id=author.id,
                guild_id=guild_id,
            )
        except Exception:
            logger.exception("Could not tell %s about post %s", recipient.id, post.id)
            continue
        delivered += 1
    return delivered


async def publish_due_posts(session: AsyncSession, *, now: datetime) -> list[int]:
    """Publish every scheduled notice whose time has come, in one guild.

    The session is already routed into that guild's schema. Returns the ids
    published, which is what the tests assert on. Commits: the claim has to be
    durable before anything leaves for an inbox or a device.

    Trashed drafts are left alone: a notice somebody threw away must not go up
    on schedule. Restoring it puts it back in scope, and the next pass sends it.
    """
    claimed = (
        await session.exec(
            update(Post)
            .where(
                Post.published_at.is_(None),
                Post.scheduled_for.is_not(None),
                Post.scheduled_for <= now,
                Post.deleted_at.is_(None),
            )
            .values(published_at=now, updated_at=now)
            .returning(Post.id)
        )
    ).all()
    post_ids = [row[0] for row in claimed]
    if not post_ids:
        return []

    # The claim is durable before a single email or push goes out. Sending
    # first would mean a failure anywhere below rolls ``published_at`` back
    # while the messages stay sent, and the next pass — seeing NULL again —
    # announces the same notices to the same people.
    await session.commit()

    posts = (
        (
            await session.exec(
                select(Post)
                .where(Post.id.in_(post_ids))
                .options(*posts_service.list_loader_options())
            )
        )
        .unique()
        .all()
    )
    for post in posts:
        author = await accounts_service.load_one(post.created_by)
        if author is None:
            # The account is gone; the notice still goes up, silently.
            logger.warning("Post %s published with no author to attribute", post.id)
            continue
        await announce_post(session, post, author=author, guild_id=post.guild_id)
    return post_ids


async def _publish_all_guilds(session: AsyncSession, *, now: datetime) -> None:
    """Run one publication pass in every active guild's schema.

    Routes in as a guild admin: publishing is system maintenance over the whole
    board, and a scheduled draft is by definition shared with people the worker
    is not. Enumerating guilds happens first, on the system engine, because
    ``SET ROLE`` into a guild drops it.

    A read-only or suspended guild is skipped. A hold is a hold — it must not
    keep announcing new notices to its members while it is unresolved.
    """
    await set_rls_context(session)
    guild_ids = list(
        await session.exec(
            select(Guild.id)
            .where(Guild.status == GuildStatus.active.value)
            .order_by(Guild.id.asc())
        )
    )
    for guild_id in guild_ids:
        # ids collide across schemas, so clear the identity map between guilds.
        session.expunge_all()
        await set_rls_context(session, guild_id=guild_id, guild_role="admin")
        await publish_due_posts(session, now=now)
        await session.commit()


async def process_post_publications() -> None:
    """One pass of the publication loop across every guild schema.

    Polled by the background worker. Idempotent: a post is claimed by the
    ``published_at IS NULL`` predicate on the UPDATE, so a pass that overlaps
    another (or retries after a crash) publishes each notice exactly once.
    """
    async with AdminSessionLocal() as session:
        await _publish_all_guilds(session, now=datetime.now(timezone.utc))
