"""Post service — loaders, the board's ordering, and the pin rule.

A post is a shareable DAC resource (``resource_type='post'``) holding a
notice as a Lexical editor state. It owns no child content; its comments
belong to the shared comment table like every other tool's, and its reactions
to the shared reaction table.

The one thing that is genuinely this tool's own is the **board order**:
:func:`board_order` puts the live pins first, most recently pinned at the top,
and everything else newest-first behind them. It is written once here so the
list endpoint, the export, and anything else that renders a board cannot
disagree about what "the top" means.
"""

from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from typing import Any, cast

from sqlalchemy.orm import selectinload
from sqlalchemy import false
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative
from app.models.tenant.post import Post, board_time, is_published_clause, pin_is_live
from app.models.tenant.post_read import PostRead
from app.models.tenant.resource_grant import ResourceGrant
from app.services import permissions as permissions_service
from app.services.tenant import tags as tags_service


def list_loader_options() -> list:
    """Eager-load what a post *list* row needs: its sharing, its initiative's
    memberships (the DAC engine reads them), and its tags."""
    return [
        selectinload(Post.grants).selectinload(ResourceGrant.role),
        selectinload(Post.initiative).selectinload(Initiative.memberships),
        # Who wrote it. A notice is signed — the board shows the person above
        # the headline the way a comment shows its author — so the profile
        # comes with the row rather than costing a query per card.
        selectinload(Post.creator),
        tags_service.TOOL_TAG_LINKS[Tool.post].load_options(),
    ]


def post_loader_options() -> list:
    """Eager-load everything post serialization + authorization needs."""
    return list_loader_options()


def board_order() -> list:
    """The bulletin board's order: live pins on top, then newest first.

    ``pin_is_live()`` is what decides membership of the pinned band, so a pin
    whose expiry has passed falls back into the feed by date without anything
    having to sweep the column. Within the band the most recently pinned notice
    leads; behind it the feed is strictly reverse-chronological, with the id as
    the tiebreak so two posts written in the same instant still order stably.

    The second key reads the pin time *through* the same liveness test rather
    than reading the column directly. A lapsed pin still has a ``pinned_at``,
    and ordering on the raw column would sort it above every post that was
    never pinned at all — putting it back at the top of the board by the very
    expiry that was supposed to take it down.

    The feed is dated by :func:`board_time`, not by when the row was written: a
    notice scheduled for Friday belongs at the top of Friday's board, not
    wherever the moment somebody drafted it would put it.
    """
    from sqlalchemy import case, desc

    live = pin_is_live()
    return [
        desc(case((live, 1), else_=0)),
        case((live, Post.pinned_at), else_=None).desc().nullslast(),
        board_time().desc(),
        Post.id.desc(),
    ]


def visibility_clause(
    user_id: int, *, guild_id: int | None, initiative_id: int | None = None
) -> Any:
    """The WHERE leg hiding notices that have not gone up yet.

    A scheduled post is a draft: it is live for nobody until the publication
    sweep stamps it, and until then only the people who could edit it — its
    author, anyone it is shared with at write or owner, a guild admin — have
    any business seeing it. Everyone else's board, counts and search results
    are as if it did not exist.

    Written as one clause so every surface that lists posts appends the same
    rule. The draft leg is the DAC machinery's own
    :func:`permissions.writable_scope_clause` rather than a restatement of who
    may edit a post, and it takes the same ``initiative_id`` the read leg does
    so both agree on whether the question is scoped to one initiative.
    """
    from sqlalchemy import or_

    return or_(
        is_published_clause(),
        permissions_service.writable_scope_clause(
            Tool.post,
            Post.id,
            user_id,
            guild_id=guild_id,
            initiative_id=initiative_id,
        ),
    )


def audience_user_ids(post: Post, *, exclude: int | None = None) -> set[int]:
    """Who a notice was shared with — the people to tell about it.

    Defers to :func:`permissions.audience_user_ids` so the fan-out and the
    per-request check read one another's answer: a post shared with three
    people notifies three people, and a board of a hundred members is not
    interrupted because somebody posted to a subset of it.
    """
    audience = permissions_service.audience_user_ids(post)
    if exclude is not None:
        audience.discard(exclude)
    return audience


def unread_clause(user_id: int):
    """The WHERE leg for "notices this reader has not read".

    Unread is the absence of a receipt, so this is a NOT EXISTS rather than a
    flag to keep in step with anything. A notice nobody has opened has no rows
    here at all, which is what keeps the table the size of what has been read
    instead of posts x members.
    """
    from sqlalchemy import exists

    return ~exists().where(PostRead.post_id == Post.id, PostRead.user_id == user_id)


