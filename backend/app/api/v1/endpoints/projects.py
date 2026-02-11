from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func
from sqlalchemy.orm import selectinload
from sqlalchemy import delete as sa_delete
from sqlmodel import select

from app.api.deps import (
    RLSSessionDep,
    SessionDep,
    get_current_active_user,
    get_guild_membership,
    GuildContext,
    require_guild_roles,
)
from app.db.session import reapply_rls_context
from app.models.project import Project, ProjectPermission, ProjectPermissionLevel, ProjectRolePermission
from app.models.project_order import ProjectOrder
from app.models.project_activity import ProjectFavorite, RecentProjectView
from app.models.task import Task, TaskAssignee, TaskStatus, TaskStatusCategory, Subtask
from app.models.comment import Comment
from app.models.initiative import Initiative, InitiativeMember, InitiativeRoleModel, PermissionKey
from app.models.user import User
from app.models.guild import GuildRole
from app.models.document import ProjectDocument
from app.models.tag import Tag, ProjectTag, TaskTag
from app.services import notifications as notifications_service
from app.services import initiatives as initiatives_service
from app.services import documents as documents_service
from app.services import task_statuses as task_statuses_service
from app.services.realtime import broadcast_event
from app.schemas.project import (
    ProjectCreate,
    ProjectDuplicateRequest,
    ProjectPermissionBulkCreate,
    ProjectPermissionBulkDelete,
    ProjectPermissionCreate,
    ProjectPermissionRead,
    ProjectPermissionUpdate,
    ProjectRead,
    ProjectRolePermissionCreate,
    ProjectRolePermissionRead,
    ProjectRolePermissionUpdate,
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
from app.schemas.tag import TagSetRequest, TagSummary

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]
GuildAdminContext = Annotated[GuildContext, Depends(require_guild_roles(GuildRole.admin))]

MAX_RECENT_PROJECTS = 20


def _project_role_permissions(project: Project) -> List[ProjectRolePermissionRead]:
    """Serialize project role permissions."""
    role_permissions = getattr(project, "role_permissions", None) or []
    result: List[ProjectRolePermissionRead] = []
    for rp in role_permissions:
        role = getattr(rp, "role", None)
        result.append(
            ProjectRolePermissionRead(
                initiative_role_id=rp.initiative_role_id,
                role_name=getattr(role, "name", "") if role else "",
                role_display_name=getattr(role, "display_name", "") if role else "",
                level=rp.level,
                created_at=rp.created_at,
            )
        )
    return result


def _project_tags(project: Project) -> List[TagSummary]:
    """Serialize project tags to TagSummary list."""
    tag_links = getattr(project, "tag_links", None) or []
    tags: List[TagSummary] = []
    for link in tag_links:
        tag = getattr(link, "tag", None)
        if tag:
            tags.append(TagSummary(id=tag.id, name=tag.name, color=tag.color))
    return tags


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


def _project_payload(
    project: Project,
    *,
    my_permission_level: str | None = None,
) -> dict:
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
            "role_permissions": _project_role_permissions(project),
            "my_permission_level": my_permission_level,
        }
    )
    return payload.model_dump(mode="json")


