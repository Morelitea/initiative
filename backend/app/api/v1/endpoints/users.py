from datetime import datetime, timezone
from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select, delete

from app.api.deps import SessionDep, get_current_active_user, require_roles
from app.core.security import get_password_hash
from app.models.task import TaskAssignee
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserRead, UserSelfUpdate, UserUpdate

router = APIRouter()

AdminUser = Annotated[User, Depends(require_roles(UserRole.admin))]

SUPER_USER_ID = 1


@router.get("/me", response_model=UserRead)
async def read_users_me(current_user: Annotated[User, Depends(get_current_active_user)]) -> User:
    return current_user


@router.get("/", response_model=List[UserRead])
async def list_users(session: SessionDep, _: Annotated[User, Depends(get_current_active_user)]) -> List[User]:
    result = await session.exec(select(User))
    return result.all()


@router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(user_in: UserCreate, session: SessionDep, _: AdminUser) -> User:
    statement = select(User).where(User.email == user_in.email)
    result = await session.exec(statement)
    if result.one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    user = User(
        email=user_in.email,
        full_name=user_in.full_name,
        hashed_password=get_password_hash(user_in.password),
        role=user_in.role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.patch("/me", response_model=UserRead)
async def update_users_me(
    user_in: UserSelfUpdate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> User:
    update_data = user_in.dict(exclude_unset=True)
    if not update_data:
        return current_user

    new_full_name = update_data.get("full_name")
    if new_full_name is not None:
        current_user.full_name = new_full_name or None

    password = update_data.get("password")
    if password:
        current_user.hashed_password = get_password_hash(password)

    if "avatar_base64" in update_data:
        avatar_value = update_data["avatar_base64"]
        if avatar_value:
            current_user.avatar_base64 = avatar_value
            current_user.avatar_url = None
        else:
            current_user.avatar_base64 = None

    if "avatar_url" in update_data:
        url_value = update_data["avatar_url"]
        if url_value:
            current_user.avatar_url = url_value
            current_user.avatar_base64 = None
        else:
            current_user.avatar_url = None

    current_user.updated_at = datetime.now(timezone.utc)
    session.add(current_user)
    await session.commit()
    await session.refresh(current_user)
    return current_user


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(user_id: int, user_in: UserUpdate, session: SessionDep, _: AdminUser) -> User:
    result = await session.exec(select(User).where(User.id == user_id))
    user = result.one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    update_data = user_in.dict(exclude_unset=True)
    if user.id == SUPER_USER_ID and "role" in update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change the super user's role",
        )
    if (password := update_data.pop("password", None)):
        user.hashed_password = get_password_hash(password)
    if "avatar_base64" in update_data:
        user.avatar_base64 = update_data.pop("avatar_base64")
        if user.avatar_base64:
            user.avatar_url = None
    if "avatar_url" in update_data:
        user.avatar_url = update_data.pop("avatar_url")
        if user.avatar_url:
            user.avatar_base64 = None
    for field, value in update_data.items():
        setattr(user, field, value)
    user.updated_at = datetime.now(timezone.utc)

    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.post("/{user_id}/approve", response_model=UserRead)
async def approve_user(user_id: int, session: SessionDep, _: AdminUser) -> User:
    result = await session.exec(select(User).where(User.id == user_id))
    user = result.one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if not user.is_active:
        user.is_active = True
        user.updated_at = datetime.now(timezone.utc)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, session: SessionDep, current_admin: AdminUser) -> None:
    if user_id == SUPER_USER_ID:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete the super user")
    if user_id == current_admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot delete your own account")

    result = await session.exec(select(User).where(User.id == user_id))
    user = result.one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    await session.exec(delete(TaskAssignee).where(TaskAssignee.user_id == user_id))
    await session.delete(user)
    await session.commit()
