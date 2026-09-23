"""Deleting a community keeps it, and the operator is what brings it back.

Covers the retention window end to end: what a delete leaves behind, who can
still reach it while it sits there, what the restore wizard's endpoint asks
for, and when the purge finally destroys it.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import config as config_module
from app.core.messages import GuildMessages
from app.models.platform.app_setting import DEFAULT_GUILD_RETENTION_DAYS
from app.models.platform.guild import (
    LIVE_STATUSES,
    OPERATOR_SETTABLE_STATUSES,
    Guild,
    GuildMembership,
    GuildRole,
    GuildStatus,
)
from app.models.platform.identity_ref import IdentityEntity, IdentityPurpose
from app.services.platform import billing_ping, guild_purge
from app.services.platform import guilds as guilds_service
from app.services.platform.identity_refs import billing_guild_ref, existing_ref
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
)

pytestmark = pytest.mark.integration

PASSWORD = "testpassword123"


async def _seated_guild(session: AsyncSession, **overrides):
    """A community with somebody holding its seat — the factory makes the row
    but no roster, and every rule here is about who is in it."""
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin, **overrides)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.superadmin
    )
    return admin, guild


async def _delete_via_danger_zone(
    client: AsyncClient, *, guild: Guild, headers: dict[str, str]
) -> None:
    response = await client.request(
        "DELETE",
        f"/api/v1/guilds/{guild.id}",
        headers=headers,
        json={
            "password": PASSWORD,
            "confirmation_text": f"DELETE COMMUNITY {guild.name.upper()}",
        },
    )
    assert response.status_code == 204, response.text


# ── The status set itself ───────────────────────────────────────────────────


def test_deleted_is_not_a_status_that_reaches_content():
    """The anti-drift guard.

    Every gate asks ``status in LIVE_STATUSES``. This pins what that set
    contains, so adding a status is a decision about which side it falls on
    rather than something that happens by default.
    """
    assert LIVE_STATUSES == {GuildStatus.active, GuildStatus.read_only}
    assert GuildStatus.deleted not in LIVE_STATUSES
    assert GuildStatus.deleted not in OPERATOR_SETTABLE_STATUSES
    # Every status is either live or refused — none is unaccounted for.
    assert set(GuildStatus) - LIVE_STATUSES == {
        GuildStatus.suspended,
        GuildStatus.deleted,
    }


# ── What a delete leaves behind ─────────────────────────────────────────────


async def test_deleting_keeps_the_row_the_roster_and_the_content(
    client: AsyncClient, session: AsyncSession
):
    admin, guild = await _seated_guild(session)
    member = await create_user(session)
    await create_guild_membership(session, user=member, guild=guild)

    await _delete_via_danger_zone(client, guild=guild, headers=get_auth_headers(admin))

    session.expunge_all()
    row = (await session.exec(select(Guild).where(Guild.id == guild.id))).one()
    assert row.status == GuildStatus.deleted.value
    # The deletion time, which is what the purge date counts from.
    assert row.status_changed_at is not None
    roster = (
        await session.exec(
            select(GuildMembership).where(GuildMembership.guild_id == guild.id)
        )
    ).all()
    assert len(roster) == 2, "the roster is what a restore brings back"


async def test_a_community_of_one_takes_its_roster_with_it(
    client: AsyncClient, session: AsyncSession
):
    """The single case where memberships go.

    That roster is one row describing the person doing the deleting. Every
    larger community keeps its own, because those rows are other people's.
    """
    admin, guild = await _seated_guild(session)

    await _delete_via_danger_zone(client, guild=guild, headers=get_auth_headers(admin))

    session.expunge_all()
    roster = (
        await session.exec(
            select(GuildMembership).where(GuildMembership.guild_id == guild.id)
        )
    ).all()
    assert roster == []
    # ...and what comes back therefore has to be seated.
    row = (await session.exec(select(Guild).where(Guild.id == guild.id))).one()
    assert row.status == GuildStatus.deleted.value


async def test_a_deleted_community_is_gone_for_its_admin_too(
    client: AsyncClient, session: AsyncSession
):
    """The carve-out that survives ``suspended`` does not survive deletion.

    A suspended community stays in its admins' list so they can still reach
    billing and the danger zone. A deleted one has no billing surface left and
    its danger zone has already been used, so it leaves every list.
    """
    admin, guild = await _seated_guild(session)
    # A second member, so the roster survives the delete and this is genuinely
    # testing the carve-out rather than an empty list.
    await create_guild_membership(session, user=await create_user(session), guild=guild)
    headers = get_auth_headers(admin)

    listed = await client.get("/api/v1/guilds/", headers=headers)
    assert [g["id"] for g in listed.json()] == [guild.id]

    await _delete_via_danger_zone(client, guild=guild, headers=headers)

    listed = await client.get("/api/v1/guilds/", headers=headers)
    assert listed.json() == []
    # And it is refused on the path, not merely hidden from the list.
    refused = await client.get(f"/api/v1/g/{guild.id}/initiatives/", headers=headers)
    assert refused.status_code == 403


async def test_deleting_the_community_unblocks_deleting_the_account(
    session: AsyncSession,
):
    """The ordinary way out: delete your community, then your account.

    The sole-seat rule exists so a *live* community always keeps somebody who
    can run it. A deleted one has nothing to run, so holding its seat blocks
    nothing.
    """
    from app.services.platform import users as users_service

    holder, guild = await _seated_guild(session)
    await create_guild_membership(session, user=await create_user(session), guild=guild)

    can_delete, blockers = await users_service.check_deletion_eligibility(
        session, holder.id
    )
    assert can_delete is False and blockers, "precondition: the seat blocks"

    row = (await session.exec(select(Guild).where(Guild.id == guild.id))).one()
    await guilds_service.soft_delete_guild(session, row, actor_user_id=holder.id)
    await session.commit()

    can_delete, blockers = await users_service.check_deletion_eligibility(
        session, holder.id
    )
    assert can_delete is True, blockers


# ── Restore ─────────────────────────────────────────────────────────────────


async def test_restore_brings_it_back_at_the_status_the_operator_names(
    client: AsyncClient, session: AsyncSession, acting_user
):
    operator = await acting_user("owner")
    admin, guild = await _seated_guild(session)
    # Two members, so the roster — and with it the seat — survives the delete
    # and the restore has nothing to ask about.
    await create_guild_membership(session, user=await create_user(session), guild=guild)
    await _delete_via_danger_zone(client, guild=guild, headers=get_auth_headers(admin))

    response = await client.post(
        f"/api/v1/settings/guilds/{guild.id}/restore",
        headers=operator.headers,
        json={"status": "read_only"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "read_only"
    assert response.json()["purge_at"] is None

    # And its admin has it back.
    listed = await client.get("/api/v1/guilds/", headers=get_auth_headers(admin))
    assert [g["id"] for g in listed.json()] == [guild.id]


async def _billing_ref(guild_id: int) -> str | None:
    return await existing_ref(
        entity_type=IdentityEntity.guild,
        entity_id=guild_id,
        purpose=IdentityPurpose.billing,
    )


@pytest.fixture
def lifecycle_pings(monkeypatch):
    """Billing configured, and the lifecycle pings captured instead of sent."""
    monkeypatch.setattr(
        config_module.settings, "BILLING_SERVICE_URL", "https://billing.internal"
    )
    monkeypatch.setattr(config_module.settings, "BILLING_HMAC_SECRET", "ping-secret")
    sent: list[int] = []

    async def _capture(guild_id: int) -> None:
        sent.append(guild_id)

    monkeypatch.setattr(billing_ping, "_send_lifecycle_ping", _capture)
    return sent


async def test_billing_keeps_its_name_for_a_deleted_community_and_hears_both_ways(
    client: AsyncClient, session: AsyncSession, acting_user, lifecycle_pings
):
    """Billing charges a deleted community until it learns otherwise, and learns
    it by asking about the name it already holds. Dropping that name at the
    delete left billing unable to ask — and a restore came back as a community
    billing had never seen, on the free plan."""
    operator = await acting_user("owner")
    admin, guild = await _seated_guild(session)
    await create_guild_membership(session, user=await create_user(session), guild=guild)
    ref = await billing_guild_ref(guild_id=guild.id)

    await _delete_via_danger_zone(client, guild=guild, headers=get_auth_headers(admin))
    assert await _billing_ref(guild.id) == ref
    assert lifecycle_pings == [guild.id]

    response = await client.post(
        f"/api/v1/settings/guilds/{guild.id}/restore",
        headers=operator.headers,
        json={"status": "active"},
    )
    assert response.status_code == 200, response.text
    assert await _billing_ref(guild.id) == ref
    assert lifecycle_pings == [guild.id, guild.id]


async def test_the_purge_is_what_drops_billings_name(
    client: AsyncClient, session: AsyncSession
):
    admin, guild = await _seated_guild(session)
    await billing_guild_ref(guild_id=guild.id)
    await _delete_via_danger_zone(client, guild=guild, headers=get_auth_headers(admin))
    session.expunge_all()
    row = (await session.exec(select(Guild).where(Guild.id == guild.id))).one()

    await guild_purge.purge_due_guilds(
        session,
        now=guild_purge.purge_at(row.status_changed_at, DEFAULT_GUILD_RETENTION_DAYS)
        + timedelta(minutes=1),
    )

    assert await _billing_ref(guild.id) is None


async def test_restore_refuses_a_community_that_is_not_deleted(
    client: AsyncClient, session: AsyncSession, acting_user
):
    operator = await acting_user("owner")
    guild = await create_guild(session, creator=await create_user(session))

    response = await client.post(
        f"/api/v1/settings/guilds/{guild.id}/restore",
        headers=operator.headers,
        json={"status": "active"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == GuildMessages.GUILD_NOT_DELETED


async def test_restore_needs_a_capability(
    client: AsyncClient, session: AsyncSession, acting_user
):
    plain = await acting_user("member")
    guild = await create_guild(session, creator=await create_user(session))

    response = await client.post(
        f"/api/v1/settings/guilds/{guild.id}/restore",
        headers=plain.headers,
        json={"status": "active"},
    )
    assert response.status_code == 403


async def test_restore_asks_for_a_seat_when_the_roster_holds_none(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """What the operator deletion leaves, and what the wizard's second step is
    for: a community with nobody who can run it cannot simply be switched on."""
    operator = await acting_user("owner")
    _admin, guild = await _seated_guild(session)
    row = (await session.exec(select(Guild).where(Guild.id == guild.id))).one()
    # A community of one takes its roster with it, which is what leaves a
    # restore with nobody to run it.
    await guilds_service.soft_delete_guild(
        session, row, actor_user_id=operator.user.id, via="operator"
    )
    await session.commit()
    session.expunge_all()

    listed = await client.get("/api/v1/settings/guilds", headers=operator.headers)
    entry = next(g for g in listed.json() if g["id"] == guild.id)
    assert entry["has_seat"] is False
    assert entry["purge_at"] is not None

    refused = await client.post(
        f"/api/v1/settings/guilds/{guild.id}/restore",
        headers=operator.headers,
        json={"status": "active"},
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == GuildMessages.GUILD_RESTORE_SEAT_REQUIRED

    seated = await create_user(session)
    response = await client.post(
        f"/api/v1/settings/guilds/{guild.id}/restore",
        headers=operator.headers,
        json={"status": "active", "seat_user_id": seated.id},
    )
    assert response.status_code == 200, response.text
    assert response.json()["has_seat"] is True

    session.expunge_all()
    membership = (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.guild_id == guild.id,
                GuildMembership.user_id == seated.id,
            )
        )
    ).one()
    assert membership.role == GuildRole.superadmin


async def test_the_status_control_cannot_delete_a_community(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """``deleted`` is reached by deleting and left by restoring, never by the
    dropdown — which would skip revoking the community's app grants."""
    operator = await acting_user("owner")
    guild = await create_guild(session, creator=await create_user(session))

    response = await client.patch(
        f"/api/v1/settings/guilds/{guild.id}",
        headers=operator.headers,
        json={"status": "deleted"},
    )
    assert response.status_code == 422


