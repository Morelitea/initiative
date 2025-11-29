from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import GuildContext, SessionDep, get_current_active_user, get_guild_membership
from app.models.user import User
from app.schemas.comment import CommentCreate, CommentRead
from app.services import comments as comments_service

router = APIRouter()
GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


@router.post("/", response_model=CommentRead, status_code=status.HTTP_201_CREATED)
async def create_comment(
    comment_in: CommentCreate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CommentRead:
    try:
        comment = await comments_service.create_comment(
            session,
            author=current_user,
            guild_id=guild_context.guild_id,
            guild_role=guild_context.role,
            content=comment_in.content,
            task_id=comment_in.task_id,
            document_id=comment_in.document_id,
            parent_comment_id=comment_in.parent_comment_id,
        )
    except comments_service.CommentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except comments_service.CommentPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except comments_service.CommentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await session.commit()
    await session.refresh(comment)
    return CommentRead.model_validate(comment)


@router.get("/", response_model=List[CommentRead])
async def list_comments(
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    task_id: Optional[int] = Query(default=None, gt=0),
    document_id: Optional[int] = Query(default=None, gt=0),
) -> List[CommentRead]:
    try:
        comments = await comments_service.list_comments(
            session,
            user=current_user,
            guild_id=guild_context.guild_id,
            guild_role=guild_context.role,
            task_id=task_id,
            document_id=document_id,
        )
    except comments_service.CommentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except comments_service.CommentPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except comments_service.CommentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return [CommentRead.model_validate(comment) for comment in comments]


@router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_id: int,
    session: SessionDep,
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except comments_service.CommentPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except comments_service.CommentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await session.commit()
