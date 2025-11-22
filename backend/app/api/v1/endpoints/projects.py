from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api.deps import SessionDep, get_current_active_user, require_roles
from app.models.project import Project, ProjectMember, ProjectRole
from app.models.project_order import ProjectOrder
from app.models.task import Task, TaskAssignee
from app.models.team import Team, TeamMember
from app.models.user import User, UserRole
from app.services import project_access
from app.services.realtime import broadcast_event
from app.schemas.project import (
    ProjectCreate,
    ProjectDuplicateRequest,
    ProjectMemberCreate,
    ProjectMemberRead,
    ProjectRead,
    ProjectReorderRequest,
    ProjectUpdate,
)

router = APIRouter()

ManagerUser = Annotated[User, Depends(require_roles(UserRole.admin, UserRole.project_manager))]
AdminUser = Annotated[User, Depends(require_roles(UserRole.admin))]


def _project_payload(project: Project) -> dict:
    return ProjectRead.model_validate(project).model_dump()


async def _get_project_or_404(project_id: int, session: SessionDep) -> Project:
    statement = select(Project).where(Project.id == project_id).options(
        selectinload(Project.members),
        selectinload(Project.owner),
        selectinload(Project.team).selectinload(Team.members),
    )
    result = await session.exec(statement)
    project = result.one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


async def _get_team_or_404(team_id: int, session: SessionDep) -> Team:
    result = await session.exec(select(Team).where(Team.id == team_id))
    team = result.one_or_none()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    return team


async def _is_team_member(project: Project, user: User, session: SessionDep) -> bool:
    if not project.team_id:
        return False
    stmt = select(TeamMember).where(TeamMember.team_id == project.team_id, TeamMember.user_id == user.id)
    result = await session.exec(stmt)
    return result.one_or_none() is not None


async def _ensure_user_in_team(team_id: int, user_id: int, session: SessionDep) -> None:
    stmt = select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == user_id)
    result = await session.exec(stmt)
    if not result.one_or_none():
        session.add(TeamMember(team_id=team_id, user_id=user_id))
        await session.commit()


def _ensure_not_archived(project: Project) -> None:
    if project.is_archived:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project is archived")


async def _duplicate_template_tasks(session: SessionDep, template: Project, new_project: Project) -> None:
    task_stmt = (
        select(Task)
        .options(selectinload(Task.assignees))
        .where(Task.project_id == template.id)
        .order_by(Task.sort_order.asc(), Task.id.asc())
    )
    task_result = await session.exec(task_stmt)
    template_tasks = task_result.all()
    if not template_tasks:
        return

    for template_task in template_tasks:
        new_task = Task(
            project_id=new_project.id,
            title=template_task.title,
            description=template_task.description,
            status=template_task.status,
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
    archived: Optional[bool],
    template: Optional[bool],
) -> List[Project]:
    base_statement = select(Project).options(
        selectinload(Project.members),
        selectinload(Project.owner),
        selectinload(Project.team).selectinload(Team.members),
    )
    result = await session.exec(base_statement)
    all_projects = result.all()

    if current_user.role == UserRole.admin:
        return [project for project in all_projects if _matches_filters(project, archived=archived, template=template)]

    membership_result = await session.exec(select(ProjectMember).where(ProjectMember.user_id == current_user.id))
    memberships = membership_result.all()
    membership_map = {membership.project_id: membership.role for membership in memberships}
    user_project_role = project_access.user_role_to_project_role(current_user.role)
    team_ids_result = await session.exec(select(TeamMember.team_id).where(TeamMember.user_id == current_user.id))
    team_ids = set(team_ids_result.all())

    visible_projects: List[Project] = []
    for project in all_projects:
        if not _matches_filters(project, archived=archived, template=template):
            continue
        if project.owner_id == current_user.id:
            visible_projects.append(project)
            continue

        if project.team_id and project.team_id not in team_ids and current_user.role != UserRole.admin:
            continue

        membership_role = membership_map.get(project.id)
        allowed_read_roles = project_access.read_roles_set(project)
        if membership_role and membership_role.value in allowed_read_roles:
            visible_projects.append(project)
            continue

        if user_project_role.value in allowed_read_roles:
            visible_projects.append(project)

    return visible_projects


async def _project_reads_with_order(
    session: SessionDep,
    current_user: User,
    projects: List[Project],
) -> List[ProjectRead]:
    if not projects:
        return []

    project_ids = [project.id for project in projects if project.id is not None]
    order_map: dict[int, float] = {}
    if project_ids:
        order_stmt = select(ProjectOrder).where(
            ProjectOrder.user_id == current_user.id,
            ProjectOrder.project_id.in_(tuple(project_ids)),
        )
        order_result = await session.exec(order_stmt)
        order_map = {order.project_id: order.sort_order for order in order_result.all()}

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
        payload = ProjectRead.model_validate(project)
        payload = payload.model_copy(update={"sort_order": order_map.get(project.id)})
        payloads.append(payload)
    return payloads


