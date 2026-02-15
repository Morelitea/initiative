import asyncio

from sqlmodel import select

from app.core.config import settings
from app.core.security import get_password_hash
from app.db.session import AdminSessionLocal, run_migrations
from app.models.user import User, UserRole
from app.models.guild import GuildRole
from app.services import app_settings as app_settings_service
from app.services import initiatives as initiatives_service
from app.services import guilds as guilds_service


async def init_superuser() -> None:
    if not (settings.FIRST_SUPERUSER_EMAIL and settings.FIRST_SUPERUSER_PASSWORD):
        return

    async with AdminSessionLocal() as session:
        async with session.begin():
            primary_guild = await guilds_service.get_primary_guild(session)
            result = await session.exec(select(User).where(User.email == settings.FIRST_SUPERUSER_EMAIL))
            user = result.one_or_none()
            if user:
                await guilds_service.ensure_membership(
                    session,
                    guild_id=primary_guild.id,
                    user_id=user.id,
                    role=GuildRole.admin,
                )
                await initiatives_service.ensure_default_initiative(session, user, guild_id=primary_guild.id)
                return

            superuser = User(
                email=settings.FIRST_SUPERUSER_EMAIL,
                full_name=settings.FIRST_SUPERUSER_FULL_NAME,
                hashed_password=get_password_hash(settings.FIRST_SUPERUSER_PASSWORD),
                role=UserRole.admin,
                email_verified=True,
            )
            session.add(superuser)
            await session.flush()
            await guilds_service.ensure_membership(
                session,
                guild_id=primary_guild.id,
                user_id=superuser.id,
                role=GuildRole.admin,
            )
            await initiatives_service.ensure_default_initiative(session, superuser, guild_id=primary_guild.id)


async def init() -> None:
    await run_migrations()
    await init_superuser()
    async with AdminSessionLocal() as session:
        await app_settings_service.get_or_create_guild_settings(session)


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(init())
