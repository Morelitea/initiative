"""Deleting an account keeps it, and coming back is what calls it off.

Covers the window end to end: what a deletion leaves behind, who can still see
the account while it sits there, the two ways back, and when the erasure that
used to run immediately actually runs.
"""

from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import OperatorMessages
from app.models.platform.app_setting import DEFAULT_ACCOUNT_RETENTION_DAYS
from app.models.platform.guild import GuildMembership, GuildRole
from app.models.platform.user import (
    ABSENT_STATUSES,
    SIGN_IN_STATUSES,
    User,
    UserStatus,
)
from app.services.platform import account_purge
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
)


PASSWORD = "testpassword123"


async def _delete_own_account(client: AsyncClient, user: User) -> None:
    response = await client.post(
        "/api/v1/users/me/delete-account",
        headers=get_auth_headers(user),
        json={
            "action": "soft_delete",
            "password": PASSWORD,
            "confirmation_text": "DELETE MY ACCOUNT",
        },
    )
    assert response.status_code == 200, response.text


# ── The status set itself ───────────────────────────────────────────────────


def test_deleted_is_absent_but_may_still_sign_in():
    """The two sets that make the window work, pinned.

    An account on its way out is absent from everywhere people are listed, and
    is still allowed to reach a sign-in — because reaching one is how the
    deletion is called off.
    """
    assert UserStatus.deleted in ABSENT_STATUSES
    assert UserStatus.deleted in SIGN_IN_STATUSES
    # A suspension is the other absence. It signs in, to be told it is in
    # time out, and reaches nothing else.
    assert UserStatus.suspended in ABSENT_STATUSES
    assert UserStatus.suspended in SIGN_IN_STATUSES
    # Somebody taking a break is neither: they are not erased by a timer, and
    # an operator is what brings them back.
    assert UserStatus.deactivated not in ABSENT_STATUSES
    assert UserStatus.deactivated not in SIGN_IN_STATUSES


# ── What a deletion leaves behind ───────────────────────────────────────────


async def test_deleting_keeps_the_account_and_everything_it_holds(
    client: AsyncClient, session: AsyncSession
):
    """The whole difference from deactivating: nothing is dropped.

    Memberships stay, so coming back restores the account whole rather than to
    one with no communities.
    """
    user = await create_user(session)
    guild = await create_guild(session, creator=await create_user(session))
    await create_guild_membership(session, user=user, guild=guild)

    await _delete_own_account(client, user)

    session.expunge_all()
    row = (await session.exec(select(User).where(User.id == user.id))).one()
    assert row.status == UserStatus.deleted
    # When it was asked for, which is what the erasure date counts from.
    assert row.status_changed_at is not None
    # Its personal details are untouched — nothing has been erased yet.
    assert row.full_name == user.full_name

    roster = (
        await session.exec(
            select(GuildMembership).where(GuildMembership.user_id == user.id)
        )
    ).all()
    assert len(roster) == 1, "memberships are what a restore brings back"


async def test_a_deleted_account_is_gone_from_the_roster(
    client: AsyncClient, session: AsyncSession
):
    """Absent to everybody else, for as long as it sits there."""
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.superadmin
    )
    leaver = await create_user(session)
    await create_guild_membership(session, user=leaver, guild=guild)

    listed = await client.get(
        f"/api/v1/c/{guild.id}/users/", headers=get_auth_headers(admin)
    )
    assert leaver.id in [u["id"] for u in listed.json()]

    await _delete_own_account(client, leaver)

    listed = await client.get(
        f"/api/v1/c/{guild.id}/users/", headers=get_auth_headers(admin)
    )
    assert leaver.id not in [u["id"] for u in listed.json()]


async def test_a_deleted_account_is_not_a_seat(
    client: AsyncClient, session: AsyncSession
):
    """Two seat holders must not each leave by counting the other.

    The membership row survives the window, so a count that read rows rather
    than accounts would let the second one go and leave the community with
    nobody who can run it.
    """
    from app.services.platform import guilds as guilds_service

    first = await create_user(session)
    second = await create_user(session)
    guild = await create_guild(session, creator=first)
    await create_guild_membership(
        session, user=first, guild=guild, role=GuildRole.superadmin
    )
    await create_guild_membership(
        session, user=second, guild=guild, role=GuildRole.superadmin
    )

    await _delete_own_account(client, first)
    session.expunge_all()

    # The second one is now the only live seat, so their own deletion is
    # refused rather than stranding the community.
    assert await guilds_service.must_keep_superadmin(
        session, guild_id=guild.id, user_id=second.id
    )


