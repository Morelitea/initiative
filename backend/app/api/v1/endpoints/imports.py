"""API endpoints for importing tasks from external platforms."""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api.deps import (
    SessionDep,
    get_current_active_user,
    get_guild_membership,
    GuildContext,
)
from app.models.project import Project, ProjectPermissionLevel
from app.models.initiative import Initiative, InitiativeMember, InitiativeRole
from app.models.user import User
from app.models.guild import GuildRole
from app.schemas.import_data import (
    TodoistImportRequest,
    TodoistParseResult,
    ImportResult,
)
from app.services import import_service
from app.services import task_statuses as task_statuses_service

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


async def _validate_project_write_access(
    session: SessionDep,
    project_id: int,
    user: User,
    guild_id: int,
    guild_role: GuildRole | None,
) -> Project:
    """Validate user has write access to a project."""
    project_stmt = (
        select(Project)
        .join(Project.initiative)
        .where(
            Project.id == project_id,
            Initiative.guild_id == guild_id,
        )
        .options(
            selectinload(Project.permissions),
            selectinload(Project.initiative)
            .selectinload(Initiative.memberships)
            .selectinload(InitiativeMember.user),
        )
    )
    result = await session.exec(project_stmt)
    project = result.first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )

    if project.is_archived:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot import to archived project",
        )

    # Check write access
    is_guild_admin = guild_role == GuildRole.admin
    is_owner = project.owner_id == user.id
    is_pm = any(
        m.user_id == user.id and m.role == InitiativeRole.project_manager
        for m in project.initiative.memberships
    )
    membership = next(
        (m for m in project.initiative.memberships if m.user_id == user.id), None
    )
    permission = next(
        (
            p
            for p in project.permissions
            if p.user_id == user.id and p.level in [ProjectPermissionLevel.owner, ProjectPermissionLevel.write]
        ),
        None,
    )

    has_write = (
        is_guild_admin
        or is_owner
        or is_pm
        or permission is not None
        or bool(project.members_can_write and membership)
    )

    if not has_write:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this project",
        )

    return project


@router.post("/todoist/parse", response_model=TodoistParseResult)
async def parse_todoist_csv(
    csv_content: Annotated[str, Body(media_type="text/plain")],
    _current_user: Annotated[User, Depends(get_current_active_user)],
) -> TodoistParseResult:
    """
    Parse a Todoist CSV export and return detected sections and task count.

    This is a preview endpoint to help users map sections before importing.
    """
    try:
        parse_result, _ = import_service.parse_todoist_csv(csv_content)
        return parse_result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse CSV: {str(e)}",
        )


@router.post("/todoist", response_model=ImportResult)
async def import_from_todoist(
    request: TodoistImportRequest,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ImportResult:
    """
    Import tasks from a Todoist CSV export into a project.

    The section_mapping maps Todoist section names to task_status_id values
    in the target project.
    """
    # Validate write access to the project
    project = await _validate_project_write_access(
        session,
        request.project_id,
        current_user,
        guild_context.guild_id,
        guild_context.role,
    )

    # Ensure default statuses exist
    await task_statuses_service.ensure_default_statuses(session, project.id)

    # Validate that all mapped status IDs belong to the project
    project_statuses = await task_statuses_service.list_statuses(
        session, project.id
    )
    valid_status_ids = {s.id for s in project_statuses}

    for section_name, status_id in request.section_mapping.items():
        if status_id not in valid_status_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status ID {status_id} for section '{section_name}'",
            )

    # Perform the import
    result = await import_service.import_todoist_tasks(
        session,
        project.id,
        request.csv_content,
        request.section_mapping,
    )

    return result
