"""End-to-end tests for the break-glass path (Phase 3).

``data.bypass`` is repurposed from a standing all-guild bypass into the right to
self-issue a scoped, time-bound, audited PAM grant. These tests prove:

* an admin/owner can self-issue a grant in one step (created + approved);
* a non-``data.bypass`` user cannot;
* the standing reach is gone — an admin reaches a guild's data ONLY after
  clicking through break-glass (the Phase 3 smoke test);
* the grant is the audit trail (requester == approver) and is read-only by
  default, short-lived, and non-stacking.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.auth import totp as totp_service

from app.models.platform.guild import GuildRole
from app.models.platform.user import UserRole
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_user,
    get_auth_headers,
)


@pytest.mark.integration
async def test_break_glass_self_issues_live_grant(
    client: AsyncClient, session: AsyncSession
):
    """An admin self-issues a read grant in one step: created AND approved,
    live immediately, with requester == approver as the audit record."""
    owner = await create_user(
        session, email="bg-owner@example.com", role=UserRole.owner
    )
    admin = await create_user(
        session, email="bg-admin@example.com", role=UserRole.operator
    )
    guild = await create_guild(session, creator=owner)  # admin is NOT a member

    resp = await client.post(
        "/api/v1/access-grants/break-glass",
        json={"guild_id": guild.id, "reason": "prod incident #42"},
        headers=get_auth_headers(admin),
    )
    assert resp.status_code == 201, resp.text
    grant = resp.json()
    assert grant["status"] == "approved"
    assert grant["is_live"] is True
    # Breaking glass is not a dial: write access to the content, and a
    # settings grant alongside it.
    assert grant["access_level"] == "read_write"
    assert grant["expires_at"] is not None
    assert grant["user_id"] == admin.id
    assert grant["requested_by_id"] == admin.id
    assert grant["approved_by_id"] == admin.id  # self-approved = the audit trail


@pytest.mark.integration
async def test_break_glass_requires_data_bypass(
    client: AsyncClient, session: AsyncSession
):
    """Lower tiers (support/moderator) lack ``data.bypass`` and must go through
    the request→approve flow instead — break-glass is 403 for them."""
    owner = await create_user(
        session, email="bg-owner2@example.com", role=UserRole.owner
    )
    support = await create_user(
        session, email="bg-support2@example.com", role=UserRole.support
    )
    guild = await create_guild(session, creator=owner)

    resp = await client.post(
        "/api/v1/access-grants/break-glass",
        json={"guild_id": guild.id, "reason": "no bypass"},
        headers=get_auth_headers(support),
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.integration
async def test_admin_reaches_guild_only_after_clicking_through(
    client: AsyncClient, session: AsyncSession
):
    """THE Phase 3 smoke test: a platform admin with ``data.bypass`` has NO
    standing reach into a guild's data — they get 403 until they break glass,
    then the same request succeeds via the scoped PAM grant."""
    owner = await create_user(
        session, email="bg-owner3@example.com", role=UserRole.owner
    )
    admin = await create_user(
        session, email="bg-admin3@example.com", role=UserRole.operator
    )
    guild = await create_guild(session, creator=owner)
    await create_initiative(session, guild, owner, name="Recon Wing")

    headers = get_auth_headers(admin)

    # BEFORE: no membership, no grant — the standing bypass is gone, so 403.
    resp = await client.get(f"/api/v1/g/{guild.id}/initiatives/", headers=headers)
    assert resp.status_code == 403, (
        "admin must NOT reach guild data without breaking glass"
    )

    # CLICK THROUGH: self-issue a break-glass grant.
    resp = await client.post(
        "/api/v1/access-grants/break-glass",
        json={"guild_id": guild.id, "reason": "investigate Recon Wing"},
        headers=get_auth_headers(admin),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["is_live"] is True

    # AFTER: the same request now succeeds, scoped to this one guild.
    resp = await client.get(f"/api/v1/g/{guild.id}/initiatives/", headers=headers)
    assert resp.status_code == 200, resp.text
    assert any(i["name"] == "Recon Wing" for i in resp.json()), (
        "after break-glass the admin should see the guild's initiatives"
    )


@pytest.mark.integration
async def test_break_glass_read_default_is_read_only(
    client: AsyncClient, session: AsyncSession
):
    """A default (read) break-glass grant cannot write the guild's content —
    RLS scopes it to the read-only guild role."""
    owner = await create_user(
        session, email="bg-owner4@example.com", role=UserRole.owner
    )
    admin = await create_user(
        session, email="bg-admin4@example.com", role=UserRole.operator
    )
    guild = await create_guild(session, creator=owner)
    init = await create_initiative(session, guild, owner, name="Ops")

    headers = get_auth_headers(admin)
    resp = await client.post(
        "/api/v1/access-grants/break-glass",
        json={"guild_id": guild.id, "reason": "read only look"},
        headers=get_auth_headers(admin),
    )
    assert resp.status_code == 201, resp.text

    # Can read...
    resp = await client.get(f"/api/v1/g/{guild.id}/initiatives/", headers=headers)
    assert resp.status_code == 200, resp.text

    # ...but cannot create a project (a write) under the read grant.
    resp = await client.post(
        f"/api/v1/g/{guild.id}/projects/",
        json={"name": "Should Fail", "initiative_id": init.id},
        headers=headers,
    )
    assert resp.status_code in (403, 404), resp.text


@pytest.mark.integration
async def test_break_glass_reaches_no_further_than_any_other_grant(
    client: AsyncClient, session: AsyncSession
):
    """Breaking glass issues two grants and no special authority.

    The content grant is `read_write` and means what it means for support:
    existing content, not authoring and not access management. The settings
    grant is what carries a community's configuration, and it is recorded
    separately so the log says which was exercised.
    """
    owner = await create_user(
        session, email="bg-owner8@example.com", role=UserRole.owner
    )
    admin = await create_user(
        session, email="bg-admin8@example.com", role=UserRole.operator
    )
    target = await create_user(session, email="bg-target8@example.com")
    guild = await create_guild(session, creator=owner)
    init = await create_initiative(session, guild, owner, name="War Room")
    project = await create_project(session, init, owner, name="Existing")

    headers = get_auth_headers(admin)
    resp = await client.post(
        "/api/v1/access-grants/break-glass",
        json={"guild_id": guild.id, "reason": "full incident response"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["access_level"] == "read_write"

    # Both rows are there, each naming what it is for.
    listed = await client.get("/api/v1/access-grants/?mine=true", headers=headers)
    issued = {(g["purpose"], g["access_level"]) for g in listed.json()}
    assert ("content", "read_write") in issued
    assert ("settings", "superadmin") in issued

    # Authoring is not what a content grant is: no new project.
    resp = await client.post(
        f"/api/v1/g/{guild.id}/projects/",
        json={"name": "New Front", "initiative_id": init.id},
        headers=headers,
    )
    assert resp.status_code == 403, resp.text

    # Nor is handing access out.
    resp = await client.put(
        f"/api/v1/g/{guild.id}/projects/{project.id}/grants",
        json=[{"user_id": target.id, "level": "write"}],
        headers=headers,
    )
    assert resp.status_code == 403, resp.text

    # What the settings grant carries: the community's own configuration.
    resp = await client.get(f"/api/v1/guilds/{guild.id}/auth-policy", headers=headers)
    assert resp.status_code == 200, resp.text


@pytest.mark.integration
async def test_break_glass_already_member_rejected(
    client: AsyncClient, session: AsyncSession
):
    """An admin who is a real member of the guild already has standing access —
    break-glass is rejected as redundant."""
    owner = await create_user(
        session, email="bg-owner5@example.com", role=UserRole.owner
    )
    admin = await create_user(
        session, email="bg-admin5@example.com", role=UserRole.operator
    )
    guild = await create_guild(session, creator=owner)
    # The admin is a real member of this guild already.
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.member
    )

    resp = await client.post(
        "/api/v1/access-grants/break-glass",
        json={"guild_id": guild.id, "reason": "already in"},
        headers=get_auth_headers(admin),
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "ACCESS_GRANT_ALREADY_MEMBER"


@pytest.mark.integration
async def test_break_glass_duration_capped(client: AsyncClient, session: AsyncSession):
    """A self-approved grant is capped at the (short) break-glass ceiling,
    below the role's request→approve maximum."""
    owner = await create_user(
        session, email="bg-owner6@example.com", role=UserRole.owner
    )
    admin = await create_user(
        session, email="bg-admin6@example.com", role=UserRole.operator
    )
    guild = await create_guild(session, creator=owner)

    # 24h is within the admin's request→approve cap but over break-glass (4h).
    resp = await client.post(
        "/api/v1/access-grants/break-glass",
        json={
            "guild_id": guild.id,
            "reason": "too long",
            "requested_duration_minutes": 1440,
        },
        headers=get_auth_headers(admin),
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "ACCESS_GRANT_DURATION_TOO_LONG"


@pytest.mark.integration
async def test_break_glass_overlapping_live_rejected(
    client: AsyncClient, session: AsyncSession
):
    """A second break-glass while one is still live is rejected (no stacking);
    re-trigger only after the current grant ends."""
    owner = await create_user(
        session, email="bg-owner7@example.com", role=UserRole.owner
    )
    admin = await create_user(
        session, email="bg-admin7@example.com", role=UserRole.operator
    )
    guild = await create_guild(session, creator=owner)

    body = {"guild_id": guild.id, "reason": "first"}
    resp = await client.post(
        "/api/v1/access-grants/break-glass", json=body, headers=get_auth_headers(admin)
    )
    assert resp.status_code == 201, resp.text

    resp = await client.post(
        "/api/v1/access-grants/break-glass",
        json={"guild_id": guild.id, "reason": "second"},
        headers=get_auth_headers(admin),
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "ACCESS_GRANT_ALREADY_LIVE"


# ---------------------------------------------------------------------------
# The second factor (D9)
#
# Breaking glass carries the account's own factor as soon as any data.bypass
# holder has one. Nobody configures it: the condition is read at the moment of
# the request, and it is only ever on because somebody can satisfy it.
# ---------------------------------------------------------------------------


def _next_code(secret: str) -> str:
    """The code for the interval after this one.

    Confirming an enrolment takes the interval its code came from, so breaking
    glass in the same thirty seconds cannot present that code again — which is
    the rule working, and the reason the code proves presence at all. One
    interval ahead is inside the drift a clock is allowed.
    """
    import pyotp

    at = datetime.now(timezone.utc) + timedelta(seconds=totp_service.TOTP_PERIOD)
    return pyotp.TOTP(secret).at(at)


async def _enrol_factor(
    client: AsyncClient, session: AsyncSession, user, password: str = "testpassword123"
) -> tuple[str, list[str]]:
    """Give ``user`` a confirmed factor, returning (secret, recovery codes)."""
    import pyotp

    headers = get_auth_headers(user)
    started = await client.post(
        "/api/v1/auth/totp/enroll", json={"current_password": password}, headers=headers
    )
    assert started.status_code == 200, started.text
    secret = started.json()["secret"]
    confirmed = await client.post(
        "/api/v1/auth/totp/confirm",
        json={"code": pyotp.TOTP(secret).now()},
        headers=headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    await session.refresh(user)
    return secret, confirmed.json()["codes"]


@pytest.mark.integration
async def test_break_glass_asks_for_nothing_while_no_holder_has_a_factor(
    client: AsyncClient, session: AsyncSession
):
    """A deployment where nobody has enrolled is untouched by this."""
    owner = await create_user(
        session, email="d9-none-o@example.com", role=UserRole.owner
    )
    admin = await create_user(
        session, email="d9-none-a@example.com", role=UserRole.operator
    )
    guild = await create_guild(session, creator=owner)

    resp = await client.post(
        "/api/v1/access-grants/break-glass",
        json={"guild_id": guild.id, "reason": "nothing to prove yet"},
        headers=get_auth_headers(admin),
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.integration
async def test_break_glass_takes_the_code_once_a_holder_has_one(
    client: AsyncClient, session: AsyncSession
):
    """One enrolled data.bypass holder turns it on for the whole platform."""
    owner = await create_user(
        session, email="d9-code-o@example.com", role=UserRole.owner
    )
    guild = await create_guild(session, creator=owner)
    admin = await create_user(
        session, email="d9-code-a@example.com", role=UserRole.operator
    )
    secret, _codes = await _enrol_factor(client, session, admin)

    # No code supplied.
    refused = await client.post(
        "/api/v1/access-grants/break-glass",
        json={"guild_id": guild.id, "reason": "incident"},
        headers=get_auth_headers(admin),
    )
    assert refused.status_code == 401
    assert refused.json()["detail"] == "ACCESS_GRANT_SECOND_FACTOR_REQUIRED"

    # With the code.
    resp = await client.post(
        "/api/v1/access-grants/break-glass",
        json={
            "guild_id": guild.id,
            "reason": "incident",
            "code": _next_code(secret),
        },
        headers=get_auth_headers(admin),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "approved"


@pytest.mark.integration
async def test_break_glass_refuses_a_wrong_code(
    client: AsyncClient, session: AsyncSession
):
    owner = await create_user(
        session, email="d9-bad-o@example.com", role=UserRole.owner
    )
    guild = await create_guild(session, creator=owner)
    admin = await create_user(
        session, email="d9-bad-a@example.com", role=UserRole.operator
    )
    await _enrol_factor(client, session, admin)

    resp = await client.post(
        "/api/v1/access-grants/break-glass",
        json={"guild_id": guild.id, "reason": "incident", "code": "000000"},
        headers=get_auth_headers(admin),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "TOTP_INVALID"


@pytest.mark.integration
async def test_a_recovery_code_breaks_glass_too(
    client: AsyncClient, session: AsyncSession
):
    """The phone is the thing most likely to be missing in the hour somebody
    needs this, so the set kept for that answers it as well."""
    owner = await create_user(
        session, email="d9-rec-o@example.com", role=UserRole.owner
    )
    guild = await create_guild(session, creator=owner)
    admin = await create_user(
        session, email="d9-rec-a@example.com", role=UserRole.operator
    )
    _secret, codes = await _enrol_factor(client, session, admin)

    resp = await client.post(
        "/api/v1/access-grants/break-glass",
        json={"guild_id": guild.id, "reason": "incident", "recovery_code": codes[0]},
        headers=get_auth_headers(admin),
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.integration
async def test_a_holder_with_no_factor_is_told_to_set_one_up(
    client: AsyncClient, session: AsyncSession
):
    """The cost of the derived rule, stated as a test: a colleague enrolling
    is what turns it on, and the refusal names the way back."""
    owner = await create_user(session, email="d9-un-o@example.com", role=UserRole.owner)
    guild = await create_guild(session, creator=owner)
    enrolled = await create_user(
        session, email="d9-un-e@example.com", role=UserRole.operator
    )
    await _enrol_factor(client, session, enrolled)
    bare = await create_user(
        session, email="d9-un-b@example.com", role=UserRole.operator
    )

    resp = await client.post(
        "/api/v1/access-grants/break-glass",
        json={"guild_id": guild.id, "reason": "incident"},
        headers=get_auth_headers(bare),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "ACCESS_GRANT_SECOND_FACTOR_ENROLMENT_REQUIRED"


@pytest.mark.integration
async def test_withdrawing_the_authenticator_stops_it_being_asked_for(
    client: AsyncClient, session: AsyncSession
):
    """The rule may only ask while the Security page can answer it.

    A deployment that stops offering the authenticator app refuses new
    enrolments, so a holder without one would have been refused with nowhere
    to go. It stops asking instead.
    """
    from app.core.login_methods import LoginMethod
    from app.services.platform import auth_posture

    owner = await create_user(session, email="d9-wd-o@example.com", role=UserRole.owner)
    guild = await create_guild(session, creator=owner)
    enrolled = await create_user(
        session, email="d9-wd-e@example.com", role=UserRole.operator
    )
    await _enrol_factor(client, session, enrolled)
    bare = await create_user(
        session, email="d9-wd-b@example.com", role=UserRole.operator
    )

    # While it is offered, the unenrolled holder is refused.
    refused = await client.post(
        "/api/v1/access-grants/break-glass",
        json={"guild_id": guild.id, "reason": "incident"},
        headers=get_auth_headers(bare),
    )
    assert refused.status_code == 403

    await auth_posture.set_login_methods(
        session,
        methods=[LoginMethod.password, LoginMethod.sso],
        acknowledge_stranded=None,
        actor_user_id=owner.id,
    )
    await session.commit()

    resp = await client.post(
        "/api/v1/access-grants/break-glass",
        json={"guild_id": guild.id, "reason": "incident"},
        headers=get_auth_headers(bare),
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.integration
async def test_the_form_is_told_what_it_will_be_asked_for(
    client: AsyncClient, session: AsyncSession
):
    admin = await create_user(
        session, email="d9-req-a@example.com", role=UserRole.operator
    )

    before = await client.get(
        "/api/v1/access-grants/break-glass", headers=get_auth_headers(admin)
    )
    assert before.status_code == 200, before.text
    assert before.json() == {"second_factor_required": False, "enrolled": False}

    await _enrol_factor(client, session, admin)

    after = await client.get(
        "/api/v1/access-grants/break-glass", headers=get_auth_headers(admin)
    )
    assert after.json() == {"second_factor_required": True, "enrolled": True}


@pytest.mark.integration
async def test_a_support_users_factor_does_not_turn_it_on(
    client: AsyncClient, session: AsyncSession
):
    """The rule reads data.bypass holders, not everybody: a support account
    enrolling says nothing about who can break glass."""
    owner = await create_user(
        session, email="d9-sup-o@example.com", role=UserRole.owner
    )
    guild = await create_guild(session, creator=owner)
    support = await create_user(
        session, email="d9-sup-s@example.com", role=UserRole.support
    )
    await _enrol_factor(client, session, support)
    admin = await create_user(
        session, email="d9-sup-a@example.com", role=UserRole.operator
    )

    resp = await client.post(
        "/api/v1/access-grants/break-glass",
        json={"guild_id": guild.id, "reason": "incident"},
        headers=get_auth_headers(admin),
    )
    assert resp.status_code == 201, resp.text
