"""Tests for first-boot seeding (init_db)."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

import app.db.init_db as init_db
from app.core.config import settings
from app.core.encryption import hash_email
from app.models.guild import Guild
from app.models.user import User
from app.services import guilds as guilds_service

pytestmark = pytest.mark.database


async def test_init_superuser_cleans_up_when_guild_seed_fails(engine, monkeypatch):
    """A guild-seed failure during first-boot superuser init must undo the
    already-committed user + guild.

    Otherwise the committed user makes init_superuser short-circuit on every
    subsequent restart ("already seeded"), permanently stranding the primary
    guild without a schema. The cleanup mirrors the API/registration paths.
    """
    # init_superuser uses AdminSessionLocal (bound to the prod admin engine);
    # point it (and provisioning, via the autouse harness) at the test DB.
    test_sessions = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(init_db, "AdminSessionLocal", test_sessions)

    email = "init-boot-seedfail@example.com"
    monkeypatch.setattr(settings, "FIRST_SUPERUSER_EMAIL", email)
    monkeypatch.setattr(settings, "FIRST_SUPERUSER_PASSWORD", "securepassword123")
    monkeypatch.setattr(settings, "FIRST_SUPERUSER_FULL_NAME", "Boot Fail")

    async def _boom(seed_session, *args, **kwargs):
        # Abort the transaction like a real failing query would, so the cleanup
        # path must rollback before it can delete the stranded rows.
        await seed_session.execute(text("SELECT * FROM does_not_exist_xyz"))

    monkeypatch.setattr(guilds_service, "seed_guild_content", _boom)

    async with test_sessions() as pre:
        guilds_before = len((await pre.exec(select(Guild))).all())

    with pytest.raises(Exception):
        await init_db.init_superuser()

    async with test_sessions() as check:
        user = (
            await check.exec(select(User).where(User.email_hash == hash_email(email)))
        ).one_or_none()
        assert user is None, (
            "first-boot user must be removed so a restart re-initializes"
        )
        guilds_after = len((await check.exec(select(Guild))).all())
        assert guilds_after == guilds_before, "the primary guild must be removed too"
