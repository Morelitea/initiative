"""Phase 2 platform-role RLS ceilings (migration 0109).

These assert the *DB backstop* added in Phase 2: on the purely-platform tables
(``users``, ``access_grants``, ``app_settings``) a tier physically cannot exceed its
privilege, independent of the app-layer capability checks.

Two complementary styles:

* **Direct ``SET ROLE`` (DB-level).** The ``session`` fixture connects as the
  superuser, but ``SET ROLE platform_<tier>`` drops to a non-superuser role, so RLS
  and table GRANTs ARE enforced from that statement on — exactly like the production
  request path. This proves the policy/grant ceiling without the app layer in the
  way.
* **End-to-end (real-role ``client``).** An authenticated request assumes
  ``platform_<tier>`` on a real ``app_user`` connection, so the moved endpoints
  (admin user reads, owner config writes) run role-scoped, RLS-enforced.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.schema_provisioning import platform_role_name
from app.models.platform.user import UserRole
from app.testing import create_guild, create_user


async def _assume(session, tier: str, user_id: int) -> None:
    """Assume ``platform_<tier>`` with ``current_user_id`` set, on the session's
    connection — mirrors what ``set_rls_context`` does for a public-path request."""
    await session.exec(
        text(
            "SELECT set_config('app.current_user_id', :uid, false), "
            "set_config('role', :role, false)"
        ),
        params={"uid": str(user_id), "role": platform_role_name(tier)},
    )


async def _reset(session) -> None:
    await session.exec(
        text(
            "SELECT set_config('role', 'none', false), "
            "set_config('app.current_user_id', '', false)"
        )
    )


# --- users ----------------------------------------------------------------


async def test_member_sees_only_own_user_row(session):
    """The member-tier floor: ``platform_base`` own-row only. A member can read
    their own ``users`` row but not anyone else's."""
    u1 = await create_user(session)
    u2 = await create_user(session)
    await _assume(session, "member", u1.id)
    ids = {r[0] for r in (await session.exec(text("SELECT id FROM users"))).fetchall()}
    await _reset(session)
    assert u1.id in ids
    assert u2.id not in ids


async def test_support_reads_all_users(session):
    """``users.read`` — support+ can SELECT every user row (``users_platform_read``)."""
    u1 = await create_user(session)
    u2 = await create_user(session)
    await _assume(session, "support", u1.id)
    ids = {r[0] for r in (await session.exec(text("SELECT id FROM users"))).fetchall()}
    await _reset(session)
    assert {u1.id, u2.id} <= ids


async def test_support_cannot_update_others_but_moderator_can(session):
    """``users.manage`` is moderator+. Support has read-all but no update-all, so an
    UPDATE of another user touches 0 rows (RLS USING filters it out); moderator's
    ``users_platform_manage`` lets the same UPDATE land."""
    actor = await create_user(session)
    target = await create_user(session)

    await _assume(session, "support", actor.id)
    res = await session.exec(
        text("UPDATE users SET full_name = 'sx' WHERE id = :id"),
        params={"id": target.id},
    )
    await _reset(session)
    assert res.rowcount == 0

    await _assume(session, "moderator", actor.id)
    res = await session.exec(
        text("UPDATE users SET full_name = 'mx' WHERE id = :id"),
        params={"id": target.id},
    )
    await _reset(session)
    assert res.rowcount == 1


async def test_no_tier_can_delete_users(session):
    """``users_no_delete`` (RESTRICTIVE) keeps DELETE denied even for owner; user
    deletion stays on the admin engine."""
    actor = await create_user(session)
    target = await create_user(session)
    await _assume(session, "owner", actor.id)
    res = await session.exec(
        text("DELETE FROM users WHERE id = :id"), params={"id": target.id}
    )
    await _reset(session)
    assert res.rowcount == 0


# --- access_grants --------------------------------------------------------


async def _insert_grant(session, user_id: int, guild_id: int) -> None:
    await session.exec(
        text(
            "INSERT INTO access_grants "
            "(user_id, guild_id, reason, requested_duration_minutes, requested_by_id) "
            "VALUES (:u, :g, 'r', 60, :u)"
        ),
        params={"u": user_id, "g": guild_id},
    )


async def test_access_grants_self_vs_admin(session):
    """A grantee sees only their own grant (``access_grants_self``); an admin sees
    the whole queue (``access_grants_admin``). ``is_superadmin`` is retired here."""
    guild = await create_guild(session)
    u1 = await create_user(session)
    u2 = await create_user(session)
    await _insert_grant(session, u1.id, guild.id)
    await _insert_grant(session, u2.id, guild.id)

    await _assume(session, "member", u1.id)
    own = {
        r[0]
        for r in (
            await session.exec(text("SELECT user_id FROM access_grants"))
        ).fetchall()
    }
    await _reset(session)
    assert own == {u1.id}

    await _assume(session, "admin", u1.id)
    allrows = {
        r[0]
        for r in (
            await session.exec(text("SELECT user_id FROM access_grants"))
        ).fetchall()
    }
    await _reset(session)
    assert {u1.id, u2.id} <= allrows