async def annotate_read_state(
    session: AsyncSession, rows: Sequence[Post], *, user_id: int
) -> None:
    """Stamp ``is_read`` on each post for this reader, in one query.

    A plain attribute, the way the comment count is: the posts table has no
    relationship to the receipts, and a board of twenty must not become twenty
    queries.
    """
    ids = [post.id for post in rows if post.id is not None]
    if not ids:
        return
    read_ids = set(
        (
            await session.exec(
                select(PostRead.post_id).where(
                    PostRead.post_id.in_(ids), PostRead.user_id == user_id
                )
            )
        ).all()
    )
    for post in rows:
        object.__setattr__(post, "is_read", post.id in read_ids)


def current_readers(post: Post, reader_ids: Iterable[int]) -> set[int]:
    """Of the people who have read this notice, the ones it is still for.

    Sharing changes after a notice goes up: somebody who read it can leave the
    initiative or lose their grant, and their receipt stays behind. The roster
    and the count both answer against the audience as it is NOW, so the two
    sides of the roster are drawn from one set — otherwise "Read 3, Unread 1"
    could describe four people and a board of five.

    Its author is not among them. Writing a notice is not reading it, and the
    roster says so on the other side too.
    """
    audience = audience_user_ids(post, exclude=post.created_by)
    return {user_id for user_id in reader_ids if user_id in audience}


async def annotate_read_counts(session: AsyncSession, rows: Sequence[Post]) -> None:
    """Stamp ``read_count`` on each post — how many people have read it.

    One query for the page, the way the comment count is done: a board of five
    must not become five more. It returns the readers rather than a count per
    post, because the number shown is the readers the notice is still FOR (see
    :func:`current_readers`) and that is a per-post question no GROUP BY can
    answer. Bounded by the page, which is five.
    """
    ids = [post.id for post in rows if post.id is not None]
    if not ids:
        return
    pairs = (
        await session.exec(
            select(PostRead.post_id, PostRead.user_id).where(PostRead.post_id.in_(ids))
        )
    ).all()
    by_post: dict[int, set[int]] = {}
    for post_id, user_id in pairs:
        by_post.setdefault(post_id, set()).add(user_id)
    for post in rows:
        readers = current_readers(post, by_post.get(post.id, set()))
        object.__setattr__(post, "read_count", len(readers))


async def list_readers(
    session: AsyncSession, post: Post
) -> tuple[list[Any], list[int]]:
    """Who has read this notice, and who it is still waiting on.

    Both sides are drawn from the notice's current audience —
    :func:`audience_user_ids`, the same set the publication notified. That is
    the only honest denominator: a board of a hundred where a notice went to
    five is not ninety-five people ignoring it, and somebody who has since left
    is on neither side rather than only on one.

    Returns the reader rows (newest first, carrying their profile) and the ids
    of everyone still to read it; the endpoint resolves those ids to people.
    """
    receipts = (
        (
            await session.exec(
                select(PostRead)
                .where(PostRead.post_id == post.id)
                .options(selectinload(PostRead.reader))
                .order_by(PostRead.read_at.desc())
            )
        )
        .unique()
        .all()
    )
    read_ids = current_readers(post, (receipt.user_id for receipt in receipts))
    waiting = audience_user_ids(post, exclude=post.created_by) - read_ids
    return [r for r in receipts if r.user_id in read_ids], sorted(waiting)


async def load_member_profiles(
    session: AsyncSession, user_ids: Sequence[int]
) -> list[Any]:
    """The people behind a set of ids, for a roster. Ordered by handle so the
    list reads the same on every request."""
    from app.models.platform.user_profile_view import MemberProfile

    if not user_ids:
        return []
    rows = (
        await session.exec(
            select(MemberProfile)
            .where(MemberProfile.id.in_(tuple(user_ids)))
            .order_by(MemberProfile.username.asc())
        )
    ).all()
    return list(rows)


