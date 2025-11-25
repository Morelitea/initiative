import asyncio

from sqlmodel import select

from app.core.config import settings
from app.core.security import get_password_hash
from app.db.session import AsyncSessionLocal, run_migrations
from app.models.user import User, UserRole
from app.services import app_settings as app_settings_service


async def init_superuser() -> None:
    if not (settings.FIRST_SUPERUSER_EMAIL and settings.FIRST_SUPERUSER_PASSWORD):
        return

    async with AsyncSessionLocal() as session:
        result = await session.exec(select(User).where(User.email == settings.FIRST_SUPERUSER_EMAIL))
        user = result.one_or_none()
        if user:
            return

        superuser = User(
            email=settings.FIRST_SUPERUSER_EMAIL,
            full_name=settings.FIRST_SUPERUSER_FULL_NAME,
            hashed_password=get_password_hash(settings.FIRST_SUPERUSER_PASSWORD),
            role=UserRole.admin,
            email_verified=True,
        )
        session.add(superuser)
        await session.commit()


async def init() -> None:
    await run_migrations()
    await init_superuser()
    async with AsyncSessionLocal() as session:
        await app_settings_service.get_or_create_app_settings(
            session, default_domains=settings.AUTO_APPROVED_EMAIL_DOMAINS
        )


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(init())