# ── Coming back ─────────────────────────────────────────────────────────────


async def test_signing_in_calls_the_deletion_off(
    client: AsyncClient, session: AsyncSession
):
    """The ordinary way back, and the reason ``deleted`` may sign in at all."""
    user = await create_user(session)
    await _delete_own_account(client, user)
    session.expunge_all()

    response = await client.post(
        "/api/v1/auth/token",
        data={"username": user.seeded_address, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text

    session.expunge_all()
    row = (await session.exec(select(User).where(User.id == user.id))).one()
    assert row.status == UserStatus.active


async def test_an_operator_can_call_it_off_too(
    client: AsyncClient, session: AsyncSession, acting_user
):
    operator = await acting_user("owner")
    user = await create_user(session)
    await _delete_own_account(client, user)
    session.expunge_all()

    response = await client.post(
        f"/api/v1/operator/users/{user.id}/restore", headers=operator.headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "active"
    assert response.json()["purge_at"] is None


async def test_restore_refuses_an_account_that_is_not_deleted(
    client: AsyncClient, session: AsyncSession, acting_user
):
    operator = await acting_user("owner")
    user = await create_user(session)

    response = await client.post(
        f"/api/v1/operator/users/{user.id}/restore", headers=operator.headers
    )
    assert response.status_code == 409
    assert response.json()["detail"] == OperatorMessages.USER_NOT_DELETED


async def test_restore_needs_a_capability(
    client: AsyncClient, session: AsyncSession, acting_user
):
    plain = await acting_user("member")
    user = await create_user(session)

    response = await client.post(
        f"/api/v1/operator/users/{user.id}/restore", headers=plain.headers
    )
    assert response.status_code == 403


# ── The erasure ─────────────────────────────────────────────────────────────


async def test_the_purge_waits_out_the_window_then_erases(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    await _delete_own_account(client, user)
    session.expunge_all()

    row = (await session.exec(select(User).where(User.id == user.id))).one()
    asked = row.status_changed_at
    assert asked is not None
    assert account_purge.erase_at(
        asked, DEFAULT_ACCOUNT_RETENTION_DAYS
    ) == asked + timedelta(days=DEFAULT_ACCOUNT_RETENTION_DAYS)

    session.expunge_all()
    assert (
        await account_purge.purge_due_accounts(
            session,
            now=account_purge.erase_at(asked, DEFAULT_ACCOUNT_RETENTION_DAYS)
            - timedelta(minutes=1),
        )
        == 0
    )

    session.expunge_all()
    assert (
        await account_purge.purge_due_accounts(
            session,
            now=account_purge.erase_at(asked, DEFAULT_ACCOUNT_RETENTION_DAYS)
            + timedelta(minutes=1),
        )
        == 1
    )
    session.expunge_all()
    row = (await session.exec(select(User).where(User.id == user.id))).one()
    # What the erasure produces is exactly what it produced before there was a
    # window: an anonymized husk, not a missing row.
    assert row.status == UserStatus.anonymized


async def test_each_account_is_erased_and_told_once(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """An account another sweep is erasing is left to it, and one already
    erased is not erased again: the receipt goes once."""
    from app.db.session import SystemSessionLocal
    from app.services import email as email_service

    letters: list[list[str]] = []

    async def _record(_session, *, recipients, locale="en"):
        letters.append(list(recipients))

    monkeypatch.setattr(email_service, "announce_account_erased", _record)
    user = await create_user(session)
    await _delete_own_account(client, user)
    session.expunge_all()
    later = datetime.now(timezone.utc) + timedelta(
        days=DEFAULT_ACCOUNT_RETENTION_DAYS + 1
    )

    async with SystemSessionLocal() as other_sweep:
        await other_sweep.exec(
            select(User.id).where(User.id == user.id).with_for_update()
        )
        assert await account_purge.purge_due_accounts(session, now=later) == 0
        await other_sweep.rollback()

    session.expunge_all()
    assert await account_purge.purge_due_accounts(session, now=later) == 1
    session.expunge_all()
    assert await account_purge.purge_due_accounts(session, now=later) == 0
    assert len(letters) == 1


async def test_the_purge_leaves_every_other_status_alone(session: AsyncSession):
    """Somebody on a break is never erased by a timer."""
    kept: list[int] = []
    for status in (UserStatus.active, UserStatus.suspended, UserStatus.deactivated):
        user = await create_user(session)
        row = (await session.exec(select(User).where(User.id == user.id))).one()
        row.status = status
        row.status_changed_at = datetime.now(timezone.utc) - timedelta(days=365)
        session.add(row)
        kept.append(user.id)
    await session.commit()
    session.expunge_all()

    assert (
        await account_purge.purge_due_accounts(session, now=datetime.now(timezone.utc))
        == 0
    )
    for user_id in kept:
        row = (await session.exec(select(User).where(User.id == user_id))).one()
        assert row.status != UserStatus.anonymized


async def test_a_deployment_can_keep_deleted_accounts_forever(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Blank means never, for a deployment required to keep accounts."""
    operator = await acting_user("owner")
    user = await create_user(session)
    await _delete_own_account(client, user)

    response = await client.put(
        "/api/v1/settings/community",
        headers=operator.headers,
        json={
            "community_directory_enabled": False,
            "deleted_account_retention_days": None,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["deleted_account_retention_days"] is None

    session.expunge_all()
    assert (
        await account_purge.purge_due_accounts(
            session, now=datetime.now(timezone.utc) + timedelta(days=3650)
        )
        == 0
    )
    session.expunge_all()
    row = (await session.exec(select(User).where(User.id == user.id))).one()
    assert row.status == UserStatus.deleted


async def test_the_window_is_the_deployments_to_set(
    client: AsyncClient, session: AsyncSession, acting_user
):
    operator = await acting_user("owner")
    user = await create_user(session)
    await _delete_own_account(client, user)

    response = await client.put(
        "/api/v1/settings/community",
        headers=operator.headers,
        json={
            "community_directory_enabled": False,
            "deleted_account_retention_days": 7,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["deleted_account_retention_days"] == 7

    session.expunge_all()
    row = (await session.exec(select(User).where(User.id == user.id))).one()
    asked = row.status_changed_at
    assert asked is not None

    session.expunge_all()
    assert (
        await account_purge.purge_due_accounts(session, now=asked + timedelta(days=6))
        == 0
    )
    session.expunge_all()
    assert (
        await account_purge.purge_due_accounts(session, now=asked + timedelta(days=8))
        == 1
    )


async def test_the_operator_shape_carries_the_erasure_date(
    client: AsyncClient, session: AsyncSession, acting_user
):
    operator = await acting_user("owner")
    user = await create_user(session)
    await _delete_own_account(client, user)
    session.expunge_all()

    listed = await client.get("/api/v1/operator/users", headers=operator.headers)
    entry = next(u for u in listed.json()["items"] if u["id"] == user.id)
    assert entry["status"] == "deleted"
    assert entry["purge_at"] is not None


async def test_deactivating_still_drops_memberships(
    client: AsyncClient, session: AsyncSession
):
    """Untouched. Two different things that must keep being two things."""
    user = await create_user(session)
    guild = await create_guild(session, creator=await create_user(session))
    await create_guild_membership(session, user=user, guild=guild)

    response = await client.post(
        "/api/v1/users/me/delete-account",
        headers=get_auth_headers(user),
        json={
            "action": "deactivate",
            "password": PASSWORD,
            "confirmation_text": "DEACTIVATE MY ACCOUNT",
        },
    )
    assert response.status_code == 200, response.text

    session.expunge_all()
    row = (await session.exec(select(User).where(User.id == user.id))).one()
    assert row.status == UserStatus.deactivated
    roster = (
        await session.exec(
            select(GuildMembership).where(GuildMembership.user_id == user.id)
        )
    ).all()
    assert roster == []
