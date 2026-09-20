"""Integration tests for platform-admin endpoints at /api/v1/admin."""

import csv
import io

import pytest
from sqlmodel import select

from app.core.messages import AdminMessages, InitiativeMessages
from app.models.platform.guild import (
    Guild,
    GuildMembership,
    GuildRole,
    GuildStatus,
)
from app.models.platform.user import User, UserRole
from app.services.platform import users as users_service
from app.testing.factories import create_guild, create_guild_membership, create_user


#: Every test here drives the API through the real app and a real database.
pytestmark = pytest.mark.integration


def _parse_csv(body: bytes) -> tuple[list[str], list[list[str]]]:
    """Strip the UTF-8 BOM and parse the CSV body into (headers, rows)."""
    text = body.decode("utf-8")
    if text.startswith("﻿"):
        text = text[1:]
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    return rows[0], rows[1:]


#: An id no account in the fixture below has.
_NO_SUCH_USER = {"missing": 99998, "gone": 99999}


@pytest.fixture
async def platform_people(acting_user):
    """An operator who may export, and two ordinary accounts to export."""
    return {
        "admin": await acting_user("operator", email="admin@example.com"),
        "one": await acting_user("member", email="alpha@example.com"),
        "two": await acting_user("member", email="bravo@example.com"),
    }


def _export_id(people: dict, name: str) -> int:
    return _NO_SUCH_USER.get(name) or people[name].user.id


async def test_export_platform_users_csv_as_admin(client, platform_people):
    """Platform admins export every account as a BOM'd CSV attachment, with
    the addresses masked the way the roster it exports masks them."""
    admin = platform_people["admin"]

    response = await client.get("/api/v1/admin/users/export.csv", headers=admin.headers)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=" in response.headers["content-disposition"]
    assert "platform-users-" in response.headers["content-disposition"]
    assert response.content.startswith("﻿".encode("utf-8"))

    header_row, data_rows = _parse_csv(response.content)
    assert header_row == [
        "user_id",
        "email",
        "full_name",
        "platform_role",
        "status",
        "email_verified",
        "created_at",
        "updated_at",
        "timezone",
        "locale",
    ]
    assert {row[1] for row in data_rows} == {
        "a***n@e***m",
        "a***a@e***m",
        "b***o@e***m",
    }
    assert not any("@example.com" in row[1] for row in data_rows)


@pytest.mark.parametrize(
    ("ask", "expect"),
    [
        pytest.param(["one"], ["one"], id="one-id-is-that-account"),
        pytest.param(["one", "two"], ["one", "two"], id="two-ids-are-both-of-them"),
        pytest.param(["missing", "gone"], [], id="no-id-resolves-so-there-is-no-file"),
    ],
)
async def test_export_platform_users_csv_returns_the_accounts_asked_for(
    client, platform_people, ask, expect
):
    """``user_id`` narrows the export to the accounts it names, and a request
    that resolves to nobody is a 404. A single account files under its handle;
    any wider export files under the platform."""
    admin = platform_people["admin"]
    query = "&".join(f"user_id={_export_id(platform_people, name)}" for name in ask)

    response = await client.get(
        f"/api/v1/admin/users/export.csv?{query}", headers=admin.headers
    )

    if not expect:
        assert response.status_code == 404
        return

    assert response.status_code == 200
    _, data_rows = _parse_csv(response.content)
    assert {row[0] for row in data_rows} == {
        str(platform_people[name].user.id) for name in expect
    }

    disposition = response.headers["content-disposition"]
    if len(expect) == 1:
        only = platform_people[expect[0]].user
        # Named by handle, never by address: a filename outlives the download,
        # in a directory listing and in whatever it gets mailed to.
        assert f"user-{only.id}-{only.username}" in disposition
        assert "@" not in disposition
        assert data_rows[0][1] == "a***a@e***m"
    else:
        assert "platform-users-" in disposition


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        pytest.param("deactivate", 400, id="deactivating-is-refused"),
        pytest.param("soft_delete", 400, id="anonymizing-again-is-refused"),
        pytest.param("hard_delete", 200, id="removing-the-row-is-what-is-left"),
    ],
)
async def test_the_only_follow_up_to_anonymizing_is_a_hard_delete(
    client, session, acting_user, action, expected
):
    """An anonymized row holds nothing left to deactivate or to strip, so the
    one action still open on it is removing it."""
    admin = await acting_user("operator")
    target = await create_user(session)
    await users_service.soft_delete_user(session, target.id)

    response = await client.request(
        "DELETE",
        f"/api/v1/admin/users/{target.id}",
        headers=admin.headers,
        json={"action": action},
    )

    assert response.status_code == expected
    if expected == 400:
        assert response.json()["detail"] == "ADMIN_ALREADY_ANONYMIZED"


