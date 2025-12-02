from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api.deps import (
    SessionDep,
    get_current_active_user,
    get_guild_membership,
    GuildContext,
    require_guild_roles,
)
from app.models.project import Project, ProjectPermission, ProjectPermissionLevel
from app.models.project_order import ProjectOrder
from app.models.project_activity import ProjectFavorite, RecentProjectView
from app.models.task import Task, TaskAssignee, TaskStatus, TaskStatusCategory
from app.models.comment import Comment
from app.models.initiative import Initiative, InitiativeMember, InitiativeRole
from app.models.user import User
from app.models.guild import GuildRole
from app.models.document import ProjectDocument
from app.services import notifications as notifications_service
from app.services import initiatives as initiatives_service
from app.services import documents as documents_service
from app.services import task_statuses as task_statuses_service
from app.services.realtime import broadcast_event
from app.schemas.project import (
    ProjectCreate,
    ProjectDuplicateRequest,
    ProjectPermissionCreate,
    ProjectPermissionRead,
    ProjectRead,
    ProjectTaskSummary,
    ProjectReorderRequest,
    ProjectUpdate,
    ProjectFavoriteStatus,
    ProjectRecentViewRead,
    ProjectActivityEntry,
    ProjectActivityResponse,
)
from app.schemas.comment import CommentAuthor
from app.schemas.initiative import serialize_initiative
from app.schemas.document import ProjectDocumentSummary, serialize_project_document_link

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]
GuildAdminContext = Annotated[GuildContext, Depends(require_guild_roles(GuildRole.admin))]

MAX_RECENT_PROJECTS = 20


def _project_documents(project: Project) -> List[ProjectDocumentSummary]:
    documents: List[ProjectDocumentSummary] = []
    for link in getattr(project, "document_links", []) or []:
        summary = serialize_project_document_link(link)
        if summary:
            documents.append(summary)
    documents.sort(key=lambda item: (item.title.lower(), item.document_id))
    return documents


async def _attach_task_summaries(session: SessionDep, projects: List[Project]) -> None:
    if not projects:
        return
    project_ids = [project.id for project in projects if project.id is not None]
    summary_map: dict[int, ProjectTaskSummary] = {}
    if project_ids:
        done_case = case((TaskStatus.category == TaskStatusCategory.done, 1), else_=0)
        stmt = (
            select(
                Task.project_id,
                func.count(Task.id),
                func.coalesce(func.sum(done_case), 0),
            )
            .join(Task.task_status)
            .where(Task.project_id.in_(tuple(project_ids)))
            .group_by(Task.project_id)
        )
        result = await session.exec(stmt)
        for project_id, total, completed in result.all():
            summary_map[int(project_id)] = ProjectTaskSummary(
                total=int(total or 0),
                completed=int(completed or 0),
            )

    for project in projects:
        summary = summary_map.get(project.id or 0, ProjectTaskSummary())
        setattr(project, "_task_summary", summary)


def _project_payload(project: Project) -> dict:
    payload = ProjectRead.model_validate(project)
    if project.initiative:
        payload.initiative = serialize_initiative(project.initiative)
    summary = getattr(project, "_task_summary", None)
    if not isinstance(summary, ProjectTaskSummary):
        summary = ProjectTaskSummary()
    payload = payload.model_copy(
        update={
            "documents": _project_documents(project),
            "task_summary": summary,
        }
    )
    return payload.model_dump(mode="json")


async def _get_project_or_404(project_id: int, session: SessionDep, guild_id: int | None = None) -> Project:
    statement = select(Project).where(Project.id == project_id).options(
        selectinload(Project.permissions).selectinload(ProjectPermission.user),
        selectinload(Project.owner),
        selectinload(Project.initiative).selectinload(Initiative.memberships).selectinload(InitiativeMember.user),
        selectinload(Project.document_links).selectinload(ProjectDocument.document),
    )
    if guild_id is not None:
        statement = statement.join(Project.initiative).where(Initiative.guild_id == guild_id)
    result = await session.exec(statement)
    project = result.one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