async def _require_project_membership(
    project: Project,
    current_user: User,
    session: SessionDep,
    *,
    access: str = "read",
    require_manager: bool = False,
) -> ProjectMember | None:
    if current_user.role == UserRole.admin or project.owner_id == current_user.id:
        return None

    is_team_member = await _is_team_member(project, current_user, session)
    if (
        project.team_id
        and not is_team_member
        and current_user.role != UserRole.admin
        and project.owner_id != current_user.id
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not part of this project's team")

    member_stmt = select(ProjectMember).where(
        ProjectMember.project_id == project.id,
        ProjectMember.user_id == current_user.id,
    )
    result = await session.exec(member_stmt)
    membership = result.one_or_none()
    user_project_role = project_access.user_role_to_project_role(current_user.role)

    allowed_roles = (
        project_access.write_roles_set(project) if access == "write" else project_access.read_roles_set(project)
    )

    has_global_access = user_project_role.value in allowed_roles
    has_membership_access = membership and membership.role.value in allowed_roles

    if not membership:
        if has_global_access:
            if project.team_id and not is_team_member:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not part of this project's team")
            if require_manager and user_project_role not in {ProjectRole.admin, ProjectRole.project_manager}:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Manager role required")
            return None
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not part of this project")

    if not has_membership_access and not has_global_access:
        detail = "Write access denied for your role" if access == "write" else "This project is not visible to your role"
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)

    if require_manager:
        if membership.role not in {ProjectRole.admin, ProjectRole.project_manager} and user_project_role not in {
            ProjectRole.admin,
            ProjectRole.project_manager,
        }:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Manager role required")

    return membership


@router.get("/", response_model=List[ProjectRead])
async def list_projects(
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    archived: Optional[bool] = Query(default=None),
    template: Optional[bool] = Query(default=None),
) -> List[ProjectRead]:
    projects = await _visible_projects(
        session,
        current_user,
        archived=archived,
        template=template,
    )
    return await _project_reads_with_order(session, current_user, projects)


@router.post("/", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_in: ProjectCreate,
    session: SessionDep,
    manager_user: ManagerUser,
) -> Project:
    template_project: Project | None = None
    if project_in.template_id is not None:
        template_project = await _get_project_or_404(project_in.template_id, session)
        if not template_project.is_template:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected template is invalid")
        await _require_project_membership(template_project, manager_user, session, access="read")

    owner_id = project_in.owner_id or manager_user.id
    icon_value = project_in.icon if project_in.icon is not None else (template_project.icon if template_project else None)
    description_value = (
        project_in.description
        if project_in.description is not None
        else (template_project.description if template_project else None)
    )
    team_id = (
        project_in.team_id
        if project_in.team_id is not None
        else (template_project.team_id if template_project else None)
    )
    if team_id is not None:
        await _get_team_or_404(team_id, session)
        await _ensure_user_in_team(team_id, owner_id, session)
    read_roles_source = (
        project_in.read_roles
        if project_in.read_roles is not None
        else (template_project.read_roles if template_project else None)
    )
    write_roles_source = (
        project_in.write_roles
        if project_in.write_roles is not None
        else (template_project.write_roles if template_project else None)
    )
    read_roles = project_access.normalize_read_roles(read_roles_source)
    write_roles = project_access.normalize_write_roles(write_roles_source)
    project = Project(
        name=project_in.name,
        icon=icon_value,
        description=description_value,
        owner_id=owner_id,
        team_id=team_id,
        read_roles=read_roles,
        write_roles=write_roles,
        is_template=project_in.is_template,
    )

    session.add(project)
    await session.commit()
    await session.refresh(project)

    # Ensure owner is reflected as project member with owner role
    owner_membership = ProjectMember(project_id=project.id, user_id=owner_id, role=ProjectRole.admin)
    session.add(owner_membership)
    await session.commit()

    if template_project:
        await _duplicate_template_tasks(session, template_project, project)
        await session.commit()

    await session.refresh(project)

    project = await _get_project_or_404(project.id, session)
    await broadcast_event("project", "created", _project_payload(project))
    return project