async def _get_project_or_404(project_id: int, session: SessionDep, guild_id: int | None = None) -> Project:
    statement = select(Project).where(Project.id == project_id).options(
        selectinload(Project.permissions).selectinload(ProjectPermission.user),
        selectinload(Project.role_permissions).selectinload(ProjectRolePermission.role),
        selectinload(Project.owner),
        selectinload(Project.initiative).selectinload(Initiative.memberships).options(
            selectinload(InitiativeMember.user),
            selectinload(InitiativeMember.role_ref).selectinload(InitiativeRoleModel.permissions),
        ),
        selectinload(Project.document_links).selectinload(ProjectDocument.document),
        selectinload(Project.tag_links).selectinload(ProjectTag.tag),
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
        .options(selectinload(Initiative.memberships).options(
            selectinload(InitiativeMember.user),
            selectinload(InitiativeMember.role_ref).selectinload(InitiativeRoleModel.permissions),
        ))
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


def _role_permission_level_from_project(project: Project, user_id: int) -> ProjectPermissionLevel | None:
    """Get the highest role-based permission level for a user on a project."""
    role_permissions = getattr(project, "role_permissions", None)
    if not role_permissions:
        return None
    initiative = getattr(project, "initiative", None)
    if not initiative:
        return None
    memberships = getattr(initiative, "memberships", None)
    if not memberships:
        return None
    # Find user's role_id(s) in this initiative
    user_role_ids = {m.role_id for m in memberships if m.user_id == user_id and m.role_id is not None}
    if not user_role_ids:
        return None
    # Find matching role permissions and return the highest level
    level_order = {ProjectPermissionLevel.read: 0, ProjectPermissionLevel.write: 1, ProjectPermissionLevel.owner: 2}
    best_level: ProjectPermissionLevel | None = None
    for rp in role_permissions:
        if rp.initiative_role_id in user_role_ids:
            if best_level is None or level_order.get(rp.level, 0) > level_order.get(best_level, 0):
                best_level = rp.level
    return best_level


def _effective_permission_level(
    user_level: ProjectPermissionLevel | None,
    role_level: ProjectPermissionLevel | None,
) -> ProjectPermissionLevel | None:
    """Return the higher of two permission levels (MAX behavior)."""
    if user_level is None:
        return role_level
    if role_level is None:
        return user_level
    level_order = {ProjectPermissionLevel.read: 0, ProjectPermissionLevel.write: 1, ProjectPermissionLevel.owner: 2}
    if level_order.get(role_level, 0) > level_order.get(user_level, 0):
        return role_level
    return user_level


def _compute_my_permission_level(
    project: Project,
    user_id: int,
    *,
    is_guild_admin: bool = False,
) -> str | None:
    """Compute the effective permission level for a user on a project.

    Uses eagerly-loaded relationships (permissions, role_permissions,
    initiative.memberships) so no DB queries are needed.
    Guild admins are treated as having owner-level access.
    """
    if is_guild_admin:
        return ProjectPermissionLevel.owner.value

    # Check user-specific permission
    user_level: ProjectPermissionLevel | None = None
    perm = _permission_from_project(project, user_id)
    if perm:
        user_level = perm.level

    # Check role-based permission
    role_level = _role_permission_level_from_project(project, user_id)

    effective = _effective_permission_level(user_level, role_level)
    return effective.value if effective else None


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
        # Get the member role for this initiative
        member_role = await initiatives_service.get_member_role(session, initiative_id=initiative_id)
        if not member_role:
            # Create roles if they don't exist (migration safety)
            _, member_role = await initiatives_service.create_builtin_roles(session, initiative_id=initiative_id)
        session.add(
            InitiativeMember(
                initiative_id=initiative_id,
                user_id=user_id,
                role_id=member_role.id,
            )
        )
        await session.flush()


def _ensure_not_archived(project: Project) -> None:
    if project.is_archived:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project is archived")


async def _remove_user_task_assignments(
    session: SessionDep,
    project_id: int,
    user_id: int,
) -> None:
    """Remove all task assignments for a user in a project.

    Called when a user loses write access to a project (permission removed or
    downgraded to read), since users cannot be assigned to tasks they can't edit.
    """
    # Get task IDs for this project
    task_ids_stmt = select(Task.id).where(Task.project_id == project_id)
    task_ids_result = await session.exec(task_ids_stmt)
    task_ids = list(task_ids_result.all())

    if not task_ids:
        return

    # Delete assignments for this user on these tasks
    delete_stmt = sa_delete(TaskAssignee).where(
        TaskAssignee.task_id.in_(task_ids),
        TaskAssignee.user_id == user_id,
    )
    await session.exec(delete_stmt)


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
        .options(
            selectinload(Task.assignees),
            selectinload(Task.task_status),
            selectinload(Task.subtasks),
            selectinload(Task.tag_links),
        )
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
        if template_task.subtasks:
            session.add_all(
                [
                    Subtask(
                        task_id=new_task.id,
                        content=subtask.content,
                        is_completed=subtask.is_completed,
                        position=subtask.position,
                    )
                    for subtask in template_task.subtasks
                ]
            )
        if template_task.tag_links:
            session.add_all(
                [
                    TaskTag(
                        task_id=new_task.id,
                        tag_id=link.tag_id,
                    )
                    for link in template_task.tag_links
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
) -> List[Project]:
    """Get projects visible to the user.

    DAC: Projects with explicit ProjectPermission OR role-based permission.
    """
    # Subquery: projects where user has explicit permission
    user_perm_subq = (
        select(ProjectPermission.project_id)
        .where(ProjectPermission.user_id == current_user.id)
    )
    # Subquery: projects where user's initiative role has permission
    role_perm_subq = (
        select(ProjectRolePermission.project_id)
        .join(
            InitiativeMember,
            (InitiativeMember.role_id == ProjectRolePermission.initiative_role_id)
            & (InitiativeMember.user_id == current_user.id),
        )
    )
    has_permission_subq = user_perm_subq.union(role_perm_subq)

    base_statement = (
        select(Project)
        .join(Project.initiative)
        .where(
            Initiative.guild_id == guild_id,
            Project.id.in_(has_permission_subq),
        )
        .options(
            selectinload(Project.permissions).selectinload(ProjectPermission.user),
            selectinload(Project.role_permissions).selectinload(ProjectRolePermission.role),
            selectinload(Project.owner),
            selectinload(Project.initiative).selectinload(Initiative.memberships).options(
                selectinload(InitiativeMember.user),
                selectinload(InitiativeMember.role_ref).selectinload(InitiativeRoleModel.permissions),
            ),
            selectinload(Project.document_links).selectinload(ProjectDocument.document),
            selectinload(Project.tag_links).selectinload(ProjectTag.tag),
        )
    )
    result = await session.exec(base_statement)
    all_projects = result.all()

    return [project for project in all_projects if _matches_filters(project, archived=archived, template=template)]


async def _project_reads_with_order(
    session: SessionDep,
    current_user: User,
    projects: List[Project],
    *,
    is_guild_admin: bool = False,
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
        my_level = _compute_my_permission_level(
            project, current_user.id, is_guild_admin=is_guild_admin,
        )
        payloads.append(
            _build_project_payload(
                project,
                sort_order=order_map.get(project.id),
                favorite_ids=favorite_ids,
                view_map=view_map,
                my_permission_level=my_level,
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
            selectinload(Project.role_permissions).selectinload(ProjectRolePermission.role),
            selectinload(Project.owner),
            selectinload(Project.initiative).selectinload(Initiative.memberships).options(
                selectinload(InitiativeMember.user),
                selectinload(InitiativeMember.role_ref).selectinload(InitiativeRoleModel.permissions),
            ),
            selectinload(Project.document_links).selectinload(ProjectDocument.document),
            selectinload(Project.tag_links).selectinload(ProjectTag.tag),
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
    my_permission_level: str | None = None,
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
            "tags": _project_tags(project),
            "role_permissions": _project_role_permissions(project),
            "my_permission_level": my_permission_level,
        }
    )


async def _record_recent_project_view(
    session: SessionDep,
    *,
    user_id: int,
    project_id: int,
) -> RecentProjectView:
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    now = datetime.now(timezone.utc)
    # Use upsert to handle race conditions
    stmt = pg_insert(RecentProjectView).values(
        user_id=user_id,
        project_id=project_id,
        last_viewed_at=now,
    ).on_conflict_do_update(
        index_elements=["user_id", "project_id"],
        set_={"last_viewed_at": now},
    )

    await session.execute(stmt)
    await session.commit()
    await reapply_rls_context(session)

    # Fetch the record we just upserted
    fetch_stmt = select(RecentProjectView).where(
        RecentProjectView.user_id == user_id,
        RecentProjectView.project_id == project_id,
    )
    result = await session.exec(fetch_stmt)
    record = result.one()

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
    *,
    is_guild_admin: bool = False,
) -> ProjectRead:
    payloads = await _project_reads_with_order(
        session, current_user, [project], is_guild_admin=is_guild_admin,
    )
    if payloads:
        return payloads[0]
    my_level = _compute_my_permission_level(
        project, current_user.id, is_guild_admin=is_guild_admin,
    )
    project_ids = [project.id] if project.id is not None else []
    favorite_ids, view_map = await _project_meta_for_user(session, current_user.id, project_ids)
    await _attach_task_summaries(session, [project])
    return _build_project_payload(
        project,
        sort_order=None,
        favorite_ids=favorite_ids,
        view_map=view_map,
        my_permission_level=my_level,
    )


async def _require_project_membership(
    project: Project,
    current_user: User,
    session: SessionDep,
    *,
    access: str = "read",
    require_manager: bool = False,
):
    """Check if user has required access to a project.

    DAC: Access granted through explicit ProjectPermission or role-based permission.
    Effective level = MAX(user-specific, role-based).
    - owner permission = full access (can manage permissions, delete, etc.)
    - write permission = can edit project content
    - read permission = can view project
    """
    # Check explicit permission
    permission = await _get_project_permission(project, current_user.id, session)
    user_level = permission.level if permission else None

    # Check role-based permission
    role_level = _role_permission_level_from_project(project, current_user.id)

    effective = _effective_permission_level(user_level, role_level)

    if require_manager:
        # Only project owners can perform manager-level operations
        if effective != ProjectPermissionLevel.owner:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Project owner permission required",
            )
        return

    if effective is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You don't have access to this project")

    # Check access level for non-manager operations
    if access == "write" and effective == ProjectPermissionLevel.read:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Write access required")


def _has_project_write_access(
    project: Project,
    current_user: User,
) -> bool:
    """Check if user has write access to a project (synchronous version for filtering).

    DAC: Write access requires explicit write/owner permission or role-based write permission.
    """
    permission = _permission_from_project(project, current_user.id)
    user_level = permission.level if permission else None
    role_level = _role_permission_level_from_project(project, current_user.id)
    effective = _effective_permission_level(user_level, role_level)

    return effective is not None and effective in (ProjectPermissionLevel.owner, ProjectPermissionLevel.write)


@router.get("/", response_model=List[ProjectRead])
async def list_projects(
    session: RLSSessionDep,
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
    )
    return await _project_reads_with_order(
        session, current_user, projects,
        is_guild_admin=guild_context.role == GuildRole.admin,
    )


@router.get("/writable", response_model=List[ProjectRead])
async def list_writable_projects(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[ProjectRead]:
    projects = await _visible_projects(
        session,
        current_user,
        guild_id=guild_context.guild_id,
        archived=None,
        template=None,
    )
    writable_projects = [
        project
        for project in projects
        if _has_project_write_access(project, current_user)
    ]
    return await _project_reads_with_order(
        session, current_user, writable_projects,
        is_guild_admin=guild_context.role == GuildRole.admin,
    )


@router.post("/", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_in: ProjectCreate,
    session: RLSSessionDep,
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
    if initiative_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Initiative is required")
    initiative = await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)
    if guild_context.role != GuildRole.admin:
        has_perm = await initiatives_service.check_initiative_permission(
            session,
            initiative_id=initiative_id,
            user=current_user,
            permission_key=PermissionKey.create_projects,
        )
        if not has_perm:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission required to create projects",
            )
    await _ensure_user_in_initiative(initiative_id, owner_id, session)
    project = Project(
        name=project_in.name,
        icon=icon_value,
        description=description_value,
        owner_id=owner_id,
        initiative_id=initiative_id,
        is_template=project_in.is_template,
        guild_id=guild_context.guild_id,
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
        guild_id=guild_context.guild_id,
    )
    session.add(owner_permission)

    # Add read permissions for all initiative members (except owner)
    for membership in initiative.memberships:
        if membership.user_id != owner_id and membership.user:
            read_permission = ProjectPermission(
                project_id=project.id,
                user_id=membership.user_id,
                level=ProjectPermissionLevel.read,
                guild_id=guild_context.guild_id,
            )
            session.add(read_permission)

    if template_project:
        await _duplicate_template_tasks(
            session,
            template_project,
            project,
            status_mapping=status_mapping,
            fallback_status_ids=fallback_status_ids,
        )
        # Copy tags from template project
        template_tag_links = getattr(template_project, "tag_links", None) or []
        if template_tag_links:
            session.add_all([
                ProjectTag(
                    project_id=project.id,
                    tag_id=link.tag_id,
                )
                for link in template_tag_links
            ])

    await session.commit()
    await reapply_rls_context(session)

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
                guild_id=guild_context.guild_id,
            )
    await _attach_task_summaries(session, [project])
    is_admin = guild_context.role == GuildRole.admin
    await broadcast_event("project", "created", _project_payload(
        project,
        my_permission_level=_compute_my_permission_level(
            project, current_user.id, is_guild_admin=is_admin,
        ),
    ))
    return await _project_read_for_user(
        session, current_user, project, is_guild_admin=is_admin,
    )