# ── The purge ───────────────────────────────────────────────────────────────


async def test_the_purge_waits_out_the_whole_window(
    client: AsyncClient, session: AsyncSession
):
    admin, guild = await _seated_guild(session)
    await _delete_via_danger_zone(client, guild=guild, headers=get_auth_headers(admin))
    session.expunge_all()

    row = (await session.exec(select(Guild).where(Guild.id == guild.id))).one()
    deleted_at = row.status_changed_at
    assert deleted_at is not None
    assert guild_purge.purge_at(
        deleted_at, DEFAULT_GUILD_RETENTION_DAYS
    ) == deleted_at + timedelta(days=DEFAULT_GUILD_RETENTION_DAYS)

    session.expunge_all()
    assert (
        await guild_purge.purge_due_guilds(
            session,
            now=guild_purge.purge_at(deleted_at, DEFAULT_GUILD_RETENTION_DAYS)
            - timedelta(minutes=1),
        )
        == 0
    )
    assert (
        await session.exec(select(Guild).where(Guild.id == guild.id))
    ).one_or_none() is not None

    session.expunge_all()
    assert (
        await guild_purge.purge_due_guilds(
            session,
            now=guild_purge.purge_at(deleted_at, DEFAULT_GUILD_RETENTION_DAYS)
            + timedelta(minutes=1),
        )
        == 1
    )
    assert (
        await session.exec(select(Guild).where(Guild.id == guild.id))
    ).one_or_none() is None


