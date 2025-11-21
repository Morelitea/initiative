from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api.deps import SessionDep, get_current_active_user, require_roles
from app.models.project import Project, ProjectMember, ProjectRole
from app.models.team import Team, TeamMember
from app.models.user import User, UserRole
from app.services import project_access
from app.schemas.project import (
    ProjectCreate,
    ProjectMemberCreate,
    ProjectMemberRead,
    ProjectRead,
    ProjectUpdate,
)

router = APIRouter()

ManagerUser = Annotated[User, Depends(require_roles(UserRole.admin, UserRole.project_manager))]
AdminUser = Annotated[User, Depends(require_roles(UserRole.admin))]


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
) -> List[Project]:
    base_statement = select(Project).options(
        selectinload(Project.members),
        selectinload(Project.owner),
        selectinload(Project.team).selectinload(Team.members),
    )

    result = await session.exec(base_statement)
    all_projects = result.all()

    def _matches_archive_filter(project: Project) -> bool:
        if archived is None:
            return not project.is_archived
        return project.is_archived == archived

    if current_user.role == UserRole.admin:
        return [project for project in all_projects if _matches_archive_filter(project)]

    membership_result = await session.exec(select(ProjectMember).where(ProjectMember.user_id == current_user.id))
    memberships = membership_result.all()
    membership_map = {membership.project_id: membership.role for membership in memberships}
    user_project_role = project_access.user_role_to_project_role(current_user.role)
    team_ids_result = await session.exec(select(TeamMember.team_id).where(TeamMember.user_id == current_user.id))
    team_ids = set(team_ids_result.all())

    visible_projects: List[Project] = []
    for project in all_projects:
        if not _matches_archive_filter(project):
            continue
        if project.owner_id == current_user.id:
            visible_projects.append(project)
            continue

        if (
            project.team_id
            and project.team_id not in team_ids
            and current_user.role != UserRole.admin
        ):
            continue

        membership_role = membership_map.get(project.id)
        allowed_read_roles = project_access.read_roles_set(project)
        if membership_role and membership_role.value in allowed_read_roles:
            visible_projects.append(project)
            continue

        if user_project_role.value in allowed_read_roles:
            visible_projects.append(project)

    return visible_projects


@router.post("/", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_in: ProjectCreate,
    session: SessionDep,
    manager_user: ManagerUser,
) -> Project:
    owner_id = project_in.owner_id or manager_user.id
    team_id = project_in.team_id
    if team_id is not None:
        await _get_team_or_404(team_id, session)
        await _ensure_user_in_team(team_id, owner_id, session)
    read_roles = project_access.normalize_read_roles(project_in.read_roles)
    write_roles = project_access.normalize_write_roles(project_in.write_roles)
    project = Project(
        name=project_in.name,
        description=project_in.description,
        owner_id=owner_id,
        team_id=team_id,
        read_roles=read_roles,
        write_roles=write_roles,
    )

    session.add(project)
    await session.commit()
    await session.refresh(project)

    # Ensure owner is reflected as project member with owner role
    owner_membership = ProjectMember(project_id=project.id, user_id=owner_id, role=ProjectRole.admin)
    session.add(owner_membership)
    await session.commit()
    await session.refresh(project)

    project = await _get_project_or_404(project.id, session)
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
    return await _get_project_or_404(project_id, session)


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
    return await _get_project_or_404(project_id, session)


@router.get("/{project_id}", response_model=ProjectRead)
async def read_project(project_id: int, session: SessionDep, current_user: Annotated[User, Depends(get_current_active_user)]) -> Project:
    project = await _get_project_or_404(project_id, session)
    await _require_project_membership(project, current_user, session, access="read")
    return project


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


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: int,
    session: SessionDep,
    _: AdminUser,
) -> None:
    project = await _get_project_or_404(project_id, session)
    await session.delete(project)
    await session.commit()
