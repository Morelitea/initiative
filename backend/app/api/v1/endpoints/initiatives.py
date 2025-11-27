from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import select, delete

from app.api.deps import (
    SessionDep,
    get_current_active_user,
    get_guild_membership,
    GuildContext,
    require_guild_roles,
)
from app.models.project import Project
from app.models.initiative import Initiative, InitiativeMember, InitiativeRole
from app.models.guild import GuildRole
from app.models.task import Task, TaskAssignee
from app.models.user import User
from app.schemas.initiative import (
    InitiativeCreate,
    InitiativeMemberAdd,
    InitiativeMemberUpdate,
    InitiativeRead,
    InitiativeUpdate,
    serialize_initiative,
)
from app.services import notifications as notifications_service
from app.services import initiatives as initiatives_service
from app.services import guilds as guilds_service
GuildAdminContext = Annotated[GuildContext, Depends(require_guild_roles(GuildRole.admin))]

router = APIRouter()


async def _get_initiative_or_404(initiative_id: int, session: SessionDep, guild_id: int | None = None) -> Initiative:
    statement = (
        select(Initiative)
        .where(Initiative.id == initiative_id)
        .options(selectinload(Initiative.memberships).selectinload(InitiativeMember.user))
    )
    if guild_id is not None:
        statement = statement.where(Initiative.guild_id == guild_id)
    result = await session.exec(statement)
    initiative = result.one_or_none()
    if not initiative:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Initiative not found")
    return initiative


async def _initiative_name_exists(
    session: SessionDep,
    name: str,
    *,
    guild_id: int,
    exclude_initiative_id: int | None = None,
) -> bool:
    normalized = name.strip().lower()
    if not normalized:
        return False
    statement = select(Initiative.id).where(
        Initiative.guild_id == guild_id,
        func.lower(Initiative.name) == normalized,
    )
    if exclude_initiative_id is not None:
        statement = statement.where(Initiative.id != exclude_initiative_id)
    result = await session.exec(statement)
    return result.first() is not None


async def _require_manager_access(
    session: SessionDep,
    initiative: Initiative,
    current_user: User,
    *,
    guild_role: GuildRole | None = None,
) -> None:
    if guild_role == GuildRole.admin:
        return
    membership = await initiatives_service.get_initiative_membership(
        session,
        initiative_id=initiative.id,
        user_id=current_user.id,
    )
    if not membership or membership.role != InitiativeRole.project_manager:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Initiative manager role required")


async def _ensure_remaining_manager(
    session: SessionDep,
    initiative: Initiative,
    *,
    exclude_user_ids: set[int] | None = None,
) -> None:
    exclude = exclude_user_ids or set()
    stmt = select(InitiativeMember).where(
        InitiativeMember.initiative_id == initiative.id,
        InitiativeMember.role == InitiativeRole.project_manager,
    )
    result = await session.exec(stmt)
    managers = [member for member in result.all() if member.user_id not in exclude]
    if not managers:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one project manager is required")


@router.get("/", response_model=List[InitiativeRead])
async def list_initiatives(
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> List[InitiativeRead]:
    statement = (
        select(Initiative)
        .where(Initiative.guild_id == guild_context.guild_id)
        .options(selectinload(Initiative.memberships).selectinload(InitiativeMember.user))
    )
    if guild_context.role != GuildRole.admin:
        statement = (
            statement.join(InitiativeMember, InitiativeMember.initiative_id == Initiative.id)
            .where(InitiativeMember.user_id == current_user.id)
            .distinct()
        )
    result = await session.exec(statement)
    initiatives = result.all()
    return [serialize_initiative(initiative) for initiative in initiatives]


@router.post("/", response_model=InitiativeRead, status_code=status.HTTP_201_CREATED)
async def create_initiative(
    initiative_in: InitiativeCreate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(require_guild_roles(GuildRole.admin))],
) -> InitiativeRead:
    guild_id = guild_context.guild_id
    if await _initiative_name_exists(session, initiative_in.name, guild_id=guild_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Initiative name already exists")
    initiative = Initiative(name=initiative_in.name, description=initiative_in.description, guild_id=guild_id)
    if initiative_in.color:
        initiative.color = initiative_in.color
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)
    session.add(
        InitiativeMember(
            initiative_id=initiative.id,
            user_id=current_user.id,
            role=InitiativeRole.project_manager,
        )
    )
    await session.commit()
    await session.refresh(initiative, attribute_names=["memberships"])
    return serialize_initiative(initiative)