async def _get_initiative_or_404(initiative_id: int, session: SessionDep, guild_id: int | None = None) -> Initiative:
    result = await session.exec(
        select(Initiative)
        .where(Initiative.id == initiative_id)
        .options(selectinload(Initiative.memberships).selectinload(InitiativeMember.user))
    )
    initiative = result.one_or_none()
    if not initiative or (guild_id is not None and initiative.guild_id != guild_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Initiative not found")
    return initiative


def _permission_from_project(project: Project, user_id: int) -> ProjectPermission | None:
    permissions = getattr(project, "permissions", None)
    if not permissions:
        return None
    for permission in permissions:
        if permission.user_id == user_id:
            return permission
    return None


def _membership_from_project(project: Project, user_id: int) -> InitiativeMember | None:
    initiative = getattr(project, "initiative", None)
    if not initiative:
        return None
    memberships = getattr(initiative, "memberships", None)
    if not memberships:
        return None
    for membership in memberships:
        if membership.user_id == user_id:
            return membership
    return None


async def _get_initiative_membership(project: Project, user: User, session: SessionDep) -> InitiativeMember | None:
    cached = _membership_from_project(project, user.id)
    if cached:
        return cached
    if not project.initiative_id:
        return None
    stmt = select(InitiativeMember).where(
        InitiativeMember.initiative_id == project.initiative_id,
        InitiativeMember.user_id == user.id,
    )
    result = await session.exec(stmt)
    membership = result.one_or_none()
    if membership and project.initiative:
        project.initiative.memberships.append(membership)
    return membership


async def _get_project_permission(project: Project, user_id: int, session: SessionDep) -> ProjectPermission | None:
    cached = _permission_from_project(project, user_id)
    if cached:
        return cached
    stmt = select(ProjectPermission).where(
        ProjectPermission.project_id == project.id,
        ProjectPermission.user_id == user_id,
    )
    result = await session.exec(stmt)
    permission = result.one_or_none()
    if permission:
        project.permissions.append(permission)
    return permission


async def _ensure_user_in_initiative(initiative_id: int, user_id: int, session: SessionDep) -> None:
    stmt = select(InitiativeMember).where(
        InitiativeMember.initiative_id == initiative_id,
        InitiativeMember.user_id == user_id,
    )
    result = await session.exec(stmt)
    if not result.one_or_none():
        session.add(
            InitiativeMember(
                initiative_id=initiative_id,
                user_id=user_id,
                role=InitiativeRole.member,
            )
        )
        await session.flush()


def _ensure_not_archived(project: Project) -> None:
    if project.is_archived:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project is archived")


async def _duplicate_template_tasks(
    session: SessionDep,
    template: Project,
    new_project: Project,
    *,
    status_mapping: dict[int, int],
    fallback_status_ids: dict[TaskStatusCategory, int],
) -> None:
    task_stmt = (
        select(Task)
        .options(selectinload(Task.assignees), selectinload(Task.task_status))
        .where(Task.project_id == template.id)
        .order_by(Task.sort_order.asc(), Task.id.asc())
    )
    task_result = await session.exec(task_stmt)
    template_tasks = task_result.all()
    if not template_tasks:
        return

    for template_task in template_tasks:
        template_status_id = getattr(template_task, "task_status_id", None)
        mapped_status_id = None
        if template_status_id is not None:
            mapped_status_id = status_mapping.get(template_status_id)
        if mapped_status_id is None:
            category = getattr(getattr(template_task, "task_status", None), "category", None)
            if category is not None:
                mapped_status_id = fallback_status_ids.get(category)
        if mapped_status_id is None and fallback_status_ids:
            mapped_status_id = next(iter(fallback_status_ids.values()))
        new_task = Task(
            project_id=new_project.id,
            title=template_task.title,
            description=template_task.description,
            task_status_id=mapped_status_id,
            priority=template_task.priority,
            due_date=template_task.due_date,
            sort_order=template_task.sort_order,
        )
        session.add(new_task)
        await session.flush()
        if template_task.assignees:
            session.add_all(
                [
                    TaskAssignee(task_id=new_task.id, user_id=assignee.id)
                    for assignee in template_task.assignees
                ]
            )


def _matches_filters(project: Project, *, archived: Optional[bool], template: Optional[bool]) -> bool:
    if template is None:
        if project.is_template:
            return False
    elif project.is_template != template:
        return False

    if archived is None:
        return not project.is_archived
    return project.is_archived == archived


async def _visible_projects(
    session: SessionDep,
    current_user: User,
    *,
    guild_id: int,
    archived: Optional[bool],
    template: Optional[bool],
    is_guild_admin: bool,
) -> List[Project]:
    base_statement = (
        select(Project)
        .join(Project.initiative)
        .where(Initiative.guild_id == guild_id)
        .options(
            selectinload(Project.permissions).selectinload(ProjectPermission.user),
            selectinload(Project.owner),
            selectinload(Project.initiative).selectinload(Initiative.memberships).selectinload(InitiativeMember.user),
            selectinload(Project.document_links).selectinload(ProjectDocument.document),
        )
    )
    result = await session.exec(base_statement)
    all_projects = result.all()

    if is_guild_admin:
        return [project for project in all_projects if _matches_filters(project, archived=archived, template=template)]

    initiative_ids_result = await session.exec(
        select(InitiativeMember.initiative_id)
        .join(Initiative, Initiative.id == InitiativeMember.initiative_id)
        .where(
            InitiativeMember.user_id == current_user.id,
            Initiative.guild_id == guild_id,
        )
    )
    initiative_ids = {row for row in initiative_ids_result.all() if row is not None}

    visible_projects: List[Project] = []
    for project in all_projects:
        if not _matches_filters(project, archived=archived, template=template):
            continue
        if project.owner_id == current_user.id:
            visible_projects.append(project)
            continue
        if project.initiative_id in initiative_ids:
            visible_projects.append(project)
            continue
        permission = _permission_from_project(project, current_user.id)
        if permission:
            visible_projects.append(project)

    return visible_projects


async def _project_reads_with_order(
    session: SessionDep,
    current_user: User,
    projects: List[Project],
) -> List[ProjectRead]:
    if not projects:
        return []

    await _attach_task_summaries(session, projects)

    project_ids = [project.id for project in projects if project.id is not None]
    order_map: dict[int, float] = {}
    if project_ids:
        order_stmt = select(ProjectOrder).where(
            ProjectOrder.user_id == current_user.id,
            ProjectOrder.project_id.in_(tuple(project_ids)),
        )
        order_result = await session.exec(order_stmt)
        order_map = {order.project_id: order.sort_order for order in order_result.all()}
    favorite_ids, view_map = await _project_meta_for_user(session, current_user.id, project_ids)

    def sort_key(project: Project) -> tuple[bool, float, int]:
        order_value = order_map.get(project.id)
        return (
            order_value is None,
            float(order_value) if order_value is not None else 0.0,
            project.id or 0,
        )

    sorted_projects = sorted(projects, key=sort_key)

    payloads: List[ProjectRead] = []
    for project in sorted_projects:
        payloads.append(
            _build_project_payload(
                project,
                sort_order=order_map.get(project.id),
                favorite_ids=favorite_ids,
                view_map=view_map,
            )
        )
    return payloads


async def _project_meta_for_user(
    session: SessionDep,
    user_id: int,
    project_ids: List[int],
) -> tuple[set[int], dict[int, datetime]]:
    if not project_ids:
        return set(), {}
    fav_stmt = select(ProjectFavorite.project_id).where(
        ProjectFavorite.user_id == user_id,
        ProjectFavorite.project_id.in_(tuple(project_ids)),
    )
    fav_result = await session.exec(fav_stmt)
    favorite_rows = fav_result.all()
    favorite_ids = {
        row if isinstance(row, int) else row[0]  # type: ignore[index]
        for row in favorite_rows
    }

    view_stmt = select(RecentProjectView.project_id, RecentProjectView.last_viewed_at).where(
        RecentProjectView.user_id == user_id,
        RecentProjectView.project_id.in_(tuple(project_ids)),
    )
    view_result = await session.exec(view_stmt)
    view_rows = view_result.all()
    view_map: dict[int, datetime] = {}
    for row in view_rows:
        if isinstance(row, tuple):
            project_id, last_viewed_at = row
        else:
            project_id, last_viewed_at = row.project_id, row.last_viewed_at  # type: ignore[attr-defined]
        view_map[int(project_id)] = last_viewed_at
    return favorite_ids, view_map


async def _projects_by_ids(
    session: SessionDep,
    project_ids: List[int],
    *,
    guild_id: int,
) -> dict[int, Project]:
    if not project_ids:
        return {}
    stmt = (
        select(Project)
        .join(Project.initiative)
        .where(
            Project.id.in_(tuple(project_ids)),
            Initiative.guild_id == guild_id,
        )
        .options(
            selectinload(Project.permissions).selectinload(ProjectPermission.user),
            selectinload(Project.owner),
            selectinload(Project.initiative).selectinload(Initiative.memberships).selectinload(InitiativeMember.user),
            selectinload(Project.document_links).selectinload(ProjectDocument.document),
        )
    )
    result = await session.exec(stmt)
    projects = result.all()
    return {project.id: project for project in projects if project.id is not None}


def _build_project_payload(
    project: Project,
    *,
    sort_order: Optional[float],
    favorite_ids: set[int],
    view_map: dict[int, datetime],
) -> ProjectRead:
    payload = ProjectRead.model_validate(project)
    if project.initiative:
        payload.initiative = serialize_initiative(project.initiative)
    project_id = project.id or 0
    summary = getattr(project, "_task_summary", None)
    if not isinstance(summary, ProjectTaskSummary):
        summary = ProjectTaskSummary()
    return payload.model_copy(
        update={
            "sort_order": sort_order,
            "is_favorited": project_id in favorite_ids,
            "last_viewed_at": view_map.get(project_id),
            "documents": _project_documents(project),
            "task_summary": summary,
        }
    )


async def _record_recent_project_view(
    session: SessionDep,
    *,
    user_id: int,
    project_id: int,
) -> RecentProjectView:
    stmt = select(RecentProjectView).where(
        RecentProjectView.user_id == user_id,
        RecentProjectView.project_id == project_id,
    )
    result = await session.exec(stmt)
    record = result.one_or_none()
    now = datetime.now(timezone.utc)
    if record:
        record.last_viewed_at = now
    else:
        record = RecentProjectView(user_id=user_id, project_id=project_id, last_viewed_at=now)
        session.add(record)
    await session.commit()
    await session.refresh(record)

    prune_stmt = (
        select(RecentProjectView)
        .where(RecentProjectView.user_id == user_id)
        .order_by(RecentProjectView.last_viewed_at.desc())
        .offset(MAX_RECENT_PROJECTS)
    )
    prune_result = await session.exec(prune_stmt)
    stale_records = prune_result.all()
    if stale_records:
        for stale in stale_records:
            await session.delete(stale)
        await session.commit()
    return record


async def _delete_recent_project_view(
    session: SessionDep,
    *,
    user_id: int,
    project_id: int,
) -> None:
    stmt = select(RecentProjectView).where(
        RecentProjectView.user_id == user_id,
        RecentProjectView.project_id == project_id,
    )
    result = await session.exec(stmt)
    record = result.one_or_none()
    if record:
        await session.delete(record)
        await session.commit()


async def _set_favorite_state(
    session: SessionDep,
    *,
    user_id: int,
    project_id: int,
    favorited: bool,
) -> bool:
    stmt = select(ProjectFavorite).where(
        ProjectFavorite.user_id == user_id,
        ProjectFavorite.project_id == project_id,
    )
    result = await session.exec(stmt)
    record = result.one_or_none()
    if favorited:
        if record is None:
            session.add(ProjectFavorite(user_id=user_id, project_id=project_id))
            await session.commit()
        return True

    if record:
        await session.delete(record)
        await session.commit()
    return False


async def _project_read_for_user(
    session: SessionDep,
    current_user: User,
    project: Project,
) -> ProjectRead:
    payloads = await _project_reads_with_order(session, current_user, [project])
    if payloads:
        return payloads[0]
    project_ids = [project.id] if project.id is not None else []
    favorite_ids, view_map = await _project_meta_for_user(session, current_user.id, project_ids)
    await _attach_task_summaries(session, [project])
    return _build_project_payload(
        project,
        sort_order=None,
        favorite_ids=favorite_ids,
        view_map=view_map,
    )


async def _require_project_membership(
    project: Project,
    current_user: User,
    session: SessionDep,
    *,
    access: str = "read",
    require_manager: bool = False,
    guild_role: GuildRole | None = None,
):
    if guild_role == GuildRole.admin:
        return

    initiative_membership = await _get_initiative_membership(project, current_user, session)
    permission = await _get_project_permission(project, current_user.id, session)
    is_owner = project.owner_id == current_user.id
    is_initiative_pm = initiative_membership and initiative_membership.role == InitiativeRole.project_manager

    if access == "read":
        if is_owner or initiative_membership or permission:
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not part of this project's initiative")

    has_write = (
        is_owner
        or is_initiative_pm
        or permission is not None
        or bool(project.members_can_write and initiative_membership)
    )
    if not has_write:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Write access denied for your role")

    if require_manager and not (is_owner or is_initiative_pm or guild_role == GuildRole.admin):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Initiative manager role required")


@router.get("/", response_model=List[ProjectRead])
async def list_projects(
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    archived: Optional[bool] = Query(default=None),
    template: Optional[bool] = Query(default=None),
) -> List[ProjectRead]:
    projects = await _visible_projects(
        session,
        current_user,
        guild_id=guild_context.guild_id,
        archived=archived,
        template=template,
        is_guild_admin=guild_context.role == GuildRole.admin,
    )
    return await _project_reads_with_order(session, current_user, projects)


@router.post("/", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_in: ProjectCreate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRead:
    template_project: Project | None = None
    if project_in.template_id is not None:
        template_project = await _get_project_or_404(project_in.template_id, session, guild_context.guild_id)
        if not template_project.is_template:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected template is invalid")
        await _require_project_membership(
            template_project,
            current_user,
            session,
            access="read",
            guild_role=guild_context.role,
        )

    owner_id = project_in.owner_id or current_user.id
    icon_value = project_in.icon if project_in.icon is not None else (template_project.icon if template_project else None)
    description_value = (
        project_in.description
        if project_in.description is not None
        else (template_project.description if template_project else None)
    )
    initiative_id = (
        project_in.initiative_id
        if getattr(project_in, "initiative_id", None) is not None
        else (template_project.initiative_id if template_project else None)
    )
    members_can_write_value = project_in.members_can_write
    if "members_can_write" not in project_in.model_fields_set and template_project:
        members_can_write_value = template_project.members_can_write
    if initiative_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Initiative is required")
    initiative = await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)
    if guild_context.role != GuildRole.admin:
        membership = await initiatives_service.get_initiative_membership(
            session,
            initiative_id=initiative_id,
            user_id=current_user.id,
        )
        if not membership or membership.role != InitiativeRole.project_manager:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Initiative manager role required")
    await _ensure_user_in_initiative(initiative_id, owner_id, session)
    project = Project(
        name=project_in.name,
        icon=icon_value,
        description=description_value,
        owner_id=owner_id,
        initiative_id=initiative_id,
        members_can_write=members_can_write_value,
        is_template=project_in.is_template,
    )

    session.add(project)
    await session.flush()

    status_mapping: dict[int, int] = {}
    if template_project:
        status_mapping = await task_statuses_service.clone_statuses(
            session,
            source_project_id=template_project.id,
            target_project_id=project.id,
        )

    statuses = await task_statuses_service.ensure_default_statuses(session, project.id)
    fallback_status_ids = {status.category: status.id for status in statuses}

    owner_permission = ProjectPermission(
        project_id=project.id,
        user_id=owner_id,
        level=ProjectPermissionLevel.owner,
    )
    session.add(owner_permission)

    if template_project:
        await _duplicate_template_tasks(
            session,
            template_project,
            project,
            status_mapping=status_mapping,
            fallback_status_ids=fallback_status_ids,
        )

    await session.commit()

    project = await _get_project_or_404(project.id, session, guild_context.guild_id)
    if project.initiative_id and project.initiative:
        for membership in project.initiative.memberships:
            member = membership.user
            if not member or member.id == current_user.id:
                continue
            await notifications_service.notify_project_added(
                session,
                member,
                initiative_name=project.initiative.name,
                project_name=project.name,
                project_id=project.id,
                initiative_id=project.initiative.id,
            )
    await _attach_task_summaries(session, [project])
    await broadcast_event("project", "created", _project_payload(project))
    return await _project_read_for_user(session, current_user, project)


@router.post("/{project_id}/archive", response_model=ProjectRead)
async def archive_project(
    project_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRead:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="write",
        require_manager=True,
        guild_role=guild_context.role,
    )
    if not project.is_archived:
        project.is_archived = True
        project.archived_at = datetime.now(timezone.utc)
        session.add(project)
        await session.commit()
    updated = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _attach_task_summaries(session, [updated])
    await broadcast_event("project", "updated", _project_payload(updated))
    return await _project_read_for_user(session, current_user, updated)


@router.post("/{project_id}/duplicate", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def duplicate_project(
    project_id: int,
    duplicate_in: ProjectDuplicateRequest,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRead:
    source_project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        source_project,
        current_user,
        session,
        access="read",
        require_manager=True,
        guild_role=guild_context.role,
    )

    owner_id = current_user.id
    initiative_id = source_project.initiative_id
    if initiative_id is not None:
        await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)
        await _ensure_user_in_initiative(initiative_id, owner_id, session)

    new_name = (
        duplicate_in.name.strip()
        if duplicate_in.name and duplicate_in.name.strip()
        else f"{source_project.name} copy"
    )
    new_project = Project(
        name=new_name,
        icon=source_project.icon,
        description=source_project.description,
        owner_id=owner_id,
        initiative_id=initiative_id,
        members_can_write=source_project.members_can_write,
        is_template=False,
    )

    session.add(new_project)
    await session.flush()

    session.add(
        ProjectPermission(
            project_id=new_project.id,
            user_id=owner_id,
            level=ProjectPermissionLevel.owner,
        )
    )

    await _duplicate_template_tasks(session, source_project, new_project)
    await session.commit()

    new_project = await _get_project_or_404(new_project.id, session, guild_context.guild_id)
    if new_project.initiative_id and new_project.initiative:
        for membership in new_project.initiative.memberships:
            member = membership.user
            if not member or member.id == current_user.id:
                continue
            await notifications_service.notify_project_added(
                session,
                member,
                initiative_name=new_project.initiative.name,
                project_name=new_project.name,
                project_id=new_project.id,
                initiative_id=new_project.initiative.id,
            )
    await _attach_task_summaries(session, [new_project])
    await broadcast_event("project", "created", _project_payload(new_project))
    return await _project_read_for_user(session, current_user, new_project)


@router.post("/{project_id}/unarchive", response_model=ProjectRead)
async def unarchive_project(
    project_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRead:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="write",
        require_manager=True,
        guild_role=guild_context.role,
    )
    if project.is_archived:
        project.is_archived = False
        project.archived_at = None
        session.add(project)
        await session.commit()
    updated = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _attach_task_summaries(session, [updated])
    await broadcast_event("project", "updated", _project_payload(updated))
    return await _project_read_for_user(session, current_user, updated)


@router.get("/recent", response_model=List[ProjectRead])
async def recent_projects(
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[ProjectRead]:
    stmt = (
        select(RecentProjectView)
        .where(RecentProjectView.user_id == current_user.id)
        .order_by(RecentProjectView.last_viewed_at.desc())
        .limit(MAX_RECENT_PROJECTS)
    )
    result = await session.exec(stmt)
    records = result.all()
    if not records:
        return []
    project_ids = [record.project_id for record in records]
    project_map = await _projects_by_ids(session, project_ids, guild_id=guild_context.guild_id)
    favorite_ids, view_map = await _project_meta_for_user(session, current_user.id, project_ids)

    payloads: List[ProjectRead] = []
    for record in records:
        project = project_map.get(record.project_id)
        if not project:
            continue
        try:
            await _require_project_membership(
                project,
                current_user,
                session,
                access="read",
                guild_role=guild_context.role,
            )
        except HTTPException:
            continue
        payloads.append(
            _build_project_payload(
                project,
                sort_order=None,
                favorite_ids=favorite_ids,
                view_map=view_map,
            )
        )
    return payloads


@router.get("/favorites", response_model=List[ProjectRead])
async def favorite_projects(
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[ProjectRead]:
    stmt = (
        select(ProjectFavorite)
        .where(ProjectFavorite.user_id == current_user.id)
        .order_by(ProjectFavorite.created_at.desc())
    )
    result = await session.exec(stmt)
    favorites = result.all()
    if not favorites:
        return []
    project_ids = [favorite.project_id for favorite in favorites]
    project_map = await _projects_by_ids(session, project_ids, guild_id=guild_context.guild_id)
    favorite_ids, view_map = await _project_meta_for_user(session, current_user.id, project_ids)

    payloads: List[ProjectRead] = []
    for favorite in favorites:
        project = project_map.get(favorite.project_id)
        if not project:
            continue
        try:
            await _require_project_membership(
                project,
                current_user,
                session,
                access="read",
                guild_role=guild_context.role,
            )
        except HTTPException:
            continue
        payloads.append(
            _build_project_payload(
                project,
                sort_order=None,
                favorite_ids=favorite_ids,
                view_map=view_map,
            )
        )
    return payloads


@router.post("/{project_id}/view", response_model=ProjectRecentViewRead)
async def record_project_view(
    project_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRecentViewRead:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="read",
        guild_role=guild_context.role,
    )
    record = await _record_recent_project_view(session, user_id=current_user.id, project_id=project.id)
    return ProjectRecentViewRead(project_id=project.id, last_viewed_at=record.last_viewed_at)


@router.delete("/{project_id}/view", status_code=status.HTTP_204_NO_CONTENT)
async def clear_project_view(
    project_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="read",
        guild_role=guild_context.role,
    )
    await _delete_recent_project_view(session, user_id=current_user.id, project_id=project.id)


@router.post("/{project_id}/favorite", response_model=ProjectFavoriteStatus)
async def favorite_project(
    project_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectFavoriteStatus:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="read",
        guild_role=guild_context.role,
    )
    await _set_favorite_state(session, user_id=current_user.id, project_id=project.id, favorited=True)
    return ProjectFavoriteStatus(project_id=project.id, is_favorited=True)


@router.delete("/{project_id}/favorite", response_model=ProjectFavoriteStatus)
async def unfavorite_project(
    project_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectFavoriteStatus:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="read",
        guild_role=guild_context.role,
    )
    await _set_favorite_state(session, user_id=current_user.id, project_id=project.id, favorited=False)
    return ProjectFavoriteStatus(project_id=project.id, is_favorited=False)


@router.get("/{project_id}/activity", response_model=ProjectActivityResponse)
async def project_activity_feed(
    project_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=20),
) -> ProjectActivityResponse:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="read",
        guild_role=guild_context.role,
    )
    offset = (page - 1) * page_size
    stmt = (
        select(Comment, Task)
        .join(Task, Comment.task_id == Task.id)
        .where(Task.project_id == project.id)
        .options(selectinload(Comment.author))
        .order_by(Comment.created_at.desc(), Comment.id.desc())
        .limit(page_size + 1)
        .offset(offset)
    )
    result = await session.exec(stmt)
    rows = result.all()
    has_next = len(rows) > page_size
    entries: list[ProjectActivityEntry] = []
    for comment, task in rows[:page_size]:
        author = comment.author
        author_payload = CommentAuthor.model_validate(author) if author else None
        entries.append(
            ProjectActivityEntry(
                comment_id=comment.id,
                content=comment.content,
                created_at=comment.created_at,
                author=author_payload,
                task_id=task.id,
                task_title=task.title,
            )
        )
    next_page = page + 1 if has_next else None
    return ProjectActivityResponse(items=entries, next_page=next_page, project_id=project.id)


@router.get("/{project_id}", response_model=ProjectRead)
async def read_project(
    project_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRead:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="read",
        guild_role=guild_context.role,
    )
    return await _project_read_for_user(session, current_user, project)


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: int,
    project_in: ProjectUpdate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRead:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="write",
        require_manager=True,
        guild_role=guild_context.role,
    )
    _ensure_not_archived(project)
    previous_initiative_id = project.initiative_id

    update_data = project_in.dict(exclude_unset=True)
    pinned_sentinel = object()
    pinned_value = update_data.pop("pinned", pinned_sentinel)
    if pinned_value is not pinned_sentinel:
        if guild_context.role != GuildRole.admin:
            initiative_membership = await _get_initiative_membership(project, current_user, session)
            if not initiative_membership or initiative_membership.role != InitiativeRole.project_manager:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Initiative manager role required to pin projects",
                )
        project.pinned_at = datetime.now(timezone.utc) if bool(pinned_value) else None

    if "initiative_id" in update_data:
        new_initiative_id = update_data.pop("initiative_id")
        if new_initiative_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Initiatives are required")
        if new_initiative_id != project.initiative_id:
            await _get_initiative_or_404(new_initiative_id, session, guild_context.guild_id)
            if guild_context.role != GuildRole.admin:
                membership = await initiatives_service.get_initiative_membership(
                    session,
                    initiative_id=new_initiative_id,
                    user_id=current_user.id,
                )
                if not membership or membership.role != InitiativeRole.project_manager:
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Initiative manager role required")
            await _ensure_user_in_initiative(new_initiative_id, project.owner_id, session)
            project.initiative_id = new_initiative_id
        if new_initiative_id != previous_initiative_id:
            for permission in list(project.permissions):
                if permission.user_id != project.owner_id:
                    await session.delete(permission)
            project.permissions = [perm for perm in project.permissions if perm.user_id == project.owner_id]
    for field, value in update_data.items():
        setattr(project, field, value)
    project.updated_at = datetime.now(timezone.utc)

    session.add(project)
    await session.commit()
    project = await _get_project_or_404(project.id, session, guild_context.guild_id)
    if (
        project.initiative_id
        and project.initiative
        and project.initiative_id != previous_initiative_id
    ):
        for membership in project.initiative.memberships:
            member = membership.user
            if not member or member.id == current_user.id:
                continue
            await notifications_service.notify_project_added(
                session,
                member,
                initiative_name=project.initiative.name,
                project_name=project.name,
                project_id=project.id,
                initiative_id=project.initiative.id,
            )
    await _attach_task_summaries(session, [project])
    await broadcast_event("project", "updated", _project_payload(project))
    return await _project_read_for_user(session, current_user, project)


