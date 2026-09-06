"""Post endpoints — an initiative's bulletin board.

Creation is gated at the initiative level (posts_enabled + create_posts);
everything after that flows from the post's resource-grant DAC
(``resource_grants`` + ``PUT /{id}/grants``), like every other tool.

Two things here are the board's own rather than the generic tool shape:

* **Order.** The default list order is the board — live pins on top, then
  newest first — rendered by ``posts_service.board_order()`` so nothing that
  shows a board can disagree about it. Passing ``sort_by`` opts out into the
  ordinary tool sort, which is what the guild-wide table needs.
* **Page size.** A board renders its notices, bodies and all, so the list
  returns whole posts and pages in twenties rather than the hundreds every
  other tool list takes. Each body is a Lexical state the client mounts an
  editor for, and that is the cost this cap is protecting; it is a starting
  number to be tuned against real boards, not a considered limit.
* **Pinning.** Lifting a notice above everyone else's is initiative management
  authority, not write access on the post, so ``PUT /{id}/pin`` asks for guild
  admin or an initiative manager rather than the post's own DAC. Its author
  can edit and delete it either way.
* **Publication.** A post with a ``scheduled_for`` in the future is a draft: it
  is reachable only by the people who could edit it, appears in no board, count
  or search result, and nobody has been told about it. The publication worker
  (``services/tenant/post_publication.py``) stamps ``published_at`` when its
  time comes and announces it then. Posting without a schedule stamps it here
  and announces before the commit, so the notice and the notices about it land
  together.
"""

from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api import resource_access
from app.api.deps import (
    IncludeDeletedDep,
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.messages import InitiativeMessages, PostMessages
from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative, PermissionKey
from app.models.tenant.post import Post
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.schemas.tenant.initiative import InitiativeGroupedCountsResponse
from app.schemas.tenant.post import (
    PostCreate,
    PostListResponse,
    PostPinUpdate,
    PostRead,
    PostUpdate,
    post_body_too_long,
    serialize_post,
)
from app.schemas.tenant.recent_view import RecentViewWrite
from app.schemas.tenant.resource_grant import ResourceGrantSchema
from app.services import permissions as permissions_service
from app.services import rls as rls_service
from app.services.tenant import comments as comments_service
from app.services.tenant import post_publication
from app.services.tenant import posts as posts_service
from app.services.tenant import recent_views as recent_views_service
from app.services.tenant import search as search_service
from app.services.tenant import tags as tags_service
from app.services.tenant import tool_listing

#: How many notices a board hands over at once. A post carries its body and
#: the client mounts an editor per body, so this is deliberately far below the
#: 100 every other tool list defaults to. A starting number, to be tuned once
#: there are real boards to measure.
BOARD_PAGE_SIZE = 20
MAX_BOARD_PAGE_SIZE = 50

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_initiative_for_post(
    session: RLSSessionDep,
    initiative_id: int,
) -> Initiative:
    stmt = (
        select(Initiative)
        .where(Initiative.id == initiative_id)
        .options(
            selectinload(Initiative.memberships),
            selectinload(Initiative.roles),
        )
    )
    result = await session.exec(stmt)
    initiative = result.one_or_none()
    if not initiative:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.NOT_FOUND,
        )
    return initiative


async def _check_create_permission(
    session: RLSSessionDep,
    initiative: Initiative,
    user: User,
    guild_context: GuildContext,
) -> None:
    if rls_service.is_guild_admin(guild_context.role):
        return
    has_perm = await rls_service.check_initiative_permission(
        session,
        initiative_id=initiative.id,
        user=user,
        permission_key=PermissionKey.create_posts,
    )
    if not has_perm:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PostMessages.CREATE_PERMISSION_REQUIRED,
        )


def _validated_body(body: dict | None) -> dict:
    """A notice's body, or a 422 saying it is too long.

    The rule itself lives with the schema (``post_body_too_long``) because an
    import applies the same one; this only maps it to a status code.
    """
    clean = body or {}
    if post_body_too_long(clean):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=PostMessages.BODY_TOO_LONG,
        )
    return clean


