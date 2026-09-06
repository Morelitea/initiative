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

from typing import Any, cast

from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative
from app.models.tenant.post import Post, board_time, is_published_clause, pin_is_live
from app.models.tenant.resource_grant import ResourceGrant
from app.services import permissions as permissions_service
from app.services.tenant import tags as tags_service


def list_loader_options() -> list:
    """Eager-load what a post *list* row needs: its sharing, its initiative's
    memberships (the DAC engine reads them), and its tags."""
    return [
        selectinload(Post.grants).selectinload(ResourceGrant.role),
        selectinload(Post.initiative).selectinload(Initiative.memberships),
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
        # it is in no export either. A backup therefore does not carry drafts;
        # that is the trade for one rule that cannot leak an unposted notice to
        # whoever happens to run the export.
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
