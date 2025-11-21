from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api.deps import SessionDep, require_roles
from app.models.project import Project
from app.models.team import Team, TeamMember
from app.models.user import User, UserRole
from app.schemas.team import TeamCreate, TeamMemberAdd, TeamRead, TeamUpdate
from app.schemas.user import UserRead

router = APIRouter()

AdminUser = Annotated[User, Depends(require_roles(UserRole.admin))]


def _serialize_team(team: Team) -> TeamRead:
    members = [UserRead.model_validate(member) for member in team.members]
    return TeamRead(
        id=team.id,
        name=team.name,
        description=team.description,
        created_at=team.created_at,
        updated_at=team.updated_at,
        members=members,
    )


async def _get_team_or_404(team_id: int, session: SessionDep) -> Team:
    statement = select(Team).where(Team.id == team_id).options(selectinload(Team.members))
    result = await session.exec(statement)
    team = result.one_or_none()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    return team


@router.get("/", response_model=List[TeamRead])
async def list_teams(session: SessionDep, _: AdminUser) -> List[TeamRead]:
    statement = select(Team).options(selectinload(Team.members))
    result = await session.exec(statement)
    teams = result.all()
    return [_serialize_team(team) for team in teams]


@router.post("/", response_model=TeamRead, status_code=status.HTTP_201_CREATED)
async def create_team(team_in: TeamCreate, session: SessionDep, _: AdminUser) -> TeamRead:
    team = Team(name=team_in.name, description=team_in.description)
    session.add(team)
    await session.commit()
    await session.refresh(team)
    await session.refresh(team, attribute_names=["members"])
    return _serialize_team(team)


@router.patch("/{team_id}", response_model=TeamRead)
async def update_team(team_id: int, team_in: TeamUpdate, session: SessionDep, _: AdminUser) -> TeamRead:
    team = await _get_team_or_404(team_id, session)

    update_data = team_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(team, field, value)
    session.add(team)
    await session.commit()
    await session.refresh(team)
    await session.refresh(team, attribute_names=["members"])
    return _serialize_team(team)


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(team_id: int, session: SessionDep, _: AdminUser) -> None:
    team = await _get_team_or_404(team_id, session)
    project_stmt = await session.exec(select(Project).where(Project.team_id == team_id))
    projects = project_stmt.all()
    for project in projects:
        await session.delete(project)
    await session.delete(team)
    await session.commit()


@router.post("/{team_id}/members", response_model=TeamRead, status_code=status.HTTP_200_OK)
async def add_team_member(team_id: int, payload: TeamMemberAdd, session: SessionDep, _: AdminUser) -> TeamRead:
    team = await _get_team_or_404(team_id, session)
    user_stmt = await session.exec(select(User).where(User.id == payload.user_id))
    user = user_stmt.one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    stmt = select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == payload.user_id)
    result = await session.exec(stmt)
    membership = result.one_or_none()
    if not membership:
        session.add(TeamMember(team_id=team_id, user_id=payload.user_id))
        await session.commit()
    await session.refresh(team)
    await session.refresh(team, attribute_names=["members"])
    return _serialize_team(team)


@router.delete("/{team_id}/members/{user_id}", response_model=TeamRead)
async def remove_team_member(team_id: int, user_id: int, session: SessionDep, _: AdminUser) -> TeamRead:
    team = await _get_team_or_404(team_id, session)
    stmt = select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == user_id)
    result = await session.exec(stmt)
    membership = result.one_or_none()
    if membership:
        await session.delete(membership)
        await session.commit()
    await session.refresh(team)
    await session.refresh(team, attribute_names=["members"])
    return _serialize_team(team)