@router.patch("/{initiative_id}", response_model=InitiativeRead)
async def update_initiative(
    initiative_id: int,
    initiative_in: InitiativeUpdate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> InitiativeRead:
    initiative = await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)
    await _require_manager_access(session, initiative, current_user, guild_role=guild_context.role)

    update_data = initiative_in.dict(exclude_unset=True)
    if "name" in update_data and update_data["name"] is not None:
        if await _initiative_name_exists(
            session,
            update_data["name"],
            guild_id=initiative.guild_id,
            exclude_initiative_id=initiative_id,
        ):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Initiative name already exists")
    for field, value in update_data.items():
        setattr(initiative, field, value)
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)
    await session.refresh(initiative, attribute_names=["memberships"])
    return serialize_initiative(initiative)


@router.delete("/{initiative_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_initiative(
    initiative_id: int,
    session: SessionDep,
    guild_context: GuildAdminContext,
) -> None:
    initiative = await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)
    if initiative.is_default:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Default initiative cannot be deleted")
    project_stmt = await session.exec(select(Project).where(Project.initiative_id == initiative_id))
    projects = project_stmt.all()
    for project in projects:
        await session.delete(project)
    await session.delete(initiative)
    await session.commit()


@router.post("/{initiative_id}/members", response_model=InitiativeRead, status_code=status.HTTP_200_OK)
async def add_initiative_member(
    initiative_id: int,
    payload: InitiativeMemberAdd,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> InitiativeRead:
    initiative = await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)
    await _require_manager_access(session, initiative, current_user)
    user_stmt = await session.exec(select(User).where(User.id == payload.user_id))
    user = user_stmt.one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    guild_membership = await guilds_service.get_membership(
        session,
        guild_id=initiative.guild_id,
        user_id=user.id,
    )
    if not guild_membership:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User is not part of this guild")
    stmt = select(InitiativeMember).where(
        InitiativeMember.initiative_id == initiative_id,
        InitiativeMember.user_id == payload.user_id,
    )
    result = await session.exec(stmt)
    membership = result.one_or_none()
    created = False
    if membership:
        if membership.role != payload.role:
            if (
                membership.role == InitiativeRole.project_manager
                and payload.role != InitiativeRole.project_manager
            ):
                await _ensure_remaining_manager(session, initiative, exclude_user_ids={membership.user_id})
            membership.role = payload.role
            session.add(membership)
    else:
        membership = InitiativeMember(
            initiative_id=initiative_id,
            user_id=payload.user_id,
            role=payload.role,
        )
        session.add(membership)
        created = True
    await session.commit()
    await session.refresh(initiative, attribute_names=["memberships"])
    if created:
        await notifications_service.notify_initiative_membership(
            session,
            user,
            initiative_id=initiative.id,
            initiative_name=initiative.name,
        )
    return serialize_initiative(initiative)


@router.delete("/{initiative_id}/members/{user_id}", response_model=InitiativeRead)
async def remove_initiative_member(
    initiative_id: int,
    user_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> InitiativeRead:
    initiative = await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)
    await _require_manager_access(session, initiative, current_user)
    stmt = select(InitiativeMember).where(
        InitiativeMember.initiative_id == initiative_id,
        InitiativeMember.user_id == user_id,
    )
    result = await session.exec(stmt)
    membership = result.one_or_none()
    if membership:
        if membership.role == InitiativeRole.project_manager:
            await _ensure_remaining_manager(session, initiative, exclude_user_ids={user_id})
        await session.delete(membership)

        project_ids_result = await session.exec(select(Project.id).where(Project.initiative_id == initiative_id))
        project_ids = [project_id for project_id in project_ids_result.all()]

        if project_ids:
            task_ids_result = await session.exec(
                select(Task.id).where(Task.project_id.in_(tuple(project_ids)))
            )
            task_ids = [task_id for task_id in task_ids_result.all()]
            if task_ids:
                delete_stmt = (
                    delete(TaskAssignee)
                    .where(TaskAssignee.user_id == user_id)
                    .where(TaskAssignee.task_id.in_(tuple(task_ids)))
                )
                await session.exec(delete_stmt)

        await session.commit()
    await session.refresh(initiative, attribute_names=["memberships"])
    return serialize_initiative(initiative)
@router.patch("/{initiative_id}/members/{user_id}", response_model=InitiativeRead)
async def update_initiative_member(
    initiative_id: int,
    user_id: int,
    payload: InitiativeMemberUpdate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> InitiativeRead:
    initiative = await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)
    await _require_manager_access(session, initiative, current_user)
    stmt = select(InitiativeMember).where(
        InitiativeMember.initiative_id == initiative_id,
        InitiativeMember.user_id == user_id,
    )
    result = await session.exec(stmt)
    membership = result.one_or_none()
    if not membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    if membership.role != payload.role:
        if membership.role == InitiativeRole.project_manager and payload.role != InitiativeRole.project_manager:
            await _ensure_remaining_manager(session, initiative, exclude_user_ids={user_id})
        membership.role = payload.role
        session.add(membership)
        await session.commit()
    await session.refresh(initiative, attribute_names=["memberships"])
    return serialize_initiative(initiative)