# --- app_settings (owner-only config) -------------------------------------


async def test_app_settings_write_is_owner_only(session):
    """Config writes are owner-only at the GRANT layer: a member's UPDATE raises
    insufficient-privilege (42501), the owner's lands."""
    owner = await create_user(session, role=UserRole.owner)
    member = await create_user(session, role=UserRole.member)
    await session.exec(
        text(
            "INSERT INTO app_settings (id, oidc_enabled, oidc_scopes) "
            "VALUES (1, false, '[]'::json) ON CONFLICT (id) DO NOTHING"
        )
    )

    await _assume(session, "member", member.id)
    with pytest.raises(DBAPIError):
        async with session.begin_nested():
            await session.exec(
                text(
                    "UPDATE app_settings SET light_accent_color = '#000000' WHERE id = 1"
                )
            )
    await _reset(session)

    await _assume(session, "owner", owner.id)
    res = await session.exec(
        text("UPDATE app_settings SET light_accent_color = '#abcdef' WHERE id = 1")
    )
    await _reset(session)
    assert res.rowcount == 1


async def test_app_settings_readable_by_every_tier(session):
    """Everyone may SELECT config (``app_settings_read`` TO PUBLIC) — public reads
    like interface colors must work for any tier."""
    await session.exec(
        text(
            "INSERT INTO app_settings (id, oidc_enabled, oidc_scopes) "
            "VALUES (1, false, '[]'::json) ON CONFLICT (id) DO NOTHING"
        )
    )
    member = await create_user(session, role=UserRole.member)
    await _assume(session, "member", member.id)
    rows = (
        await session.exec(text("SELECT id FROM app_settings WHERE id = 1"))
    ).fetchall()
    await _reset(session)
    assert len(rows) == 1


async def test_app_settings_reseed_degrades_to_transient_for_non_owner(
    session, monkeypatch
):
    """A non-owner read that would env-reseed an existing config row can't write
    (owner-only). It must return an env-correct *transient* copy without faulting,
    and must NOT persist (the savepoint rollback expires the tracked instance — the
    re-seed path rebuilds from a pre-captured snapshot). The env value is persisted
    later by an owner / startup, not by a non-owner read."""
    from app.core.config import settings as app_config
    from app.services.platform import app_settings as svc

    # Existing singleton with an empty oidc_issuer.
    await session.exec(
        text(
            "INSERT INTO app_settings (id, oidc_enabled, oidc_scopes) "
            "VALUES (1, false, '[]'::json) ON CONFLICT (id) DO NOTHING"
        )
    )
    member = await create_user(session, role=UserRole.member)
    monkeypatch.setattr(app_config, "OIDC_ISSUER", "https://issuer.example")

    await _assume(session, "member", member.id)
    settings_obj = await svc.get_app_settings(session)
    # env-correct transient, no fault despite the owner-only write being denied
    assert settings_obj.oidc_issuer == "https://issuer.example"
    await _reset(session)

    # The non-owner read did NOT persist the env value into the row.
    db_issuer = (
        await session.exec(text("SELECT oidc_issuer FROM app_settings WHERE id = 1"))
    ).scalar_one()
    assert db_issuer is None


# --- end-to-end through the real-role request path ------------------------


async def test_support_can_list_users_role_scoped(client, acting_user):
    """The moved ``GET /admin/users`` runs as ``platform_support`` (off the BYPASSRLS
    engine) and the cross-user read is authorized by ``users_platform_read``."""
    a = await acting_user("support")
    resp = await client.get("/api/v1/admin/users", headers=a.headers)
    assert resp.status_code == 200
    assert any(u["id"] == a.user.id for u in resp.json())


async def test_member_cannot_list_users(client, acting_user):
    """The capability gate still holds above RLS: a member lacks ``users.read``."""
    a = await acting_user("member")
    resp = await client.get("/api/v1/admin/users", headers=a.headers)
    assert resp.status_code == 403


async def test_owner_can_update_interface_settings_role_scoped(client, acting_user):
    """The moved ``PUT /settings/interface`` runs as ``platform_owner`` and the
    owner-only GRANT + ``app_settings_owner`` policy let the write through."""
    a = await acting_user("owner")
    resp = await client.put(
        "/api/v1/settings/interface",
        headers=a.headers,
        json={"light_accent_color": "#123456", "dark_accent_color": "#654321"},
    )
    assert resp.status_code == 200
    assert resp.json()["light_accent_color"] == "#123456"


async def test_interface_settings_readable_without_write_privilege(client, acting_user):
    """A public config read works even for a non-owner when the singleton row is
    absent: the privilege-tolerant lazy-create degrades to a transient default
    instead of faulting on the owner-only write."""
    a = await acting_user("member")
    resp = await client.get("/api/v1/settings/interface", headers=a.headers)
    assert resp.status_code == 200
