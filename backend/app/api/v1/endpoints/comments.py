from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import select

from app.api.deps import GuildContext, RLSSessionDep, get_current_active_user, get_guild_membership
from app.db.session import reapply_rls_context
from app.models.document import Document
from app.models.initiative import Initiative, InitiativeMember
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.models.comment import Comment
from app.schemas.comment import (
    CommentAuthor,
    CommentCreate,
    CommentRead,
    CommentUpdate,
    MentionEntityType,
    MentionSuggestion,
    RecentActivityEntry,
)
from sqlalchemy.orm import selectinload
from app.services import comments as comments_service
from app.services.realtime import broadcast_event

router = APIRouter()
GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


@router.post("/", response_model=CommentRead, status_code=status.HTTP_201_CREATED)
async def create_comment(
    comment_in: CommentCreate,
    session: RLSSessionDep,
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
    await reapply_rls_context(session)
    await session.refresh(comment)
    response = CommentRead.model_validate(comment)
    await broadcast_event("comment", "created", response.model_dump(mode="json"))
    return response


@router.get("/recent", response_model=List[RecentActivityEntry])
async def recent_comments(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    limit: int = Query(default=10, ge=1, le=50),
) -> List[RecentActivityEntry]:
    """Return the most recent comments across the guild."""
    stmt = (
        select(Comment)
        .where(
            Comment.parent_comment_id.is_(None),
            Comment.guild_id == guild_context.guild_id,
        )
        .options(selectinload(Comment.author))
        .order_by(Comment.created_at.desc(), Comment.id.desc())
        .limit(limit)
    )
    result = await session.exec(stmt)
    comments = result.all()

    # Batch-load related task/document/project info
    task_ids = {c.task_id for c in comments if c.task_id}
    doc_ids = {c.document_id for c in comments if c.document_id}

    tasks_by_id: dict[int, Task] = {}
    projects_by_id: dict[int, Project] = {}
    docs_by_id: dict[int, Document] = {}

    if task_ids:
        task_result = await session.exec(select(Task).where(Task.id.in_(task_ids)))
        for task in task_result.all():
            tasks_by_id[task.id] = task

        project_ids = {t.project_id for t in tasks_by_id.values()}
        if project_ids:
            proj_result = await session.exec(select(Project).where(Project.id.in_(project_ids)))
            for proj in proj_result.all():
                projects_by_id[proj.id] = proj

    if doc_ids:
        doc_result = await session.exec(select(Document).where(Document.id.in_(doc_ids)))
        for doc in doc_result.all():
            docs_by_id[doc.id] = doc

    entries: List[RecentActivityEntry] = []
    for comment in comments:
        author = comment.author
        author_payload = CommentAuthor.model_validate(author) if author else None
        task = tasks_by_id.get(comment.task_id) if comment.task_id else None
        project = projects_by_id.get(task.project_id) if task else None
        document = docs_by_id.get(comment.document_id) if comment.document_id else None
        entries.append(
            RecentActivityEntry(
                comment_id=comment.id,
                content=comment.content,
                created_at=comment.created_at,
                author=author_payload,
                task_id=task.id if task else None,
                task_title=task.title if task else None,
                document_id=document.id if document else None,
                document_title=document.title if document else None,
                project_id=project.id if project else None,
                project_name=project.name if project else None,
            )
        )
    return entries


@router.get("/", response_model=List[CommentRead])
async def list_comments(
    session: RLSSessionDep,
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
        comment = await comments_service.update_comment(
            session,
            comment_id=comment_id,
            user=current_user,
            guild_id=guild_context.guild_id,
            content=comment_in.content,
        )
    except comments_service.CommentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except comments_service.CommentPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    # Note: Content validation (empty string) is handled by Pydantic schema (422).
    # CommentValidationError from service indicates data integrity issues (500).

    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(comment)
    response = CommentRead.model_validate(comment)
    await broadcast_event("comment", "updated", response.model_dump(mode="json"))
    return response


@router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    try:
        deleted_comment = await comments_service.delete_comment(
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
    await broadcast_event(
        "comment",
        "deleted",
        {
            "id": deleted_comment.id,
            "task_id": deleted_comment.task_id,
            "document_id": deleted_comment.document_id,
            "project_id": getattr(deleted_comment, "project_id", None),
        },
    )


@router.get("/mentions/search", response_model=List[MentionSuggestion])
async def search_mentionables(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    entity_type: MentionEntityType = Query(...),
    initiative_id: int = Query(..., gt=0),
    q: str = Query(default="", max_length=100),
) -> List[MentionSuggestion]:
    """Search for mentionable entities within an initiative."""
    guild_id = guild_context.guild_id
    query = q.strip().lower()
    suggestions: List[MentionSuggestion] = []
    limit = 10

    # Verify initiative belongs to guild
    init_stmt = select(Initiative).where(
        Initiative.id == initiative_id,
        Initiative.guild_id == guild_id,
    )
    init_result = await session.exec(init_stmt)
    initiative = init_result.one_or_none()
    if not initiative:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Initiative not found",
        )

    if entity_type == MentionEntityType.user:
        # Get users who are members of this initiative
        stmt = (
            select(User)
            .join(InitiativeMember, InitiativeMember.user_id == User.id)
            .where(
                InitiativeMember.initiative_id == initiative_id,
                User.is_active.is_(True),
            )
        )
        if query:
            stmt = stmt.where(
                (User.full_name.ilike(f"%{query}%")) | (User.email.ilike(f"%{query}%"))
            )
        stmt = stmt.limit(limit)
        result = await session.exec(stmt)
        users = result.all()
        for user in users:
            display = user.full_name or user.email
            suggestions.append(
                MentionSuggestion(
                    type=MentionEntityType.user,
                    id=user.id,
                    display_text=display,
                    subtitle=user.email if user.full_name else None,
                )
            )

    elif entity_type == MentionEntityType.task:
        # Get tasks from projects in this initiative
        stmt = (
            select(Task, Project.name)
            .join(Project, Project.id == Task.project_id)
            .where(
                Project.initiative_id == initiative_id,
                Task.is_archived.is_(False),
            )
        )
        if query:
            stmt = stmt.where(Task.title.ilike(f"%{query}%"))
        stmt = stmt.order_by(Task.updated_at.desc()).limit(limit)
        result = await session.exec(stmt)
        rows = result.all()
        for task, project_name in rows:
            suggestions.append(
                MentionSuggestion(
                    type=MentionEntityType.task,
                    id=task.id,
                    display_text=task.title,
                    subtitle=project_name,
                )
            )

    elif entity_type == MentionEntityType.doc:
        # Get documents in this initiative
        stmt = select(Document).where(
            Document.initiative_id == initiative_id,
            Document.is_template.is_(False),
        )
        if query:
            stmt = stmt.where(Document.title.ilike(f"%{query}%"))
        stmt = stmt.order_by(Document.updated_at.desc()).limit(limit)
        result = await session.exec(stmt)
        docs = result.all()
        for doc in docs:
            suggestions.append(
                MentionSuggestion(
                    type=MentionEntityType.doc,
                    id=doc.id,
                    display_text=doc.title,
                    subtitle=None,
                )
            )

    elif entity_type == MentionEntityType.project:
        # Get projects in this initiative
        stmt = select(Project).where(
            Project.initiative_id == initiative_id,
            Project.is_archived.is_(False),
            Project.is_template.is_(False),
        )
        if query:
            stmt = stmt.where(Project.name.ilike(f"%{query}%"))
        stmt = stmt.order_by(Project.updated_at.desc()).limit(limit)
        result = await session.exec(stmt)
        projects = result.all()
        for project in projects:
            suggestions.append(
                MentionSuggestion(
                    type=MentionEntityType.project,
                    id=project.id,
                    display_text=project.name,
                    subtitle=project.description[:50] if project.description else None,
                )
            )

    return suggestions
