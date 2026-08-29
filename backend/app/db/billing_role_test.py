"""Least-privilege probes for the ``initiative_billing`` Postgres role.

The billing write boundary's authorization lives in the database — a
column-scoped role pinned to one guild per request by the
``app.billing_guild_id`` GUC. These tests connect as the real ``app_user``
login role, assume the billing context exactly as the endpoints do
(``set_billing_context``), and assert the role is denied everything outside
its four verbs:

* columns beyond the lifecycle surface of ``guilds`` (name, description, …)
  and beyond the tier/cap surface of ``guild_administration``, where the caps
  and plan label now live (migration 0178) — ``guild_auth_enabled`` shares that
  table but is not billing's, so it must be denied;
* member identities (``guild_memberships.user_id``) — headcount only;
* any other shared table (``users`` is the canary);
* rows of any guild other than the pinned one (RLS, both read and write);
* mutating the append-only ``billing_event_log``.

This is the SOC 2 "isolation probe" the write-boundary plan calls for: the
grants are the boundary, so the suite fails if a migration ever widens them.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.session import set_billing_context
from app.testing import create_guild, create_guild_membership

pytestmark = [pytest.mark.integration, pytest.mark.database]


async def _denied(billing_session, sql: str) -> None:
    """The statement must die at the Postgres privilege/policy layer."""
    with pytest.raises(DBAPIError):
        await billing_session.exec(text(sql))
    # A privilege error aborts the transaction; recover for the next probe
    # (the stored billing context replays on the next autobegin).
    await billing_session.rollback()


@pytest.fixture
async def guilds(session):
    guild_a = await create_guild(session, name="Billing Probe A")
    guild_b = await create_guild(session, name="Billing Probe B")
    await create_guild_membership(session, guild=guild_a)
    return guild_a, guild_b


async def test_billing_role_is_confined_to_its_column_and_guild_surface(
    session, role_session, guilds
):
    guild_a, guild_b = guilds
    s = await role_session("app_user")
    await set_billing_context(s, guild_id=guild_a.id)

    # --- Positive controls: the four legitimate verbs work ------------------
    row = (
        await s.exec(
            text("SELECT id, status FROM guilds WHERE id = :gid"),
            params={"gid": guild_a.id},
        )
    ).one()
    assert row.id == guild_a.id

    caps = (
        await s.exec(
            text(
                "SELECT guild_id, tier_name, max_storage_bytes, max_users "
                "FROM guild_administration WHERE guild_id = :gid"
            ),
            params={"gid": guild_a.id},
        )
    ).one()
    assert caps.guild_id == guild_a.id

    updated = await s.exec(
        text(
            "UPDATE guild_administration SET tier_name = 'gold' WHERE guild_id = :gid"
        ),
        params={"gid": guild_a.id},
    )
    assert updated.rowcount == 1

    status_updated = await s.exec(
        text("UPDATE guilds SET status = 'active' WHERE id = :gid"),
        params={"gid": guild_a.id},
    )
    assert status_updated.rowcount == 1

    count = (
        await s.exec(
            text("SELECT count(guild_id) FROM guild_memberships WHERE guild_id = :gid"),
            params={"gid": guild_a.id},
        )
    ).scalar_one()
    assert count == 1

    await s.exec(
        text(
            "INSERT INTO billing_event_log (event_id, guild_id, op, source, applied_at) "
            "VALUES ('probe-evt-a', :gid, 'guild_tier', 'paddle_webhook', now())"
        ),
        params={"gid": guild_a.id},
    )
    await s.rollback()  # leave no probe state behind

    # --- Column confinement: nothing beyond the tier/cap surface ------------
    await set_billing_context(s, guild_id=guild_a.id)
    await _denied(s, f"SELECT name FROM guilds WHERE id = {guild_a.id}")
    await _denied(s, f"SELECT description FROM guilds WHERE id = {guild_a.id}")
    await _denied(s, f"SELECT created_by FROM guilds WHERE id = {guild_a.id}")
    await _denied(s, f"UPDATE guilds SET name = 'pwned' WHERE id = {guild_a.id}")
    # The administration row is billing's only where its own three columns are
    # concerned: the sign-in entitlement shares the table and stays out of reach,
    # as does creating or removing the row.
    await _denied(
        s,
        f"SELECT guild_auth_enabled FROM guild_administration WHERE guild_id = {guild_a.id}",
    )
    await _denied(
        s,
        "UPDATE guild_administration SET guild_auth_enabled = true "
        f"WHERE guild_id = {guild_a.id}",
    )
    await _denied(s, f"DELETE FROM guild_administration WHERE guild_id = {guild_a.id}")
    await _denied(s, "INSERT INTO guild_administration (guild_id) VALUES (999999)")
    await _denied(s, "SELECT user_id FROM guild_memberships")
    await _denied(s, "SELECT id FROM users")
    await _denied(s, "DELETE FROM guilds WHERE id = 999999")
    await _denied(s, "INSERT INTO guilds (name) VALUES ('forged')")
    # Beyond guilds/guild_memberships, the shared schema is a void: identity,
    # config, and the PAM trail are all out of reach.
    await _denied(s, "SELECT id FROM access_grants")
    await _denied(s, "SELECT id FROM app_settings")
    await _denied(s, "SELECT id FROM guild_invites")

    # --- Append-only evidence: INSERT is the only verb ----------------------
    await _denied(s, "SELECT event_id FROM billing_event_log")
    await _denied(s, "UPDATE billing_event_log SET actor = 'x'")
    await _denied(s, "DELETE FROM billing_event_log")
    await _denied(s, "SELECT jti FROM billing_jti_blocklist")
    await _denied(s, "DELETE FROM billing_jti_blocklist")

    # --- Guild pinning: the GUC's guild is the whole visible world ----------
    invisible = (
        await s.exec(
            text("SELECT id FROM guilds WHERE id = :gid"), params={"gid": guild_b.id}
        )
    ).one_or_none()
    assert invisible is None, "RLS must hide every guild but the pinned one"

    cross_caps = (
        await s.exec(
            text("SELECT guild_id FROM guild_administration WHERE guild_id = :gid"),
            params={"gid": guild_b.id},
        )
    ).one_or_none()
    assert cross_caps is None, "RLS must hide every guild's caps but the pinned one"

    cross_update = await s.exec(
        text(
            "UPDATE guild_administration SET tier_name = 'stolen' WHERE guild_id = :gid"
        ),
        params={"gid": guild_b.id},
    )
    assert cross_update.rowcount == 0

    cross_count = (
        await s.exec(
            text("SELECT count(guild_id) FROM guild_memberships WHERE guild_id = :gid"),
            params={"gid": guild_b.id},
        )
    ).scalar_one()
    assert cross_count == 0

    # Audit rows can only claim the pinned guild (RLS WITH CHECK).
    await _denied(
        s,
        "INSERT INTO billing_event_log (event_id, guild_id, op, source, applied_at) "
        f"VALUES ('probe-evt-b', {guild_b.id}, 'guild_tier', 'paddle_webhook', now())",
    )
    await s.rollback()


async def test_unpinned_billing_guc_sees_nothing(session, role_session, guilds):
    """Fail-closed: with the billing role assumed but NO guild pinned (an
    impossible state for the endpoints, which derive the GUC from the
    verified body), every statement touches zero rows."""
    guild_a, _ = guilds
    s = await role_session("app_user")
    await set_billing_context(s, guild_id=guild_a.id)
    # Clear the pin within the transaction, keeping the role.
    await s.exec(text("SELECT set_config('app.billing_guild_id', '', true)"))
    visible = (await s.exec(text("SELECT id FROM guilds"))).all()
    assert visible == []
    visible_caps = (
        await s.exec(text("SELECT guild_id FROM guild_administration"))
    ).all()
    assert visible_caps == []

    unpinned_update = await s.exec(
        text(
            "UPDATE guild_administration SET tier_name = 'nowhere' WHERE guild_id = :gid"
        ),
        params={"gid": guild_a.id},
    )
    assert unpinned_update.rowcount == 0

    unpinned_count = (
        await s.exec(text("SELECT count(guild_id) FROM guild_memberships"))
    ).scalar_one()
    assert unpinned_count == 0
    await s.rollback()


async def test_billing_role_attributes_are_least_privilege(session):
    """The auditor-facing role facts: NOLOGIN, no superuser/BYPASSRLS/
    CREATEROLE, and the login role's membership is INHERIT FALSE — the
    boundary is reachable only via an explicit SET ROLE, never ambiently."""
    from app.db.schema_provisioning import billing_role_name

    role = billing_role_name()
    attrs = (
        await session.exec(
            text(
                "SELECT rolcanlogin, rolsuper, rolbypassrls, rolcreaterole "
                "FROM pg_roles WHERE rolname = :r"
            ),
            params={"r": role},
        )
    ).one()
    assert attrs.rolcanlogin is False
    assert attrs.rolsuper is False
    assert attrs.rolbypassrls is False
    assert attrs.rolcreaterole is False

    membership = (
        await session.exec(
            text(
                "SELECT m.inherit_option, m.admin_option "
                "FROM pg_auth_members m "
                "JOIN pg_roles granted ON granted.oid = m.roleid "
                "JOIN pg_roles member ON member.oid = m.member "
                "WHERE granted.rolname = :r AND member.rolname = 'app_user'"
            ),
            params={"r": role},
        )
    ).one()
    assert membership.inherit_option is False, (
        "app_user must hold the billing role WITH INHERIT FALSE — "
        "SET ROLE only, no standing access"
    )
    assert membership.admin_option is False