@router.post("/{project_id}/archive", response_model=ProjectRead)
async def archive_project(
    project_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRead:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="write",
            )
    if not project.is_archived:
        project.is_archived = True
        project.archived_at = datetime.now(timezone.utc)
        session.add(project)
        await session.commit()
        await reapply_rls_context(session)
    updated = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _attach_task_summaries(session, [updated])
    is_admin = guild_context.role == GuildRole.admin
    await broadcast_event("project", "updated", _project_payload(
        updated,
        my_permission_level=_compute_my_permission_level(
            updated, current_user.id, is_guild_admin=is_admin,
        ),
    ))
    return await _project_read_for_user(
        session, current_user, updated, is_guild_admin=is_admin,
    )


@router.post("/{project_id}/duplicate", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def duplicate_project(
    project_id: int,
    duplicate_in: ProjectDuplicateRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRead:
    source_project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        source_project,
        current_user,
        session,
        access="write",
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
        is_template=False,
        guild_id=guild_context.guild_id,
    )

    session.add(new_project)
    await session.flush()

    session.add(
        ProjectPermission(
            project_id=new_project.id,
            user_id=owner_id,
            level=ProjectPermissionLevel.owner,
            guild_id=guild_context.guild_id,
        )
    )

    # Add read permissions for all initiative members (except owner)
    if source_project.initiative:
        for membership in source_project.initiative.memberships:
            if membership.user_id != owner_id and membership.user:
                read_permission = ProjectPermission(
                    project_id=new_project.id,
                    user_id=membership.user_id,
                    level=ProjectPermissionLevel.read,
                    guild_id=guild_context.guild_id,
                )
                session.add(read_permission)

    # Copy tags from source project
    source_tag_links = getattr(source_project, "tag_links", None) or []
    if source_tag_links:
        session.add_all([
            ProjectTag(
                project_id=new_project.id,
                tag_id=link.tag_id,
            )
            for link in source_tag_links
        ])

    # Clone task statuses from source project to new project
    status_mapping = await task_statuses_service.clone_statuses(
        session,
        source_project_id=source_project.id,
        target_project_id=new_project.id,
    )

    # Ensure default statuses exist and create fallback mapping
    statuses = await task_statuses_service.ensure_default_statuses(session, new_project.id)
    fallback_status_ids = {status.category: status.id for status in statuses}

    await _duplicate_template_tasks(
        session,
        source_project,
        new_project,
        status_mapping=status_mapping,
        fallback_status_ids=fallback_status_ids,
    )
    await session.commit()
    await reapply_rls_context(session)

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
                guild_id=guild_context.guild_id,
            )
    await _attach_task_summaries(session, [new_project])
    is_admin = guild_context.role == GuildRole.admin
    await broadcast_event("project", "created", _project_payload(
        new_project,
        my_permission_level=_compute_my_permission_level(
            new_project, current_user.id, is_guild_admin=is_admin,
        ),
    ))
    return await _project_read_for_user(
        session, current_user, new_project, is_guild_admin=is_admin,
    )


