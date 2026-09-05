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

from typing import Any

from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative
from app.models.tenant.post import Post, pin_is_live
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
    """
    from sqlalchemy import case, desc

    live = pin_is_live()
    return [
        desc(case((live, 1), else_=0)),
        case((live, Post.pinned_at), else_=None).desc().nullslast(),
        Post.created_at.desc(),
        Post.id.desc(),
    ]


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
    """Ids of every post the user may export in the given initiatives — DAC-visible
    to the user, feature-flag respected. Deterministic order for stable backup
    output."""
    if not initiative_ids:
        return []
    conditions = [
        Post.initiative_id.in_(initiative_ids),
        Initiative.posts_enabled == True,  # noqa: E712
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