async def test_the_window_is_the_deployments_to_set(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """One figure for the whole server, set by whoever runs it."""
    operator = await acting_user("owner")
    admin, guild = await _seated_guild(session)
    await _delete_via_danger_zone(client, guild=guild, headers=get_auth_headers(admin))

    response = await client.put(
        "/api/v1/settings/community",
        headers=operator.headers,
        json={
            "community_directory_enabled": False,
            "deleted_community_retention_days": 7,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["deleted_community_retention_days"] == 7

    session.expunge_all()
    row = (await session.exec(select(Guild).where(Guild.id == guild.id))).one()
    deleted_at = row.status_changed_at
    assert deleted_at is not None

    # The window is counted from each deletion rather than stamped at the time,
    # so shortening it moves what is already deleted.
    session.expunge_all()
    assert (
        await guild_purge.purge_due_guilds(session, now=deleted_at + timedelta(days=6))
        == 0
    )
    session.expunge_all()
    assert (
        await guild_purge.purge_due_guilds(session, now=deleted_at + timedelta(days=8))
        == 1
    )


async def test_a_deployment_can_keep_deleted_communities_forever(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Clearing the figure means never destroy one.

    For a deployment that has undertaken to keep what its members put in it:
    deleted communities sit in the operator's list until somebody acts.
    """
    operator = await acting_user("owner")
    admin, guild = await _seated_guild(session)
    await _delete_via_danger_zone(client, guild=guild, headers=get_auth_headers(admin))

    response = await client.put(
        "/api/v1/settings/community",
        headers=operator.headers,
        json={
            "community_directory_enabled": False,
            "deleted_community_retention_days": None,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["deleted_community_retention_days"] is None

    session.expunge_all()
    assert (
        await guild_purge.purge_due_guilds(
            session, now=datetime.now(timezone.utc) + timedelta(days=3650)
        )
        == 0
    )
    assert (
        await session.exec(select(Guild).where(Guild.id == guild.id))
    ).one_or_none() is not None

    # And the operator's list says there is no date, rather than inventing one.
    listed = await client.get("/api/v1/settings/guilds", headers=operator.headers)
    entry = next(g for g in listed.json() if g["id"] == guild.id)
    assert entry["status"] == "deleted"
    assert entry["purge_at"] is None


async def test_omitting_the_window_leaves_it_alone(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """``null`` is an answer here, so only sending the field counts as one."""
    operator = await acting_user("owner")

    await client.put(
        "/api/v1/settings/community",
        headers=operator.headers,
        json={
            "community_directory_enabled": False,
            "deleted_community_retention_days": 30,
        },
    )
    response = await client.put(
        "/api/v1/settings/community",
        headers=operator.headers,
        json={"community_directory_enabled": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["deleted_community_retention_days"] == 30


async def test_the_purge_leaves_live_communities_alone(session: AsyncSession):
    """Every status but ``deleted`` is somebody's community, however frozen."""
    kept = []
    for status in OPERATOR_SETTABLE_STATUSES:
        guild = await create_guild(session, creator=await create_user(session))
        row = (await session.exec(select(Guild).where(Guild.id == guild.id))).one()
        row.status = status.value
        row.status_changed_at = datetime.now(timezone.utc) - timedelta(days=365)
        session.add(row)
        kept.append(guild.id)
    await session.commit()
    session.expunge_all()

    assert (
        await guild_purge.purge_due_guilds(session, now=datetime.now(timezone.utc)) == 0
    )
    for guild_id in kept:
        assert (
            await session.exec(select(Guild).where(Guild.id == guild_id))
        ).one_or_none() is not None


@pytest.mark.integration
async def test_deleting_a_community_writes_to_the_seat_that_could_restore_it(session):
    """The superadmin seat hears. An ordinary admin cannot ask for a restore,
    and members learn from it leaving their lists."""
    from app.models.platform.guild import GuildRole
    from app.services.platform import guilds as guilds_service
    from app.testing import create_guild_membership, create_user

    seat = await create_user(session, email="gd-seat@example.com")
    guild = await create_guild(session, creator=seat, name="Allotment Society")
    await create_guild_membership(
        session, user=seat, guild=guild, role=GuildRole.superadmin
    )
    boss = await create_user(session, email="gd-admin@example.com")
    await create_guild_membership(session, user=boss, guild=guild, role=GuildRole.admin)
    hand = await create_user(session, email="gd-member@example.com")
    await create_guild_membership(
        session, user=hand, guild=guild, role=GuildRole.member
    )

    notice = await guilds_service.soft_delete_guild(
        session, guild, actor_user_id=seat.id
    )

    assert notice.community_name == "Allotment Society"
    assert notice.recipients == ["gd-seat@example.com"]


@pytest.mark.integration
async def test_the_notice_is_gathered_before_the_roster_goes(session):
    """A community of one loses its roster on the way out, so the person to
    tell has to be read while they are still in it."""
    from app.models.platform.guild import GuildRole
    from app.services.platform import guilds as guilds_service
    from app.testing import create_guild_membership, create_user

    alone = await create_user(session, email="gd-solo@example.com")
    guild = await create_guild(session, creator=alone, name="Just Me")
    await create_guild_membership(
        session, user=alone, guild=guild, role=GuildRole.superadmin
    )

    notice = await guilds_service.soft_delete_guild(
        session, guild, actor_user_id=alone.id
    )

    assert notice.recipients == ["gd-solo@example.com"]
