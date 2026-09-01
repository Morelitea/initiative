from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api.deps import (
    IncludeDeletedDep,
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.reactions import ReactionTarget
from app.core.tools import Tool
from app.models.tenant.comment import Comment
from app.models.tenant.initiative import Initiative
from app.models.tenant.project import Project
from app.models.tenant.task import Task
from app.models.platform.user import User
from app.services.permissions import (
    dac_scope_clause,
)
from app.schemas.tenant.comment import (
    CommentAuthor,
    CommentCreate,
    CommentRead,
    CommentUpdate,
    RecentActivityEntry,
)
from app.services.tenant import comments as comments_service
from app.services.tenant import reactions as reactions_service
from app.services.realtime import broadcast_event

router = APIRouter()
GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


async def _broadcast_comment(session, guild_id: int, comment, action: str) -> None:
    """Emit a content-free comment signal to the comment's initiative room.

    A comment hangs off a task (→ project → initiative) or a tool entity
    (→ initiative); the parent is resolved within the guild-routed session, so
    the ``(guild_id, initiative_id)`` room is guild-safe (initiative ids are
    per-guild-schema). The automatic context replay keeps the lookup under the
    guild context after the commit. The client refetches through the RLS + DAC
    gated REST path — the bus carries ids only. A parent that names no
    initiative (a guild-level calendar) has no room, so nothing is emitted.
    """
    ids: dict = {"comment_id": comment.id}
    for column in comments_service.COMMENT_PARENT_COLUMNS:
        ids[column] = getattr(comment, column)
    if comment.task_id is not None:
        row = (
            await session.exec(
                select(Project.id, Project.initiative_id)
                .join(Task, Task.project_id == Project.id)
                .where(Task.id == comment.task_id)
            )
        ).one_or_none()
        if row is None:
            return
        ids["project_id"], initiative_id = row
    else:
        initiative_id = await comments_service.initiative_of_comment(session, comment)
    if initiative_id is None:
        return
    await broadcast_event(guild_id, initiative_id, "comment", action, ids)


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
    await session.refresh(comment)
    response = comments_service.serialize_comment(comment, viewer_id=current_user.id)
    await _broadcast_comment(session, guild_context.guild_id, comment, "created")
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
    user_id = current_user.id
    guild_id = guild_context.guild_id

    conditions = [
        Comment.parent_comment_id.is_(None),
        Comment.guild_id == guild_id,
    ]
    # A comment is reached through its parent — the task's project, or the
    # tool entity itself — so the sharing gate is applied per kind, each leg a
    # subquery over the parent table (which also drops trashed parents via the
    # session's soft-delete filter). Each clause is a no-op for a request that
    # reaches the whole guild, leaving only "attached to some parent".
    legs = [
        and_(
            Comment.task_id.isnot(None),
            Comment.task_id.in_(
                select(Task.id)
                .join(Project, Project.id == Task.project_id)
                .where(
                    dac_scope_clause(
                        Tool.project, Project.id, user_id, guild_id=guild_id
                    )
                )
            ),
        )
    ]
    for tool, target in comments_service.TOOL_COMMENT_TARGETS.items():
        model = target.model
        fk = getattr(Comment, target.column)
        # The entity's own comment switch gates its thread, so it gates the
        # feed too.
        parent_ids = select(model.id).where(
            dac_scope_clause(tool, model.id, user_id, guild_id=guild_id),
            model.comments_disabled.is_(False),
        )
        if target.feature_disabled is not None:
            # The tool's master switch gates the thread, so it gates the feed
            # too. A parent that names no initiative (a guild calendar) has no
            # switch to answer to.
            parent_ids = parent_ids.where(
                or_(
                    model.initiative_id.is_(None),
                    model.initiative_id.in_(
                        select(Initiative.id).where(
                            getattr(Initiative, tool.view_permission).is_(True)
                        )
                    ),
                )
            )
        legs.append(and_(fk.isnot(None), fk.in_(parent_ids)))
    conditions.append(or_(*legs))

    stmt = (
        select(Comment)
        .where(*conditions)
        .options(selectinload(Comment.author))
        .order_by(Comment.created_at.desc(), Comment.id.desc())
        .limit(limit)
    )
    result = await session.exec(stmt)
    comments = result.all()

    # Batch-load the parents the rows point at
    task_ids = {c.task_id for c in comments if c.task_id}
    tasks_by_id: dict[int, Task] = {}
    projects_by_id: dict[int, Project] = {}
    if task_ids:
        task_result = await session.exec(select(Task).where(Task.id.in_(task_ids)))
        for task in task_result.all():
            tasks_by_id[task.id] = task  # ty: ignore[invalid-assignment] — persisted row, id is set

        project_ids = {t.project_id for t in tasks_by_id.values()}
        if project_ids:
            proj_result = await session.exec(
                select(Project).where(Project.id.in_(project_ids))
            )
            for proj in proj_result.all():
                projects_by_id[proj.id] = proj  # ty: ignore[invalid-assignment] — persisted row, id is set

    rows_by_tool: dict[Tool, dict] = {}
    for tool, target in comments_service.TOOL_COMMENT_TARGETS.items():
        ids = {
            value for c in comments if (value := getattr(c, target.column)) is not None
        }
        if not ids:
            rows_by_tool[tool] = {}
            continue
        loaded = await session.exec(
            select(target.model).where(target.model.id.in_(ids))
        )
        rows_by_tool[tool] = {row.id: row for row in loaded.all()}

    # The feed's chips, in one query for the whole page rather than one per row.
    reactions_by_comment = await reactions_service.load_reactions(
        session,
        target=ReactionTarget.comment,
        target_ids=[c.id for c in comments],
    )

    entries: List[RecentActivityEntry] = []
    for comment in comments:
        author = comment.author
        author_payload = CommentAuthor.model_validate(author) if author else None
        fields: dict = {
            "comment_id": comment.id,
            "content": comment.content,
            "created_at": comment.created_at,
            "author": author_payload,
            "reactions": reactions_service.summarize(
                reactions_by_comment.get(comment.id, []), viewer_id=user_id
            ),
        }
        if comment.task_id:
            task = tasks_by_id.get(comment.task_id)
            project = projects_by_id.get(task.project_id) if task else None
            fields.update(
                task_id=task.id if task else None,
                task_title=task.title if task else None,
                project_id=project.id if project else None,
                project_name=project.name if project else None,
                entity_type="task",
                entity_id=comment.task_id,
                entity_name=task.title if task else None,
                initiative_id=project.initiative_id if project else None,
            )
        else:
            for tool, target in comments_service.TOOL_COMMENT_TARGETS.items():
                value = getattr(comment, target.column)
                if value is None:
                    continue
                row = rows_by_tool[tool].get(value)
                fields.update(
                    entity_type=tool.value,
                    entity_id=value,
                    entity_name=row.name if row else None,
                    initiative_id=row.initiative_id if row else None,
                )
                if tool is Tool.document:
                    fields.update(
                        document_id=value,
                        document_name=row.name if row else None,
                    )
                elif tool is Tool.project:
                    fields.update(
                        project_id=value,
                        project_name=row.name if row else None,
                    )
                break
        entries.append(RecentActivityEntry(**fields))
    return entries


@router.get("/", response_model=List[CommentRead])
async def list_comments(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    task_id: Optional[int] = Query(default=None, gt=0),
    document_id: Optional[int] = Query(default=None, gt=0),
    project_id: Optional[int] = Query(default=None, gt=0),
    queue_id: Optional[int] = Query(default=None, gt=0),
    counter_group_id: Optional[int] = Query(default=None, gt=0),
    calendar_id: Optional[int] = Query(default=None, gt=0),
    dashboard_id: Optional[int] = Query(default=None, gt=0),
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
        comments_service.serialize_comment(comment, viewer_id=current_user.id)
        for comment in comments
    ]


@router.get("/{comment_id}", response_model=CommentRead)
async def read_comment(
    comment_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
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
    return comments_service.serialize_comment(comment, viewer_id=current_user.id)


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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except comments_service.CommentPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    # Note: Content validation (empty string) is handled by Pydantic schema (422).
    # CommentValidationError from service indicates data integrity issues (500).

    await session.commit()
    await session.refresh(comment)
    response = comments_service.serialize_comment(comment, viewer_id=current_user.id)
    await _broadcast_comment(session, guild_context.guild_id, comment, "updated")
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
    await _broadcast_comment(
        session, guild_context.guild_id, deleted_comment, "deleted"
    )
