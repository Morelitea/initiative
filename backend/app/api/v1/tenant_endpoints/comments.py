from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    IncludeDeletedDep,
    GuildContext,
    RLSSessionDep,
    app_scope,
    get_current_active_user,
    get_guild_membership,
)
from app.models.platform.user import User
from app.schemas.tenant.comment import (
    CommentCreate,
    CommentRead,
    CommentUpdate,
    RecentActivityEntry,
)
from app.services import notifications as notifications_service
from app.services.tenant import attachments as attachments_service
from app.services.tenant import comments as comments_service

router = APIRouter(route_class=ActorRoute)
GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]
#: The routes an installed app may call, under the comments scopes.
CommentsRead = Annotated[ActorContext, Depends(app_scope("comments:read"))]
CommentsWrite = Annotated[ActorContext, Depends(app_scope("comments:write"))]


@router.post("/", response_model=CommentRead, status_code=status.HTTP_201_CREATED)
async def create_comment(
    comment_in: CommentCreate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CommentsWrite,
) -> CommentRead:
    # An installed app posts as itself: the comment names no author, and the
    # notices it sends name the app.
    author = await notifications_service.author_of(session, guild_context, current_user)
    try:
        comment = await comments_service.create_comment(
            session,
            author=author,
            guild_id=guild_context.guild_id,
            content=comment_in.content,
            parent_comment_id=comment_in.parent_comment_id,
            **comment_in.target_ids(),
        )
    except comments_service.CommentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except comments_service.CommentPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except comments_service.CommentValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    await session.commit()
    response = comments_service.serialize_comment(
        comment, viewer_id=guild_context.user_id
    )
    return response


@router.get("/recent", response_model=List[RecentActivityEntry])
async def recent_comments(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    limit: int = Query(default=10, ge=1, le=50),
) -> List[RecentActivityEntry]:
    """Return the most recent comments across the guild.

    Only returns comments on parents the current user has DAC permission to
    view (direct user permission or role-based). Initiative-level filtering is
    handled by RLS on the joined parent tables.
    """
    return await comments_service.recent_activity(
        session, viewer_id=current_user.id, limit=limit
    )


@router.get("/", response_model=List[CommentRead])
async def list_comments(
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CommentsRead,
    task_id: Optional[int] = Query(default=None, gt=0),
    document_id: Optional[int] = Query(default=None, gt=0),
    project_id: Optional[int] = Query(default=None, gt=0),
    queue_id: Optional[int] = Query(default=None, gt=0),
    counter_group_id: Optional[int] = Query(default=None, gt=0),
    calendar_id: Optional[int] = Query(default=None, gt=0),
    dashboard_id: Optional[int] = Query(default=None, gt=0),
    post_id: Optional[int] = Query(default=None, gt=0),
    gallery_id: Optional[int] = Query(default=None, gt=0),
    wiki_id: Optional[int] = Query(default=None, gt=0),
    wiki_page_id: Optional[int] = Query(default=None, gt=0),
) -> List[CommentRead]:
    try:
        comments = await comments_service.list_comments(
            session,
            user=current_user,
            guild_id=guild_context.guild_id,
            task_id=task_id,
            document_id=document_id,
            project_id=project_id,
            queue_id=queue_id,
            counter_group_id=counter_group_id,
            calendar_id=calendar_id,
            dashboard_id=dashboard_id,
            post_id=post_id,
            gallery_id=gallery_id,
            wiki_id=wiki_id,
            wiki_page_id=wiki_page_id,
        )
    except comments_service.CommentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except comments_service.CommentPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except comments_service.CommentValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return [
        comments_service.serialize_comment(comment, viewer_id=guild_context.user_id)
        for comment in comments
    ]


@router.get("/{comment_id}", response_model=CommentRead)
async def read_comment(
    comment_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CommentsRead,
    include_deleted: IncludeDeletedDep = False,
) -> CommentRead:
    """One comment by id — the read-back for a ``comments.*`` event."""
    try:
        comment = await comments_service.get_comment(
            session,
            comment_id=comment_id,
            user=current_user,
            guild_id=guild_context.guild_id,
        )
    except comments_service.CommentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except comments_service.CommentPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return comments_service.serialize_comment(comment, viewer_id=guild_context.user_id)


@router.patch("/{comment_id}", response_model=CommentRead)
async def update_comment(
    comment_id: int,
    comment_in: CommentUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CommentRead:
    """Update a comment. Only the original author can edit."""
    try:
        comment, released_images = await comments_service.update_comment(
            session,
            comment_id=comment_id,
            user=current_user,
            guild_id=guild_context.guild_id,
            content=comment_in.content,
        )
    except comments_service.CommentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except comments_service.CommentPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    # Note: Content validation (empty string) is handled by Pydantic schema (422).
    # CommentValidationError from service indicates data integrity issues (500).

    # No refresh here: the service already flushed the edit and loaded the
    # author, and a bare refresh() expires every attribute including that
    # relationship — serializing would then lazy-load it mid-request.
    await session.commit()
    # A picture taken out of the comment goes once the edit has landed.
    attachments_service.delete_blobs(guild_context.guild_id, released_images)
    response = comments_service.serialize_comment(comment, viewer_id=current_user.id)
    return response


@router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    try:
        await comments_service.delete_comment(
            session,
            comment_id=comment_id,
            user=current_user,
            guild_id=guild_context.guild_id,
            guild_role=guild_context.role,
        )
    except comments_service.CommentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except comments_service.CommentPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except comments_service.CommentValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    await session.commit()
