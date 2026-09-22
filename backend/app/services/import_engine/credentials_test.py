"""The credential lifecycle: it is there for one job, and then it is not."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from app.models.platform.import_credential import ImportCredential
from app.services.import_engine import credentials as import_credentials
from app.testing.factories import create_guild, create_user

pytestmark = pytest.mark.integration


async def _store(guild, user, secret: str = "shhh") -> int:
    return await import_credentials.store(
        guild_id=guild.id,
        user_id=user.id,
        provider="atlassian",
        site_url="https://acme.atlassian.net",
        principal="someone@example.com",
        secret=secret,
    )


async def test_a_stored_credential_reads_back_with_its_secret(session):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)

    credential_id = await _store(guild, user)
    loaded = await import_credentials.load(credential_id, guild_id=guild.id)

    assert loaded is not None
    assert loaded.secret == "shhh"
    assert loaded.provider == "atlassian"
    assert loaded.site_url == "https://acme.atlassian.net"
    assert loaded.principal == "someone@example.com"
    assert loaded.created_by == user.id


async def test_the_secret_is_not_in_the_column(session):
    """At rest it is ciphertext. The column is the only place the value
    lives, so this is the only place that can be checked."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)

    credential_id = await _store(guild, user, secret="hunter2")
    row = await session.get(ImportCredential, credential_id)

    assert row is not None
    assert "hunter2" not in row.secret_encrypted


async def test_another_guilds_credential_is_not_readable(session):
    """The id comes off a job row, which is data — so the guild is checked
    rather than assumed."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    other = await create_guild(session, creator=user)

    credential_id = await _store(guild, user)

    assert await import_credentials.load(credential_id, guild_id=other.id) is None


async def test_an_elapsed_credential_is_not_usable_even_before_the_sweep(session):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)

    credential_id = await _store(guild, user)
    row = await session.get(ImportCredential, credential_id)
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    session.add(row)
    await session.commit()

    assert await import_credentials.load(credential_id, guild_id=guild.id) is None


async def test_discarding_is_the_end_of_it_and_is_idempotent(session):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)

    credential_id = await _store(guild, user)
    await import_credentials.discard(credential_id)

    assert await import_credentials.load(credential_id, guild_id=guild.id) is None
    # A job can reach a terminal state twice over a restart; the second
    # discard must be a no-op rather than an error.
    await import_credentials.discard(credential_id)
    await import_credentials.discard(None)


async def test_the_sweep_takes_the_elapsed_and_leaves_the_live(session):
    """The backstop under every discard: a credential whose job never reached
    a transition to be cleaned up by."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)

    stale_id = await _store(guild, user)
    live_id = await _store(guild, user)
    stale = await session.get(ImportCredential, stale_id)
    stale.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    session.add(stale)
    await session.commit()

    await import_credentials.sweep_expired()

    remaining = {
        row.id
        for row in (
            await session.exec(
                select(ImportCredential).where(ImportCredential.guild_id == guild.id)
            )
        ).all()
    }
    assert remaining == {live_id}


async def test_describing_one_names_the_site_and_only_for_its_owner(session):
    """The request path's view of a credential: whose, which site, and no
    secret. Anybody who is not the person who connected gets nothing — the id
    arrives in a request body, and knowing a number is not owning it."""
    user = await create_user(session)
    stranger = await create_user(session)
    guild = await create_guild(session, creator=user)
    other = await create_guild(session, creator=user)

    credential_id = await _store(guild, user)

    summary = await import_credentials.describe(
        credential_id, guild_id=guild.id, user_id=user.id
    )
    assert summary is not None
    assert summary.site_url == "https://acme.atlassian.net"
    assert summary.provider == "atlassian"
    assert not hasattr(summary, "secret")

    assert (
        await import_credentials.describe(
            credential_id, guild_id=guild.id, user_id=stranger.id
        )
        is None
    )
    assert (
        await import_credentials.describe(
            credential_id, guild_id=other.id, user_id=user.id
        )
        is None
    )


async def test_an_elapsed_credential_describes_as_nothing(session):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)

    credential_id = await _store(guild, user)
    row = await session.get(ImportCredential, credential_id)
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    session.add(row)
    await session.commit()

    assert (
        await import_credentials.describe(
            credential_id, guild_id=guild.id, user_id=user.id
        )
        is None
    )