@router.post("/{project_id}/documents/{document_id}", response_model=ProjectRead)
async def attach_project_document(
    project_id: int,
    document_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRead:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="write",
        guild_role=guild_context.role,
    )
    _ensure_not_archived(project)
    document = await documents_service.get_document(
        session,
        document_id=document_id,
        guild_id=guild_context.guild_id,
    )
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if document.initiative_id != project.initiative_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document belongs to a different initiative")
    await documents_service.attach_document_to_project(
        session,
        document=document,
        project=project,
        user_id=current_user.id,
    )
    updated_project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _attach_task_summaries(session, [updated_project])
    await broadcast_event("project", "updated", _project_payload(updated_project))
    return await _project_read_for_user(session, current_user, updated_project)


@router.delete("/{project_id}/documents/{document_id}", response_model=ProjectRead)
async def detach_project_document(
    project_id: int,
    document_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRead:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="write",
        guild_role=guild_context.role,
    )
    _ensure_not_archived(project)
    document = await documents_service.get_document(
        session,
        document_id=document_id,
        guild_id=guild_context.guild_id,
    )
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if document.initiative_id != project.initiative_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document belongs to a different initiative")
    await documents_service.detach_document_from_project(
        session,
        document_id=document.id,
        project_id=project.id,
    )
    updated_project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _attach_task_summaries(session, [updated_project])
    await broadcast_event("project", "updated", _project_payload(updated_project))
    return await _project_read_for_user(session, current_user, updated_project)