@pytest.mark.parametrize(
    ("how", "start_role", "requested"),
    [
        pytest.param("deactivate", UserRole.member, "operator", id="deactivated-up"),
        pytest.param("deactivate", UserRole.operator, "member", id="deactivated-down"),
        pytest.param("anonymize", UserRole.member, "operator", id="anonymized-up"),
        pytest.param("anonymize", UserRole.operator, "member", id="anonymized-down"),
    ],
)
async def test_platform_role_change_rejected_on_inactive_users(
    client, session, acting_user, how, start_role, requested
):
    """Platform role mutations on deactivated or anonymized users are refused
    with ``ADMIN_CANNOT_CHANGE_ROLE_INACTIVE``, in either direction. The role
    on the target row is unchanged."""
    admin = await acting_user("operator")
    target = await create_user(session, role=start_role)
    if how == "deactivate":
        await users_service.deactivate_user(session, target.id)
    else:
        await users_service.soft_delete_user(session, target.id)
        # Anonymizing demotes the row, so the role under test is put back
        # directly in the database — the endpoint would refuse to set it.
        row = (await session.exec(select(User).where(User.id == target.id))).one()
        row.role = start_role
        session.add(row)
        await session.commit()

    response = await client.patch(
        f"/api/v1/admin/users/{target.id}/platform-role",
        headers=admin.headers,
        json={"role": requested},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "ADMIN_CANNOT_CHANGE_ROLE_INACTIVE"
    refreshed = (await session.exec(select(User).where(User.id == target.id))).one()
    assert refreshed.role == start_role


async def test_demoting_an_active_admin_completes(client, session, acting_user):
    """Demoting an active admin runs the last-holder check and answers 200,
    with the target's role ending up demoted."""
    deleter = await acting_user("operator")
    target = await create_user(session, role=UserRole.operator)

    response = await client.patch(
        f"/api/v1/admin/users/{target.id}/platform-role",
        headers=deleter.headers,
        json={"role": "member"},
    )
    assert response.status_code == 200, response.text

    refreshed = (await session.exec(select(User).where(User.id == target.id))).one()
    assert refreshed.role == UserRole.member


@pytest.mark.parametrize(
    ("target_seat", "other_seat", "expected", "deleted"),
    [
        pytest.param(
            GuildRole.admin,
            GuildRole.admin,
            403,
            False,
            id="another-admin-is-no-blocker",
        ),
        pytest.param(
            GuildRole.superadmin, GuildRole.member, 204, True, id="the-sole-seat-is"
        ),
    ],
)
async def test_admin_delete_guild_is_scoped_to_a_genuine_blocker(
    client, session, acting_user, target_seat, other_seat, expected, deleted
):
    """Operator guild deletion resolves a user-deletion blocker: it succeeds
    only where the named user holds the guild's sole seat, and a guild that
    somebody else can still run is refused.

    The row survives either way now — deletion is retention, not removal — so
    what tells the two apart is the status it is left at."""
    operator = await acting_user("owner")
    target = await create_user(session)
    guild = await create_guild(session, creator=target)
    await create_guild_membership(session, user=target, guild=guild, role=target_seat)
    await create_guild_membership(
        session, user=await create_user(session), guild=guild, role=other_seat
    )

    response = await client.delete(
        f"/api/v1/admin/guilds/{guild.id}?blocked_user_id={target.id}",
        headers=operator.headers,
    )

    assert response.status_code == expected, response.text
    if expected == 403:
        assert response.json()["detail"] == AdminMessages.GUILD_NOT_A_DELETION_BLOCKER
    session.expunge_all()
    row = (await session.exec(select(Guild).where(Guild.id == guild.id))).one()
    assert (row.status == GuildStatus.deleted.value) is deleted
    # The roster is kept either way. This endpoint only fires where somebody
    # else is in the community, and those rows are theirs — what unblocks the
    # account is that a deleted community has no seat to protect.
    remaining = (
        await session.exec(
            select(GuildMembership).where(GuildMembership.guild_id == guild.id)
        )
    ).all()
    assert len(remaining) == 2


async def test_admin_delete_guild_requires_blocked_user_id(
    client, session, acting_user
):
    """The blocked_user_id query param is required — no bare 'delete any guild'."""
    operator = await acting_user("owner")
    guild = await create_guild(session, creator=operator.user)

    response = await client.delete(
        f"/api/v1/admin/guilds/{guild.id}", headers=operator.headers
    )

    assert response.status_code == 422


async def test_admin_initiative_role_update_takes_any_role_the_initiative_defines(
    client, acting_user
):
    """The role switch names a role of that initiative — custom ones included;
    a name the initiative doesn't define is a 404."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    role_response = await client.post(
        admin.g(f"/initiatives/{admin.initiative.id}/roles"),
        headers=admin.headers,
        json={"name": "leads", "display_name": "Leads", "is_manager": True},
    )
    assert role_response.status_code == 201, role_response.text

    operator = await acting_user("operator")
    url = (
        f"/api/v1/admin/initiatives/{admin.initiative.id}"
        f"/members/{member.user.id}/role?guild_id={admin.guild.id}"
    )

    resp = await client.patch(url, headers=operator.headers, json={"role": "leads"})
    assert resp.status_code == 204, resp.text

    roster = await client.get(
        admin.g(f"/initiatives/{admin.initiative.id}"), headers=admin.headers
    )
    assert roster.status_code == 200, roster.text
    row = next(m for m in roster.json()["members"] if m["user"]["id"] == member.user.id)
    assert row["role_name"] == "leads"
    assert row["is_manager"] is True

    resp = await client.patch(
        url, headers=operator.headers, json={"role": "no_such_role"}
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == InitiativeMessages.ROLE_NOT_FOUND


async def test_platform_roster_masks_addresses(client, acting_user):
    """The roster serves the masked address, not the stored one.

    Asserted on the payload rather than on what the SPA renders, because the
    payload is where the shortening happens.
    """
    owner = await acting_user("owner", email="owner@example.com")
    await acting_user("member", email="user1@example.com")

    response = await client.get("/api/v1/admin/users", headers=owner.headers)

    assert response.status_code == 200
    body = response.json()
    assert {u["email"] for u in body} == {"o***r@e***m", "u***1@e***m"}
    assert "@example.com" not in response.text


async def test_admin_mutations_return_masked_addresses(client, acting_user):
    """The single-account admin routes mask too, not just the list.

    Each returns the account it just changed, so each is its own read of an
    address and needs the same shape.
    """
    owner = await acting_user("owner", email="owner@example.com")
    target = await acting_user("member", email="target@example.com")

    role_change = await client.patch(
        f"/api/v1/admin/users/{target.user.id}/platform-role",
        headers=owner.headers,
        json={"role": "support"},
    )
    assert role_change.status_code == 200
    assert role_change.json()["email"] == "t***t@e***m"

    suspend = await client.post(
        f"/api/v1/admin/users/{target.user.id}/suspension",
        headers=owner.headers,
        json={"suspended": True},
    )
    assert suspend.status_code == 200
    assert suspend.json()["email"] == "t***t@e***m"


async def test_own_account_still_reads_its_whole_address(client, acting_user):
    """The one reader entitled to an address is the person it belongs to.

    ``/users/me`` backs the account screen, where the address is shown so you
    can check which account you are signed in as. Masking it there would be
    withholding it from its owner.
    """
    owner = await acting_user("owner", email="owner@example.com")

    response = await client.get("/api/v1/users/me", headers=owner.headers)

    assert response.status_code == 200
    assert response.json()["email"] == "owner@example.com"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        pytest.param("GET", "/api/v1/admin/users/export.csv", id="the-export"),
        pytest.param("GET", "/api/v1/admin/users", id="the-roster"),
    ],
)
async def test_the_admin_router_turns_away_an_ordinary_account(
    client, acting_user, method, path
):
    """The platform-admin routes are gated on a capability an ordinary account
    does not hold."""
    a = await acting_user("member")

    response = await client.request(method, path, headers=a.headers)

    assert response.status_code == 403