@router.post("/{project_id}/unarchive", response_model=ProjectRead)
async def unarchive_project(
    project_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRead:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="write",
            )
    if project.is_archived:
        project.is_archived = False
        project.archived_at = None
        session.add(project)
        await session.commit()
        await reapply_rls_context(session)
    updated = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _attach_task_summaries(session, [updated])
    is_admin = guild_context.role == GuildRole.admin
    await broadcast_event("project", "updated", _project_payload(
        updated,
        my_permission_level=_compute_my_permission_level(
            updated, current_user.id, is_guild_admin=is_admin,
        ),
    ))
    return await _project_read_for_user(
        session, current_user, updated, is_guild_admin=is_admin,
    )


@router.get("/recent", response_model=List[ProjectRead])
async def recent_projects(
    session: RLSSessionDep,
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
    is_admin = guild_context.role == GuildRole.admin

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
                            )
        except HTTPException:
            continue
        payloads.append(
            _build_project_payload(
                project,
                sort_order=None,
                favorite_ids=favorite_ids,
                view_map=view_map,
                my_permission_level=_compute_my_permission_level(
                    project, current_user.id, is_guild_admin=is_admin,
                ),
            )
        )
    return payloads


@router.get("/favorites", response_model=List[ProjectRead])
async def favorite_projects(
    session: RLSSessionDep,
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
    is_admin = guild_context.role == GuildRole.admin

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
                            )
        except HTTPException:
            continue
        payloads.append(
            _build_project_payload(
                project,
                sort_order=None,
                favorite_ids=favorite_ids,
                view_map=view_map,
                my_permission_level=_compute_my_permission_level(
                    project, current_user.id, is_guild_admin=is_admin,
                ),
            )
        )
    return payloads