@router.post("/{project_id}/members", response_model=ProjectPermissionRead, status_code=status.HTTP_201_CREATED)
async def add_project_member(
    project_id: int,
    member_in: ProjectPermissionCreate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectPermission:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="write",
        require_manager=True,
        guild_role=guild_context.role,
    )
    _ensure_not_archived(project)
    if member_in.level == ProjectPermissionLevel.owner:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot assign owner permission")
    if member_in.user_id == project.owner_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Owner already has full access")
    if project.initiative_id:
        await _ensure_user_in_initiative(project.initiative_id, member_in.user_id, session)

    existing = await _get_project_permission(project, member_in.user_id, session)
    if existing:
        existing.level = member_in.level
        session.add(existing)
        await session.commit()
        await session.refresh(existing)
        return existing

    permission = ProjectPermission(
        project_id=project_id,
        user_id=member_in.user_id,
        level=member_in.level,
    )
    session.add(permission)
    await session.commit()
    await session.refresh(permission)
    return permission


@router.delete("/{project_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_project_member(
    project_id: int,
    user_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="write",
        require_manager=True,
        guild_role=guild_context.role,
    )
    _ensure_not_archived(project)
    if user_id == project.owner_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove the project owner")
    permission = await _get_project_permission(project, user_id, session)
    if not permission:
        return
    await session.delete(permission)
    await session.commit()


