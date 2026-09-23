"""Tests for first-boot seeding (init_db)."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

import app.db.init_db as init_db
from app.core.config import settings
from app.core.encryption import hash_email
from app.models.platform.guild import Guild
from app.models.platform.user_email import UserEmail
from app.models.platform.user import User
from app.services.platform import guilds as guilds_service

pytestmark = pytest.mark.database


async def test_init_owner_cleans_up_when_guild_seed_fails(engine, monkeypatch):
    """A guild-seed failure during first-boot superuser init must undo the
    already-committed user + guild.

    Otherwise the committed user makes init_owner short-circuit on every
    subsequent restart ("already seeded"), permanently stranding the primary
    guild without a schema. The cleanup mirrors the API/registration paths.
    """
    # init_owner uses SystemSessionLocal (bound to the prod system engine);
    # point it (and provisioning, via the autouse harness) at the test DB.
    test_sessions = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(init_db, "SystemSessionLocal", test_sessions)

    email = "init-boot-seedfail@example.com"
    monkeypatch.setattr(settings, "FIRST_OWNER_EMAIL", email)
    monkeypatch.setattr(settings, "FIRST_OWNER_PASSWORD", "securepassword123")
    monkeypatch.setattr(settings, "FIRST_OWNER_FULL_NAME", "Boot Fail")

    async def _boom(seed_session, *args, **kwargs):
        # Abort the transaction like a real failing query would, so the cleanup
        # path must rollback before it can delete the stranded rows.
        await seed_session.exec(text("SELECT * FROM does_not_exist_xyz"))

    monkeypatch.setattr(guilds_service, "seed_guild_content", _boom)

    async with test_sessions() as pre:
        guilds_before = len((await pre.exec(select(Guild))).all())

    with pytest.raises(Exception):
        await init_db.init_owner()

    async with test_sessions() as check:
        user = (
            await check.exec(
                select(User)
                .join(UserEmail, UserEmail.user_id == User.id)
                .where(UserEmail.email_hash == hash_email(email))
            )
        ).one_or_none()
        assert user is None, (
            "first-boot user must be removed so a restart re-initializes"
        )
        guilds_after = len((await check.exec(select(Guild))).all())
        assert guilds_after == guilds_before, "the primary guild must be removed too"


@pytest.mark.unit
def test_stamp_this_image_lacks_is_refused_with_instructions():
    """A database stamped ahead of the image stops the boot with a message.

    The message is the whole point: it names the revision the database is at,
    the newest one this image has, and the way back, in place of alembic's
    "Can't locate revision identified by ..." raised from inside the lifespan.
    """
    revisions, head = init_db.migration_chain()
    assert head is not None and head in revisions

    with pytest.raises(SystemExit) as refused:
        init_db._require_image_knows([head, "20991231_9999"])

    said = str(refused.value)
    assert "20991231_9999" in said
    assert head in said
    # The one the image does have is not reported as ahead of it.
    assert said.count(head) == 1


@pytest.mark.unit
def test_stamp_this_image_has_passes():
    """The ordinary upgrade — every stamped revision is in the chain."""
    revisions, head = init_db.migration_chain()
    assert init_db._require_image_knows([head]) is None
    assert init_db._require_image_knows(sorted(revisions)[:5]) is None


@pytest.mark.unit
def test_unreadable_chain_is_left_to_alembic(monkeypatch):
    """Nothing to compare against is not evidence the database is ahead."""
    monkeypatch.setattr(init_db, "migration_chain", lambda: (frozenset(), None))
    assert init_db._require_image_knows(["20991231_9999"]) is None