@router.post("/{project_id}/view", response_model=ProjectRecentViewRead)
async def record_project_view(
    project_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRecentViewRead:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="read",
            )
    record = await _record_recent_project_view(session, user_id=current_user.id, project_id=project.id)
    return ProjectRecentViewRead(project_id=project.id, last_viewed_at=record.last_viewed_at)


@router.delete("/{project_id}/view", status_code=status.HTTP_204_NO_CONTENT)
async def clear_project_view(
    project_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="read",
            )
    await _delete_recent_project_view(session, user_id=current_user.id, project_id=project.id)


@router.post("/{project_id}/favorite", response_model=ProjectFavoriteStatus)
async def favorite_project(
    project_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectFavoriteStatus:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="read",
            )
    await _set_favorite_state(session, user_id=current_user.id, project_id=project.id, favorited=True)
    return ProjectFavoriteStatus(project_id=project.id, is_favorited=True)


@router.delete("/{project_id}/favorite", response_model=ProjectFavoriteStatus)
async def unfavorite_project(
    project_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectFavoriteStatus:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="read",
            )
    await _set_favorite_state(session, user_id=current_user.id, project_id=project.id, favorited=False)
    return ProjectFavoriteStatus(project_id=project.id, is_favorited=False)


@router.get("/{project_id}/activity", response_model=ProjectActivityResponse)
async def project_activity_feed(
    project_id: int,
    session: RLSSessionDep,
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
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRead:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="read",
            )
    return await _project_read_for_user(
        session, current_user, project,
        is_guild_admin=guild_context.role == GuildRole.admin,
    )


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: int,
    project_in: ProjectUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRead:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="write",
            )
    _ensure_not_archived(project)
    previous_initiative_id = project.initiative_id

    update_data = project_in.dict(exclude_unset=True)
    pinned_sentinel = object()
    pinned_value = update_data.pop("pinned", pinned_sentinel)
    if pinned_value is not pinned_sentinel:
        # Only guild admins and initiative managers can pin/unpin projects
        can_pin = guild_context.role == GuildRole.admin
        if not can_pin and project.initiative_id:
            can_pin = await initiatives_service.is_initiative_manager(
                session,
                initiative_id=project.initiative_id,
                user=current_user,
            )
        if not can_pin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only guild admins and initiative managers can pin projects",
            )
        project.pinned_at = datetime.now(timezone.utc) if bool(pinned_value) else None

    if "initiative_id" in update_data:
        new_initiative_id = update_data.pop("initiative_id")
        if new_initiative_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Initiatives are required")
        if new_initiative_id != project.initiative_id:
            await _get_initiative_or_404(new_initiative_id, session, guild_context.guild_id)
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
    await reapply_rls_context(session)
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
                guild_id=guild_context.guild_id,
            )
    await _attach_task_summaries(session, [project])
    is_admin = guild_context.role == GuildRole.admin
    await broadcast_event("project", "updated", _project_payload(
        project,
        my_permission_level=_compute_my_permission_level(
            project, current_user.id, is_guild_admin=is_admin,
        ),
    ))
    return await _project_read_for_user(
        session, current_user, project, is_guild_admin=is_admin,
    )