@router.post("/reorder", response_model=List[ProjectRead])
async def reorder_projects(
    reorder_in: ProjectReorderRequest,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[ProjectRead]:
    visible_projects = await _visible_projects(
        session,
        current_user,
        guild_id=guild_context.guild_id,
        archived=None,
        template=None,
        is_guild_admin=guild_context.role == GuildRole.admin,
    )
    if not visible_projects:
        return []

    current_payloads = await _project_reads_with_order(session, current_user, visible_projects)
    current_ids = [project.id for project in current_payloads if project.id is not None]
    if not current_ids:
        return current_payloads

    valid_ids = set(current_ids)
    seen: set[int] = set()
    requested_ids: List[int] = []
    for project_id in reorder_in.project_ids:
        if project_id in valid_ids and project_id not in seen:
            seen.add(project_id)
            requested_ids.append(project_id)

    final_order: List[int] = requested_ids[:]
    for project_id in current_ids:
        if project_id not in seen:
            seen.add(project_id)
            final_order.append(project_id)

    if final_order == current_ids or not final_order:
        return current_payloads

    order_stmt = select(ProjectOrder).where(
        ProjectOrder.user_id == current_user.id,
        ProjectOrder.project_id.in_(tuple(final_order)),
    )
    existing_orders_result = await session.exec(order_stmt)
    existing_orders = {order.project_id: order for order in existing_orders_result.all()}

    for index, project_id in enumerate(final_order):
        sort_value = float(index)
        order = existing_orders.get(project_id)
        if order:
            order.sort_order = sort_value
        else:
            order = ProjectOrder(user_id=current_user.id, project_id=project_id, sort_order=sort_value)
        session.add(order)

    await session.commit()
    return await _project_reads_with_order(session, current_user, visible_projects)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: int,
    session: SessionDep,
    guild_context: GuildAdminContext,
) -> None:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await session.delete(project)
    await session.commit()
    await broadcast_event("project", "deleted", {"id": project_id})