@router.post("/{project_id}/archive", response_model=ProjectRead)
async def archive_project(
    project_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Project:
    project = await _get_project_or_404(project_id, session)
    await _require_project_membership(project, current_user, session, access="write", require_manager=True)
    if not project.is_archived:
        project.is_archived = True
        project.archived_at = datetime.now(timezone.utc)
        session.add(project)
        await session.commit()
    updated = await _get_project_or_404(project_id, session)
    await broadcast_event("project", "updated", _project_payload(updated))
    return updated


@router.post("/{project_id}/duplicate", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def duplicate_project(
    project_id: int,
    duplicate_in: ProjectDuplicateRequest,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Project:
    source_project = await _get_project_or_404(project_id, session)
    await _require_project_membership(source_project, current_user, session, access="read", require_manager=True)

    owner_id = current_user.id
    team_id = source_project.team_id
    if team_id is not None:
        await _get_team_or_404(team_id, session)
        await _ensure_user_in_team(team_id, owner_id, session)

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
        team_id=team_id,
        read_roles=list(source_project.read_roles),
        write_roles=list(source_project.write_roles),
        is_template=False,
    )

    session.add(new_project)
    await session.commit()
    await session.refresh(new_project)

    owner_membership = ProjectMember(project_id=new_project.id, user_id=owner_id, role=ProjectRole.admin)
    session.add(owner_membership)
    await session.commit()

    await _duplicate_template_tasks(session, source_project, new_project)
    await session.commit()

    new_project = await _get_project_or_404(new_project.id, session)
    await broadcast_event("project", "created", _project_payload(new_project))
    return new_project


@router.post("/{project_id}/unarchive", response_model=ProjectRead)
async def unarchive_project(
    project_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Project:
    project = await _get_project_or_404(project_id, session)
    await _require_project_membership(project, current_user, session, access="write", require_manager=True)
    if project.is_archived:
        project.is_archived = False
        project.archived_at = None
        session.add(project)
        await session.commit()
    updated = await _get_project_or_404(project_id, session)
    await broadcast_event("project", "updated", _project_payload(updated))
    return updated


@router.get("/{project_id}", response_model=ProjectRead)
async def read_project(
    project_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ProjectRead:
    project = await _get_project_or_404(project_id, session)
    await _require_project_membership(project, current_user, session, access="read")
    payloads = await _project_reads_with_order(session, current_user, [project])
    return payloads[0] if payloads else ProjectRead.model_validate(project)


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: int,
    project_in: ProjectUpdate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Project:
    project = await _get_project_or_404(project_id, session)
    await _require_project_membership(project, current_user, session, access="write", require_manager=True)
    _ensure_not_archived(project)

    update_data = project_in.dict(exclude_unset=True)
    if "team_id" in update_data:
        new_team_id = update_data.pop("team_id")
        if new_team_id is not None:
            await _get_team_or_404(new_team_id, session)
            await _ensure_user_in_team(new_team_id, project.owner_id, session)
        project.team_id = new_team_id
    if "read_roles" in update_data:
        project.read_roles = project_access.normalize_read_roles(update_data.pop("read_roles"))
    if "write_roles" in update_data:
        project.write_roles = project_access.normalize_write_roles(update_data.pop("write_roles"))
    for field, value in update_data.items():
        setattr(project, field, value)
    project.updated_at = datetime.now(timezone.utc)

    session.add(project)
    await session.commit()
    project = await _get_project_or_404(project.id, session)
    await broadcast_event("project", "updated", _project_payload(project))
    return project


@router.post("/{project_id}/members", response_model=ProjectMemberRead, status_code=status.HTTP_201_CREATED)
async def add_project_member(
    project_id: int,
    member_in: ProjectMemberCreate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ProjectMember:
    project = await _get_project_or_404(project_id, session)
    await _require_project_membership(project, current_user, session, access="write", require_manager=True)
    _ensure_not_archived(project)
    if project.team_id:
        await _ensure_user_in_team(project.team_id, member_in.user_id, session)

    existing_stmt = select(ProjectMember).where(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == member_in.user_id,
    )
    result = await session.exec(existing_stmt)
    membership = result.one_or_none()
    if membership:
        membership.role = member_in.role
    else:
        membership = ProjectMember(project_id=project_id, user_id=member_in.user_id, role=member_in.role)

    session.add(membership)
    await session.commit()
    await session.refresh(membership)
    return membership


@router.post("/reorder", response_model=List[ProjectRead])
async def reorder_projects(
    reorder_in: ProjectReorderRequest,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> List[ProjectRead]:
    visible_projects = await _visible_projects(session, current_user, archived=None, template=None)
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
    _: AdminUser,
) -> None:
    project = await _get_project_or_404(project_id, session)
    await session.delete(project)
    await session.commit()
    await broadcast_event("project", "deleted", {"id": project_id})