@router.post("/{project_id}/documents/{document_id}", response_model=ProjectRead)
async def attach_project_document(
    project_id: int,
    document_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRead:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="write",
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
    is_admin = guild_context.role == GuildRole.admin
    await broadcast_event("project", "updated", _project_payload(
        updated_project,
        my_permission_level=_compute_my_permission_level(
            updated_project, current_user.id, is_guild_admin=is_admin,
        ),
    ))
    return await _project_read_for_user(
        session, current_user, updated_project, is_guild_admin=is_admin,
    )


@router.delete("/{project_id}/documents/{document_id}", response_model=ProjectRead)
async def detach_project_document(
    project_id: int,
    document_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRead:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="write",
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
    is_admin = guild_context.role == GuildRole.admin
    await broadcast_event("project", "updated", _project_payload(
        updated_project,
        my_permission_level=_compute_my_permission_level(
            updated_project, current_user.id, is_guild_admin=is_admin,
        ),
    ))
    return await _project_read_for_user(
        session, current_user, updated_project, is_guild_admin=is_admin,
    )


@router.post("/{project_id}/members", response_model=ProjectPermissionRead, status_code=status.HTTP_201_CREATED)
async def add_project_member(
    project_id: int,
    member_in: ProjectPermissionCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectPermission:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="write",
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
        await reapply_rls_context(session)
        await session.refresh(existing)
        return existing

    permission = ProjectPermission(
        project_id=project_id,
        user_id=member_in.user_id,
        level=member_in.level,
        guild_id=guild_context.guild_id,
    )
    session.add(permission)
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(permission)
    return permission


@router.post("/{project_id}/members/bulk", response_model=List[ProjectPermissionRead], status_code=status.HTTP_201_CREATED)
async def add_project_members_bulk(
    project_id: int,
    bulk_in: ProjectPermissionBulkCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[ProjectPermission]:
    """Add multiple members to a project with the same permission level."""
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="write",
            )
    _ensure_not_archived(project)

    if bulk_in.level == ProjectPermissionLevel.owner:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot assign owner permission")

    if not bulk_in.user_ids:
        return []

    # Validate all users are initiative members (if project belongs to initiative)
    valid_member_ids: set[int] = set()
    if project.initiative_id:
        initiative_members_result = await session.exec(
            select(InitiativeMember.user_id).where(
                InitiativeMember.initiative_id == project.initiative_id,
                InitiativeMember.user_id.in_(bulk_in.user_ids),
            )
        )
        valid_member_ids = set(initiative_members_result.all())
    else:
        valid_member_ids = set(bulk_in.user_ids)

    # Get existing permissions
    existing_permissions_result = await session.exec(
        select(ProjectPermission).where(
            ProjectPermission.project_id == project_id,
            ProjectPermission.user_id.in_(bulk_in.user_ids),
        )
    )
    existing_permissions = {p.user_id: p for p in existing_permissions_result.all()}

    created_permissions: List[ProjectPermission] = []
    for user_id in bulk_in.user_ids:
        # Skip invalid users (not initiative members)
        if user_id not in valid_member_ids:
            continue
        # Skip owner - they already have full access
        if user_id == project.owner_id:
            continue
        # Update existing permission
        if user_id in existing_permissions:
            existing = existing_permissions[user_id]
            if existing.level != ProjectPermissionLevel.owner:
                existing.level = bulk_in.level
                session.add(existing)
                created_permissions.append(existing)
            continue
        # Create new permission
        permission = ProjectPermission(
            project_id=project_id,
            user_id=user_id,
            level=bulk_in.level,
            guild_id=guild_context.guild_id,
        )
        session.add(permission)
        created_permissions.append(permission)

    await session.commit()
    await reapply_rls_context(session)
    for permission in created_permissions:
        await session.refresh(permission)
    return created_permissions


@router.post("/{project_id}/members/bulk-delete", status_code=status.HTTP_204_NO_CONTENT)
async def remove_project_members_bulk(
    project_id: int,
    bulk_in: ProjectPermissionBulkDelete,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Remove multiple members from a project."""
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="write",
            )
    _ensure_not_archived(project)

    if not bulk_in.user_ids:
        return

    # Get existing permissions to delete
    permissions_result = await session.exec(
        select(ProjectPermission).where(
            ProjectPermission.project_id == project_id,
            ProjectPermission.user_id.in_(bulk_in.user_ids),
        )
    )
    permissions = permissions_result.all()

    removed_user_ids: list[int] = []
    for permission in permissions:
        # Skip owner - cannot remove them
        if permission.user_id == project.owner_id:
            continue
        removed_user_ids.append(permission.user_id)
        await session.delete(permission)

    # Remove task assignments for removed users
    for removed_user_id in removed_user_ids:
        await _remove_user_task_assignments(session, project.id, removed_user_id)

    await session.commit()


@router.patch("/{project_id}/members/{user_id}", response_model=ProjectPermissionRead)
async def update_project_member(
    project_id: int,
    user_id: int,
    update_in: ProjectPermissionUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectPermission:
    """Update a project member's permission level."""
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="write",
            )
    _ensure_not_archived(project)

    if update_in.level == ProjectPermissionLevel.owner:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot assign owner permission")
    if user_id == project.owner_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot modify owner's permission")

    permission = await _get_project_permission(project, user_id, session)
    if not permission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found")
    if permission.level == ProjectPermissionLevel.owner:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot modify owner's permission")

    # If downgrading to read, remove task assignments
    if update_in.level == ProjectPermissionLevel.read:
        await _remove_user_task_assignments(session, project.id, user_id)

    permission.level = update_in.level
    session.add(permission)
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(permission)
    return permission


@router.delete("/{project_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_project_member(
    project_id: int,
    user_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="write",
            )
    _ensure_not_archived(project)
    if user_id == project.owner_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove the project owner")
    permission = await _get_project_permission(project, user_id, session)
    if not permission:
        return
    await session.delete(permission)
    # Remove task assignments since user no longer has access
    await _remove_user_task_assignments(session, project.id, user_id)
    await session.commit()


@router.post("/reorder", response_model=List[ProjectRead])
async def reorder_projects(
    reorder_in: ProjectReorderRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[ProjectRead]:
    visible_projects = await _visible_projects(
        session,
        current_user,
        guild_id=guild_context.guild_id,
        archived=None,
        template=None,
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
    await reapply_rls_context(session)
    return await _project_reads_with_order(
        session, current_user, visible_projects,
        is_guild_admin=guild_context.role == GuildRole.admin,
    )


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: int,
    session: RLSSessionDep,
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
            )
    await session.delete(project)
    await session.commit()
    await broadcast_event("project", "deleted", {"id": project_id})


@router.put("/{project_id}/tags", response_model=ProjectRead)
async def set_project_tags(
    project_id: int,
    tags_in: TagSetRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRead:
    """Set tags on a project. Replaces all existing tags with the provided list."""
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project, current_user, session, access="write"
    )

    # Validate all tags belong to this guild
    if tags_in.tag_ids:
        tags_stmt = select(Tag).where(
            Tag.id.in_(tags_in.tag_ids),
            Tag.guild_id == guild_context.guild_id,
        )
        tags_result = await session.exec(tags_stmt)
        valid_tags = tags_result.all()
        valid_tag_ids = {t.id for t in valid_tags}

        invalid_ids = set(tags_in.tag_ids) - valid_tag_ids
        if invalid_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid tag IDs: {sorted(invalid_ids)}",
            )

    # Remove existing tags
    delete_stmt = sa_delete(ProjectTag).where(ProjectTag.project_id == project_id)
    await session.exec(delete_stmt)

    # Add new tags
    for tag_id in tags_in.tag_ids:
        project_tag = ProjectTag(
            project_id=project_id,
            tag_id=tag_id,
        )
        session.add(project_tag)

    # Update timestamp directly via SQL to avoid issues with deleted relationship objects
    update_stmt = (
        select(Project)
        .where(Project.id == project_id)
    )
    result = await session.exec(update_stmt)
    proj = result.one()
    proj.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await reapply_rls_context(session)

    # Refetch with all relationships
    updated = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _attach_task_summaries(session, [updated])
    return await _project_read_for_user(
        session, current_user, updated,
        is_guild_admin=guild_context.role == GuildRole.admin,
    )


# ── Role-based permission CRUD ───────────────────────────────────


@router.post("/{project_id}/role-permissions", response_model=ProjectRolePermissionRead, status_code=status.HTTP_201_CREATED)
async def add_project_role_permission(
    project_id: int,
    role_perm_in: ProjectRolePermissionCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRolePermissionRead:
    """Add a role-based permission to a project."""
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(project, current_user, session, access="write")
    _ensure_not_archived(project)

    if role_perm_in.level == ProjectPermissionLevel.owner:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot assign owner permission to a role")

    # Validate the role belongs to the same initiative as the project
    stmt = select(InitiativeRoleModel).where(InitiativeRoleModel.id == role_perm_in.initiative_role_id)
    result = await session.exec(stmt)
    role = result.one_or_none()
    if not role or role.initiative_id != project.initiative_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Role must belong to the project's initiative")

    # Check if already exists
    existing_stmt = select(ProjectRolePermission).where(
        ProjectRolePermission.project_id == project_id,
        ProjectRolePermission.initiative_role_id == role_perm_in.initiative_role_id,
    )
    existing_result = await session.exec(existing_stmt)
    existing = existing_result.one_or_none()
    if existing:
        existing.level = role_perm_in.level
        session.add(existing)
        await session.commit()
        await reapply_rls_context(session)
        await session.refresh(existing)
        return ProjectRolePermissionRead(
            initiative_role_id=existing.initiative_role_id,
            role_name=role.name,
            role_display_name=role.display_name,
            level=existing.level,
            created_at=existing.created_at,
        )

    role_perm = ProjectRolePermission(
        project_id=project_id,
        initiative_role_id=role_perm_in.initiative_role_id,
        level=role_perm_in.level,
        guild_id=guild_context.guild_id,
    )
    session.add(role_perm)
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(role_perm)
    return ProjectRolePermissionRead(
        initiative_role_id=role_perm.initiative_role_id,
        role_name=role.name,
        role_display_name=role.display_name,
        level=role_perm.level,
        created_at=role_perm.created_at,
    )


@router.patch("/{project_id}/role-permissions/{role_id}", response_model=ProjectRolePermissionRead)
async def update_project_role_permission(
    project_id: int,
    role_id: int,
    update_in: ProjectRolePermissionUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRolePermissionRead:
    """Update a role-based permission level on a project."""
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(project, current_user, session, access="write")
    _ensure_not_archived(project)

    if update_in.level == ProjectPermissionLevel.owner:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot assign owner permission to a role")

    stmt = select(ProjectRolePermission).where(
        ProjectRolePermission.project_id == project_id,
        ProjectRolePermission.initiative_role_id == role_id,
    )
    result = await session.exec(stmt)
    role_perm = result.one_or_none()
    if not role_perm:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role permission not found")

    role_perm.level = update_in.level
    session.add(role_perm)
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(role_perm)

    # Get role info
    role_stmt = select(InitiativeRoleModel).where(InitiativeRoleModel.id == role_id)
    role_result = await session.exec(role_stmt)
    role = role_result.one_or_none()
    return ProjectRolePermissionRead(
        initiative_role_id=role_perm.initiative_role_id,
        role_name=role.name if role else "",
        role_display_name=role.display_name if role else "",
        level=role_perm.level,
        created_at=role_perm.created_at,
    )


@router.delete("/{project_id}/role-permissions/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_project_role_permission(
    project_id: int,
    role_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Remove a role-based permission from a project."""
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(project, current_user, session, access="write")
    _ensure_not_archived(project)

    stmt = select(ProjectRolePermission).where(
        ProjectRolePermission.project_id == project_id,
        ProjectRolePermission.initiative_role_id == role_id,
    )
    result = await session.exec(stmt)
    role_perm = result.one_or_none()
    if not role_perm:
        return
    await session.delete(role_perm)
    await session.commit()