def _may_edit(post: Post, user: User, guild_context: GuildContext) -> bool:
    """Whether this caller could change the post — which is also who may see it
    before it goes up.

    The row-shaped form of ``permissions.writable_scope_clause``, leg for leg:
    the same bypass check, then a grant at write or owner. Written this way
    rather than through ``compute_post_permission`` so this route and the
    board's own listing cannot disagree about which drafts exist — that one
    also caps at read while a community is frozen, which would hide a draft
    from its author rather than merely stop them editing it.
    """
    if permissions_service.request_bypasses_dac(
        guild_context.guild_id,
        initiative_id=post.initiative_id,
        access="write",
    ):
        return True
    level = permissions_service.effective_level(
        permissions_service.DAC_RESOURCES[Tool.post], post, user.id
    )
    return level in ("write", "owner")


async def _announce(
    session: RLSSessionDep,
    post: Post,
    author: User,
    guild_context: GuildContext,
) -> None:
    """Tell the notice's audience it is up.

    Needs the sharing and the initiative roster loaded, which the row written a
    moment ago does not have — so it is re-read through the post loader before
    the fan-out reads its grants. The session does not autoflush, so the write
    that made it publishable has to reach the database first: without that the
    re-read would replace the pending row with the one still on disk.
    """
    await session.flush()
    hydrated = await posts_service.get_post(session, post.id, populate_existing=True)
    if hydrated is None:  # pragma: no cover — written in this transaction
        return
    await post_publication.announce_post(
        session, hydrated, author=author, guild_id=guild_context.guild_id
    )