async def mark_read(
    session: AsyncSession, post_ids: Sequence[int], *, user_id: int, guild_id: int
) -> int:
    """Record that this reader has seen these notices. Returns how many were new.

    An upsert on the composite key, so the board sending the same page twice —
    which it will, every time somebody scrolls back up — costs one statement and
    changes nothing. The first read time is kept rather than refreshed: when
    somebody read a notice is a fact, and looking at it again does not make it
    newer.

    A receipt is only recorded for a notice this reader can actually see, and
    only from somebody other than its author: the ids narrow through the same
    conditions the board's own list applies, so what can be marked read is
    exactly what could be read.

    "Can see" has to include the two standings that reach a notice without a
    grant — a guild admin, and Full access in the notice's initiative — or
    somebody who reads a board perfectly well would leave every notice on it
    permanently unread. The ids may span initiatives, so the second is asked
    per row rather than once for the request.
    """
    from sqlalchemy import or_
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.core.role_context import override_sharing_initiatives

    if not post_ids:
        return 0
    now = datetime.now(timezone.utc)
    full_access = override_sharing_initiatives()
    reachable = or_(
        permissions_service.dac_scope_clause(
            Tool.post, Post.id, user_id, guild_id=guild_id
        ),
        Post.initiative_id.in_(tuple(full_access)) if full_access else false(),
    )
    readable = (
        await session.exec(
            select(Post.id).where(
                Post.id.in_(tuple(post_ids)),
                Post.created_by != user_id,
                reachable,
                visibility_clause(user_id, guild_id=guild_id),
            )
        )
    ).all()
    if not readable:
        return 0
    statement = (
        pg_insert(PostRead)
        .values(
            [
                {"post_id": post_id, "user_id": user_id, "read_at": now}
                for post_id in readable
            ]
        )
        .on_conflict_do_nothing(index_elements=["post_id", "user_id"])
        .returning(PostRead.post_id)
    )
    inserted = (await session.exec(statement)).all()
    return len(inserted)


async def mark_unread(session: AsyncSession, post_id: int, *, user_id: int) -> None:
    """Take this reader's receipt off one notice.

    A delete, because unread is the absence of a row. Silent when there was
    none: asking for a state a thing is already in is not an error.
    """
    from sqlalchemy import delete as sa_delete

    await session.exec(
        sa_delete(PostRead).where(
            PostRead.post_id == post_id, PostRead.user_id == user_id
        )
    )


async def attach_reactions(session: AsyncSession, *posts: Post) -> None:
    """Load every post's reactions in ONE query and stamp them on the rows.

    A plain attribute, the way comments carry theirs: the posts table has no
    relationship to the polymorphic reactions table, and a board of twenty must
    not become twenty queries.
    """
    from app.core.reactions import ReactionTarget
    from app.services.tenant import reactions as reactions_service

    rows = [post for post in posts if post.id is not None]
    if not rows:
        return
    grouped = await reactions_service.load_reactions(
        session,
        target=ReactionTarget.post,
        target_ids=[cast(int, post.id) for post in rows],
    )
    for post in rows:
        object.__setattr__(post, "_reactions", grouped.get(post.id, []))


async def get_post(
    session: AsyncSession,
    post_id: int,
    *,
    populate_existing: bool = False,
) -> Post | None:
    """Fetch a post with the relationships authorization + serialization need.
    RLS scopes the row to the request's guild."""
    stmt = select(Post).where(Post.id == post_id).options(*post_loader_options())
    if populate_existing:
        stmt = stmt.execution_options(populate_existing=True)
    result = await session.exec(stmt)
    return result.one_or_none()


async def get_post_for_export(
    session: AsyncSession,
    current_user: User,
    guild_id: int,
    *,
    post_id: int,
) -> Post:
    """The post-export adapter's seam: fetch + authorize in one place so the
    rule holds on the worker's render-time replay too. READ access suffices —
    exporting is a formatted read."""
    from fastapi import HTTPException, status as http_status

    from app.core.messages import PostMessages

    post = await get_post(session, post_id)
    if post is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=PostMessages.NOT_FOUND,
        )
    if post.initiative is not None and not post.initiative.posts_enabled:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail=PostMessages.FEATURE_DISABLED,
        )
    permissions_service.require_access(
        permissions_service.DAC_RESOURCES[Tool.post],
        post,
        current_user,
        access="read",
    )
    # A notice that has not gone up is in no export either — the same gate the
    # read path applies, asked here because this seam resolves a caller-chosen
    # id rather than going through ``load_authorized``.
    if permissions_service.hidden_from_reader(Tool.post, post, current_user.id):
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=PostMessages.NOT_FOUND,
        )
    return post


async def list_post_ids_for_export(
    session: AsyncSession,
    current_user: Any,
    guild_id: int,
    *,
    initiative_ids: list[int],
) -> list[int]:
    """Ids of every post the user may export in the given initiatives — published,
    DAC-visible to the user, feature-flag respected. Deterministic order for
    stable backup output."""
    if not initiative_ids:
        return []
    conditions = [
        Post.initiative_id.in_(initiative_ids),
        Initiative.posts_enabled == True,  # noqa: E712
        # An export is a record of what a board has said, and a draft has not
        # been said yet — it is in no board, no count and no search result, so
        # it is in no export either. A backup therefore does not carry drafts,
        # which is the trade this one rule makes.
        is_published_clause(),
        permissions_service.dac_scope_clause(
            Tool.post, Post.id, current_user.id, guild_id=guild_id
        ),
    ]
    statement = (
        select(Post.id)
        .join(Initiative, Initiative.id == Post.initiative_id)
        .where(*conditions)
        .order_by(Post.id.asc())
    )
    return list(await session.exec(statement))
