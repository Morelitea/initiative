from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import String, and_, cast, func, or_
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
from app.models.tenant.document import Document
from app.models.tenant.initiative import Initiative, InitiativeMember
from app.models.tenant.project import Project
from app.models.tenant.task import Task
from app.models.platform.user import User, UserStatus
from app.services.permissions import (
    dac_scope_clause,
)
from app.schemas.tenant.comment import (
    CommentAuthor,
    CommentCreate,
    CommentRead,
    CommentUpdate,
    MentionEntityType,
    MentionSuggestion,
    MentionSuggestionListResponse,
    RecentActivityEntry,
)
from app.db.query import page_has_next, paginated_query
from app.services.tenant import comments as comments_service
from app.services.tenant import reactions as reactions_service
from app.services.realtime import broadcast_event
from app.core import usernames
from app.core.user_display import display_name, handle_of

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


@router.get("/mentions/search", response_model=MentionSuggestionListResponse)
async def search_mentionables(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    entity_type: MentionEntityType = Query(...),
    initiative_id: int = Query(..., gt=0),
    q: str = Query(default="", max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=0, le=100),
) -> MentionSuggestionListResponse:
    """Search for mentionable entities within an initiative.

    Paginated, same envelope as the member search endpoints. ``user``
    suggestions carry an avatar so the picker renders a face.
    """
    guild_id = guild_context.guild_id
    query = q.strip().lower()

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

    items: List[MentionSuggestion] = []
    total_count = 0
    actual_page = page

    if entity_type == MentionEntityType.user:
        shows_names = bool(guild_context.guild.show_member_names)
        base = (
            select(User)
            .join(InitiativeMember, InitiativeMember.user_id == User.id)
            .where(
                InitiativeMember.initiative_id == initiative_id,
                User.status == UserStatus.active,
            )
        )
        if query and (term := query.strip()):
            # The same rule as every other people search (the guild roster, the
            # initiative roster, the assignee picker): the handle always, the
            # name alongside it where the guild shows names, and a whole
            # ``foobar#1234`` narrowed to the one person who owns it.
            name_part, number = usernames.parse_handle(term)
            if number is not None:
                base = base.where(
                    func.lower(User.username) == name_part.lower(),
                    func.lpad(cast(User.discriminator, String), 4, "0").like(
                        f"{number}%"
                    ),
                )
            else:
                matches = User.username.ilike(f"%{name_part}%")
                if shows_names:
                    matches = or_(matches, User.full_name.ilike(f"%{name_part}%"))
                base = base.where(matches)
        count_stmt = select(func.count()).select_from(base.subquery())
        order = (User.full_name,) if shows_names else ()
        data_stmt = base.order_by(*order, User.username, User.discriminator, User.id)
        rows, total_count, actual_page = await paginated_query(
            session, data_stmt, count_stmt, page=page, page_size=page_size
        )
        for user in rows:
            display = display_name(user)
            items.append(
                MentionSuggestion(
                    type=MentionEntityType.user,
                    id=user.id,
                    display_text=display,
                    # The handle under the name, which is what tells two
                    # people with the same name apart. Nothing to add when the
                    # line above is already the handle.
                    subtitle=(
                        handle_of(user) if shows_names and user.full_name else None
                    ),
                    avatar_url=user.avatar_url,
                )
            )

    elif entity_type == MentionEntityType.task:
        base = (
            select(Task, Project.name)
            .join(Project, Project.id == Task.project_id)
            .where(
                Project.initiative_id == initiative_id,
                Task.is_archived.is_(False),
            )
        )
        if query:
            base = base.where(Task.title.ilike(f"%{query}%"))
        count_stmt = select(func.count()).select_from(base.subquery())
        data_stmt = base.order_by(Task.updated_at.desc())
        rows, total_count, actual_page = await paginated_query(
            session, data_stmt, count_stmt, page=page, page_size=page_size
        )
        for task, project_name in rows:
            items.append(
                MentionSuggestion(
                    type=MentionEntityType.task,
                    id=task.id,
                    display_text=task.title,
                    subtitle=project_name,
                )
            )

    elif entity_type == MentionEntityType.doc:
        base = select(Document).where(
            Document.initiative_id == initiative_id,
            Document.is_template.is_(False),
        )
        if query:
            base = base.where(Document.name.ilike(f"%{query}%"))
        count_stmt = select(func.count()).select_from(base.subquery())
        data_stmt = base.order_by(Document.updated_at.desc())
        rows, total_count, actual_page = await paginated_query(
            session, data_stmt, count_stmt, page=page, page_size=page_size
        )
        for doc in rows:
            items.append(
                MentionSuggestion(
                    type=MentionEntityType.doc,
                    id=doc.id,
                    display_text=doc.name,
                    subtitle=None,
                )
            )

    elif entity_type == MentionEntityType.project:
        base = select(Project).where(
            Project.initiative_id == initiative_id,
            Project.is_archived.is_(False),
            Project.is_template.is_(False),
        )
        if query:
            base = base.where(Project.name.ilike(f"%{query}%"))
        count_stmt = select(func.count()).select_from(base.subquery())
        data_stmt = base.order_by(Project.updated_at.desc())
        rows, total_count, actual_page = await paginated_query(
            session, data_stmt, count_stmt, page=page, page_size=page_size
        )
        for project in rows:
            items.append(
                MentionSuggestion(
                    type=MentionEntityType.project,
                    id=project.id,
                    display_text=project.name,
                    subtitle=project.description[:50] if project.description else None,
                )
            )

    return MentionSuggestionListResponse(
        items=items,
        total_count=total_count,
        page=actual_page,
        page_size=page_size,
        has_next=page_has_next(actual_page, page_size, total_count),
        has_prev=actual_page > 1,
    )
