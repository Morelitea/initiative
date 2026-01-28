from typing import Annotated, List
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select

from app.api.deps import SessionDep, require_roles
from app.models.user import User, UserRole
from app.models.user_token import UserTokenPurpose
from app.schemas.user import UserRead, UserRoleUpdate
from app.schemas.auth import VerificationSendResponse
from app.services import user_tokens
from app.services import email as email_service
from app.services import initiatives as initiatives_service
from app.services import users as users_service

router = APIRouter()

AdminUserDep = Annotated[User, Depends(require_roles(UserRole.admin))]


@router.get("/users", response_model=List[UserRead])
async def list_all_users(
    session: SessionDep,
    _current_user: AdminUserDep,
) -> List[User]:
    """List all users in the platform (admin only)."""
    from app.services.users import SYSTEM_USER_EMAIL

    stmt = select(User).where(User.email != SYSTEM_USER_EMAIL).order_by(User.created_at.asc())
    result = await session.exec(stmt)
    users = result.all()
    await initiatives_service.load_user_initiative_roles(session, users)
    return users


@router.post("/users/{user_id}/reset-password", response_model=VerificationSendResponse)
async def trigger_password_reset(
    user_id: int,
    session: SessionDep,
    _current_user: AdminUserDep,
) -> VerificationSendResponse:
    """Trigger a password reset email for a user (admin only)."""
    stmt = select(User).where(User.id == user_id)
    result = await session.exec(stmt)
    user = result.one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot reset password for inactive user")

    try:
        token = await user_tokens.create_token(
            session,
            user_id=user.id,
            purpose=UserTokenPurpose.password_reset,
            expires_minutes=60,
        )
        await email_service.send_password_reset_email(session, user, token)
    except email_service.EmailNotConfiguredError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SMTP settings are incomplete."
        ) from None
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc)
        ) from exc
    return VerificationSendResponse(status="sent")


@router.post("/users/{user_id}/reactivate", response_model=UserRead)
async def reactivate_user(
    user_id: int,
    session: SessionDep,
    _current_user: AdminUserDep,
) -> User:
    """Reactivate a deactivated user account (admin only)."""
    stmt = select(User).where(User.id == user_id)
    result = await session.exec(stmt)
    user = result.one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User is already active")

    user.is_active = True
    user.updated_at = datetime.now(timezone.utc)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    await initiatives_service.load_user_initiative_roles(session, [user])
    return user


@router.patch("/users/{user_id}/role", response_model=UserRead)
async def update_user_role(
    user_id: int,
    payload: UserRoleUpdate,
    session: SessionDep,
    current_user: AdminUserDep,
) -> User:
    """Update a user's platform role (admin only).

    Cannot change your own role or demote the last platform admin.
    """
    # Prevent changing own role
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change your own role. Another admin must do this.",
        )

    stmt = select(User).where(User.id == user_id)
    result = await session.exec(stmt)
    user = result.one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # If demoting an admin, check if they're the last one
    if user.role == UserRole.admin and payload.role != UserRole.admin:
        is_last = await users_service.is_last_platform_admin(session, user_id)
        if is_last:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot demote the last platform admin. Promote another user first.",
            )

    user.role = payload.role
    user.updated_at = datetime.now(timezone.utc)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    await initiatives_service.load_user_initiative_roles(session, [user])
    return user
