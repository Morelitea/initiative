from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import select, delete

from app.api.deps import SessionDep, require_roles
from app.models.project import Project
from app.models.initiative import Initiative, InitiativeMember
from app.models.task import Task, TaskAssignee
from app.models.user import User, UserRole
from app.schemas.initiative import (
    InitiativeCreate,
    InitiativeMemberAdd,
    InitiativeRead,
    InitiativeUpdate,
)
from app.schemas.user import UserRead

router = APIRouter()

AdminUser = Annotated[User, Depends(require_roles(UserRole.admin))]


def _serialize_initiative(initiative: Initiative) -> InitiativeRead:
    members = [UserRead.model_validate(member) for member in initiative.members]
    return InitiativeRead(
        id=initiative.id,
        name=initiative.name,
        description=initiative.description,
        color=initiative.color,
        created_at=initiative.created_at,
        updated_at=initiative.updated_at,
        members=members,
    )


async def _get_initiative_or_404(initiative_id: int, session: SessionDep) -> Initiative:
    statement = select(Initiative).where(Initiative.id == initiative_id).options(selectinload(Initiative.members))
    result = await session.exec(statement)
    initiative = result.one_or_none()
    if not initiative:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Initiative not found")
    return initiative


async def _initiative_name_exists(session: SessionDep, name: str, exclude_initiative_id: int | None = None) -> bool:
    normalized = name.strip().lower()
    if not normalized:
        return False
    statement = select(Initiative.id).where(func.lower(Initiative.name) == normalized)
    if exclude_initiative_id is not None:
        statement = statement.where(Initiative.id != exclude_initiative_id)
    result = await session.exec(statement)
    return result.first() is not None


@router.get("/", response_model=List[InitiativeRead])
async def list_initiatives(session: SessionDep, _: AdminUser) -> List[InitiativeRead]:
    statement = select(Initiative).options(selectinload(Initiative.members))
    result = await session.exec(statement)
    initiatives = result.all()
    return [_serialize_initiative(initiative) for initiative in initiatives]


@router.post("/", response_model=InitiativeRead, status_code=status.HTTP_201_CREATED)
async def create_initiative(initiative_in: InitiativeCreate, session: SessionDep, _: AdminUser) -> InitiativeRead:
    if await _initiative_name_exists(session, initiative_in.name):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Initiative name already exists")
    initiative = Initiative(name=initiative_in.name, description=initiative_in.description)
    if initiative_in.color:
        initiative.color = initiative_in.color
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)
    await session.refresh(initiative, attribute_names=["members"])
    return _serialize_initiative(initiative)


@router.patch("/{initiative_id}", response_model=InitiativeRead)
async def update_initiative(initiative_id: int, initiative_in: InitiativeUpdate, session: SessionDep, _: AdminUser) -> InitiativeRead:
    initiative = await _get_initiative_or_404(initiative_id, session)

    update_data = initiative_in.dict(exclude_unset=True)
    if "name" in update_data and update_data["name"] is not None:
        if await _initiative_name_exists(session, update_data["name"], exclude_initiative_id=initiative_id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Initiative name already exists")
    for field, value in update_data.items():
        setattr(initiative, field, value)
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)
    await session.refresh(initiative, attribute_names=["members"])
    return _serialize_initiative(initiative)


@router.delete("/{initiative_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_initiative(initiative_id: int, session: SessionDep, _: AdminUser) -> None:
    initiative = await _get_initiative_or_404(initiative_id, session)
    project_stmt = await session.exec(select(Project).where(Project.initiative_id == initiative_id))
    projects = project_stmt.all()
    for project in projects:
        await session.delete(project)
    await session.delete(initiative)
    await session.commit()


@router.post("/{initiative_id}/members", response_model=InitiativeRead, status_code=status.HTTP_200_OK)
async def add_initiative_member(initiative_id: int, payload: InitiativeMemberAdd, session: SessionDep, _: AdminUser) -> InitiativeRead:
    initiative = await _get_initiative_or_404(initiative_id, session)
    user_stmt = await session.exec(select(User).where(User.id == payload.user_id))
    user = user_stmt.one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    stmt = select(InitiativeMember).where(
        InitiativeMember.initiative_id == initiative_id,
        InitiativeMember.user_id == payload.user_id,
    )
    result = await session.exec(stmt)
    membership = result.one_or_none()
    if not membership:
        session.add(InitiativeMember(initiative_id=initiative_id, user_id=payload.user_id))
        await session.commit()
    await session.refresh(initiative)
    await session.refresh(initiative, attribute_names=["members"])
    return _serialize_initiative(initiative)


@router.delete("/{initiative_id}/members/{user_id}", response_model=InitiativeRead)
async def remove_initiative_member(initiative_id: int, user_id: int, session: SessionDep, _: AdminUser) -> InitiativeRead:
    initiative = await _get_initiative_or_404(initiative_id, session)
    stmt = select(InitiativeMember).where(
        InitiativeMember.initiative_id == initiative_id,
        InitiativeMember.user_id == user_id,
    )
    result = await session.exec(stmt)
    membership = result.one_or_none()
    if membership:
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
    await session.refresh(initiative)
    await session.refresh(initiative, attribute_names=["members"])
    return _serialize_initiative(initiative)