async def _refetch_post(session: RLSSessionDep, post_id: int) -> Post:
    post = await posts_service.get_post(session, post_id, populate_existing=True)
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=PostMessages.NOT_FOUND,
        )
    # Every write answers with the row a read would return — count, chips and
    # all.
    await comments_service.annotate_comment_counts(session, [post], column="post_id")
    await posts_service.attach_reactions(session, post)
    return post


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get("/", response_model=PostListResponse)
async def list_posts(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    initiative_id: Optional[int] = Query(default=None),
    search: Optional[str] = Query(
        default=None, description="Case-insensitive substring match on name."
    ),
    sort_by: Optional[str] = Query(
        default=None,
        description=(
            "Order by one of: name, initiative, updated_at. Omit for the board "
            "order — live pins first, then newest first."
        ),
    ),
    sort_dir: Optional[str] = Query(default=None, description="asc (default) or desc."),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(
        default=BOARD_PAGE_SIZE,
        ge=1,
        le=MAX_BOARD_PAGE_SIZE,
        description=(
            "Posts per page. Small by default: a board renders each post's "
            "body, so a page is that many editors to mount."
        ),
    ),
) -> PostListResponse:
    """List posts visible to the current user (guild admins see all).

    Returns whole posts — a board shows notices, not headlines — which is why
    it pages in twenties. A scheduled notice is here only for the people who
    could edit it; for everyone else the board starts when it goes up.
    """
    conditions = [Post.guild_id == guild_context.guild_id]

    if initiative_id is not None:
        initiative = await session.get(Initiative, initiative_id)
        if initiative and not initiative.posts_enabled:
            return PostListResponse(
                items=[],
                total_count=0,
                page=page,
                page_size=page_size,
                has_next=False,
            )
        conditions.append(Post.initiative_id == initiative_id)
    else:
        conditions.append(
            Post.initiative_id.in_(
                select(Initiative.id).where(Initiative.posts_enabled == True)  # noqa: E712
            )
        )

    conditions.append(
        permissions_service.listing_scope_clause(
            Tool.post,
            Post.id,
            current_user.id,
            guild_id=guild_context.guild_id,
            initiative_id=initiative_id,
        )
    )
    conditions.append(
        posts_service.visibility_clause(
            current_user.id,
            guild_id=guild_context.guild_id,
            initiative_id=initiative_id,
        )
    )

    name_match = search_service.tool_search_clause(Tool.post, Post.id, search)
    if name_match is not None:
        conditions.append(name_match)

    count_subq = select(Post.id).where(*conditions).subquery()
    total_count = (
        await session.exec(select(func.count()).select_from(count_subq))
    ).one()

    stmt = select(Post).where(*conditions).options(*posts_service.list_loader_options())
    stmt = (
        tool_listing.apply_tool_order(
            stmt,
            Post,
            sort_by,
            sort_dir,
            default=posts_service.board_order(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.exec(stmt)
    posts = result.unique().all()
    # One grouped query each for the page, so a board of twenty asks twice
    # rather than forty times.
    await comments_service.annotate_comment_counts(session, posts, column="post_id")
    await posts_service.attach_reactions(session, *posts)

    items = [serialize_post(p, user_id=current_user.id) for p in posts]
    has_next = page * page_size < total_count
    return PostListResponse(
        items=items,
        total_count=total_count,
        page=page,
        page_size=page_size,
        has_next=has_next,
    )


# Declared before /{post_id} so the literal path wins the match.
@router.get("/counts/by-initiative", response_model=InitiativeGroupedCountsResponse)
async def get_post_counts_by_initiative(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> InitiativeGroupedCountsResponse:
    """Visible-post counts grouped by initiative.

    Lightweight endpoint for the sidebar badges — same visibility rules as the
    post list, one GROUP BY instead of a capped list page.
    """
    conditions = [
        Post.guild_id == guild_context.guild_id,
        Post.initiative_id.in_(
            select(Initiative.id).where(Initiative.posts_enabled == True)  # noqa: E712
        ),
        permissions_service.granted_scope_clause(
            Tool.post,
            Post.id,
            current_user.id,
            guild_id=guild_context.guild_id,
        ),
        posts_service.visibility_clause(
            current_user.id, guild_id=guild_context.guild_id
        ),
    ]

    statement = (
        select(Post.initiative_id, func.count(Post.id))
        .where(*conditions)
        .group_by(Post.initiative_id)
    )
    rows = (await session.exec(statement)).all()
    return InitiativeGroupedCountsResponse(
        counts={initiative_id: count for initiative_id, count in rows}
    )


@router.get("/{post_id}", response_model=PostRead)
async def read_post(
    post_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    include_deleted: IncludeDeletedDep = False,
) -> PostRead:
    """Read one notice.

    A scheduled one answers 404 unless the caller could edit it: until it goes
    up it is a draft, and the board it belongs to does not have it yet.
    """
    post = await resource_access.load_authorized(
        session, Tool.post, post_id, current_user, guild_context
    )
    if not post.is_published and not _may_edit(post, current_user, guild_context):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=PostMessages.NOT_FOUND,
        )
    await comments_service.annotate_comment_counts(session, [post], column="post_id")
    await posts_service.attach_reactions(session, post)
    return serialize_post(post, user_id=current_user.id)


@router.post("/", response_model=PostRead, status_code=status.HTTP_201_CREATED)
async def create_post(
    post_in: PostCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> PostRead:
    """Post a notice to an initiative's board. Requires create_posts permission
    on the initiative (or guild admin); the author gets the owner grant."""
    initiative = await _get_initiative_for_post(session, post_in.initiative_id)
    if not initiative.posts_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PostMessages.FEATURE_DISABLED,
        )
    await _check_create_permission(session, initiative, current_user, guild_context)

    now = datetime.now(timezone.utc)
    # A schedule in the past is somebody asking for it now, which is what an
    # omitted one means too — so both take the same branch rather than one of
    # them being an error.
    scheduled = (
        post_in.scheduled_for
        if post_in.scheduled_for is not None and post_in.scheduled_for > now
        else None
    )
    post = Post(
        guild_id=guild_context.guild_id,
        initiative_id=initiative.id,
        created_by=current_user.id,
        name=post_in.name.strip(),
        body=_validated_body(post_in.body),
        scheduled_for=scheduled,
        published_at=None if scheduled else now,
    )
    session.add(post)
    await session.flush()

    session.add(
        ResourceGrant(
            resource_type="post",
            resource_id=post.id,
            user_id=current_user.id,
            role_id=None,
            level=ResourceAccessLevel.owner,
            guild_id=guild_context.guild_id,
            initiative_id=initiative.id,
        )
    )

    # Apply the initial sharing exactly the way edits do — one grant list, one
    # code path (defaults to Viewer for all initiative members).
    await permissions_service.replace_resource_grants(
        session,
        resource_type="post",
        resource_id=post.id,
        guild_id=guild_context.guild_id,
        initiative_id=initiative.id,
        owner_id=current_user.id,
        grants=post_in.grants,
    )

    if post_in.tag_ids:
        await tags_service.set_entity_tags(
            session,
            tags_service.TOOL_TAG_LINKS[Tool.post],
            guild_id=guild_context.guild_id,
            entity_id=post.id,
            tag_ids=post_in.tag_ids,
        )

    if post.published_at is not None:
        await _announce(session, post, current_user, guild_context)

    await session.commit()
    hydrated = await _refetch_post(session, post.id)
    return serialize_post(hydrated, user_id=current_user.id)


@router.patch("/{post_id}", response_model=PostRead)
async def update_post(
    post_id: int,
    post_in: PostUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> PostRead:
    """Edit a notice — its headline, its body, or a schedule not yet reached.
    Requires write access.

    ``scheduled_for`` moves a pending schedule; sending it as ``null`` publishes
    the draft immediately, which is how "post it now" is expressed. Sending it
    at all on a notice that is already up is a 409: publication is not
    reversible, because the people it was announced to have already been told.

    Pinning is deliberately not here: it is a different authority, and lives on
    its own route below.
    """
    post = await resource_access.load_authorized(
        session,
        Tool.post,
        post_id,
        current_user,
        guild_context,
        access="write",
    )
    updated = False
    publish_now = False
    now = datetime.now(timezone.utc)
    update_data = post_in.model_dump(exclude_unset=True)

    if "name" in update_data and update_data["name"] is not None:
        post.name = update_data["name"].strip()
        updated = True
    if "body" in update_data and update_data["body"] is not None:
        post.body = _validated_body(update_data["body"])
        updated = True
    if "scheduled_for" in update_data:
        when = update_data["scheduled_for"]
        if post.published_at is not None:
            # Already up. "Post it now" (a null) is simply nothing left to do;
            # holding it back again is refused, because the people it was
            # announced to have already been told.
            if when is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=PostMessages.ALREADY_PUBLISHED,
                )
        elif when is not None and when > now:
            post.scheduled_for = when
            updated = True
        else:
            # Cleared, or moved to a moment that has passed: it goes up now.
            post.scheduled_for = None
            post.published_at = now
            publish_now = True
            updated = True

    if updated:
        post.updated_at = now
        session.add(post)
        if publish_now:
            await _announce(session, post, current_user, guild_context)
        await session.commit()

    hydrated = await _refetch_post(session, post.id)
    return serialize_post(hydrated, user_id=current_user.id)


@router.put("/{post_id}/pin", response_model=PostRead)
async def set_post_pin(
    post_id: int,
    pin_in: PostPinUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> PostRead:
    """Pin a notice to the top of the board, or take it back down.

    A pin puts one person's notice above everyone else's, so it asks for
    authority over the initiative — guild admin or an initiative manager —
    rather than write access on the post. Read access on the post is required
    first, then that authority.

    An optional ``expires_at`` lets a notice about a date stop shouting once
    the date passes: the pin simply stops counting and the post falls back into
    the feed by its own age. Nothing sweeps the columns afterwards — a lapsed
    pin is still the record of who pinned it and when.

    Sending ``pinned`` on a pin that is already live changes only the expiry —
    the pin keeps its original time and author. A pin that has lapsed is a new
    pin, so that one re-stamps.
    """
    post = await resource_access.load_authorized(
        session, Tool.post, post_id, current_user, guild_context
    )
    if not rls_service.is_guild_admin(guild_context.role):
        is_manager = await rls_service.is_initiative_manager(
            session, initiative_id=post.initiative_id, user=current_user
        )
        if not is_manager:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=PostMessages.PIN_MANAGER_REQUIRED,
            )

    now = datetime.now(timezone.utc)
    if pin_in.pinned:
        if pin_in.expires_at is not None and pin_in.expires_at <= now:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=PostMessages.PIN_EXPIRY_IN_PAST,
            )
        # Pinning something already pinned is a change to the expiry, not a new
        # pin: keep who pinned it and when, so putting an end date on a
        # three-day-old pin does not vault it over the pins made since.
        if not post.is_pinned_now(now):
            post.pinned_at = now
            post.pinned_by = current_user.id
        post.pin_expires_at = pin_in.expires_at
    else:
        post.pinned_at = None
        post.pinned_by = None
        post.pin_expires_at = None

    post.updated_at = now
    session.add(post)
    await session.commit()

    hydrated = await _refetch_post(session, post.id)
    return serialize_post(hydrated, user_id=current_user.id)


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(
    post_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Soft-delete a post. Requires owner permission or guild admin."""
    from app.services.platform import guilds as guilds_service
    from app.services.tenant.soft_delete import soft_delete_entity

    post = await resource_access.load_authorized(
        session,
        Tool.post,
        post_id,
        current_user,
        guild_context,
        require_owner=True,
    )
    retention_days = await guilds_service.get_guild_retention_days(
        session, guild_context.guild_id
    )
    await soft_delete_entity(
        session,
        post,
        deleted_by_user_id=current_user.id,
        retention_days=retention_days,
    )
    await session.commit()


# ---------------------------------------------------------------------------
# Sharing (resource grants)
# ---------------------------------------------------------------------------


@router.put("/{post_id}/grants", response_model=PostRead)
async def set_post_grants(
    post_id: int,
    grants: List[ResourceGrantSchema],
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> PostRead:
    """Replace the post's entire sharing state in one call — the body is the
    full list of grants (all-initiative-members / per-user / per-role). Every
    non-owner grant is rebuilt from it; the owner is always preserved."""
    await resource_access.set_resource_grants(
        session, Tool.post, post_id, current_user, guild_context, grants
    )
    hydrated = await _refetch_post(session, post_id)
    return serialize_post(hydrated, user_id=current_user.id)


# ---------------------------------------------------------------------------
# Recent-view tracking (powers the layout header tabs bar)
# ---------------------------------------------------------------------------


@router.post("/{post_id}/view", response_model=RecentViewWrite)
async def record_post_view(
    post_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> RecentViewWrite:
    post = await resource_access.load_authorized(
        session, Tool.post, post_id, current_user, guild_context
    )
    record = await recent_views_service.record_view(
        session,
        user_id=current_user.id,
        entity_type="post",
        entity_id=post.id,
        persist=not guild_context.is_pam,
        limit=current_user.recent_tabs_limit,
    )
    return RecentViewWrite(
        entity_type="post",
        entity_id=post.id,
        last_viewed_at=record.last_viewed_at,
    )


@router.delete("/{post_id}/view", status_code=status.HTTP_204_NO_CONTENT)
async def clear_post_view(
    post_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    await resource_access.load_authorized(
        session, Tool.post, post_id, current_user, guild_context
    )
    await recent_views_service.clear_view(
        session,
        user_id=current_user.id,
        entity_type="post",
        entity_id=post_id,
    )
