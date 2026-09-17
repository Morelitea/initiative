"""Guild auth policy: admin endpoints, the step-up gate, and the DB-layer
session-satisfaction enforcement inside the guild RLS."""

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    GuildAccessError,
    _enforce_guild_auth_policy,
    establish_guild_access,
)
from app.core.auth_context import satisfied_provider_ids
from app.db.session import SYSTEM_SATISFIED, set_rls_context
from app.models.platform.guild import GuildRole
from app.models.platform.guild_auth_policy import GuildAuthPolicy
from app.models.tenant.project import Project
from app.services.platform import api_keys as api_keys_service
from app.services.platform import user_tokens
from app.services.platform.ws_auth import authenticate_ws_token
from app.testing.factories import (
    guild_administration,
    create_auth_provider,
    create_document,
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_user,
    get_auth_headers,
    get_auth_token,
)

pytestmark = [pytest.mark.integration, pytest.mark.auth]


def _sat_headers(user, provider_ids: list[int]) -> dict[str, str]:
    token = get_auth_token(user, satisfied_providers=provider_ids)
    return {"Authorization": f"Bearer {token}"}


async def _require_provider(
    session: AsyncSession, guild_id: int, provider
) -> GuildAuthPolicy:
    row = GuildAuthPolicy(
        guild_id=guild_id,
        policy="required",
        provider_id=provider.id,
        provider_slug=provider.slug,
    )
    session.add(row)
    await session.commit()
    return row


async def test_the_seat_sets_reads_and_clears_the_policy(
    client: AsyncClient, session: AsyncSession
):
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.security_admin
    )
    provider = await create_auth_provider(session, slug="corp", guild_id=guild.id)
    headers = _sat_headers(admin, [provider.id])

    put = await client.put(
        f"/api/v1/guilds/{guild.id}/auth-policy",
        headers=headers,
        json={"policy": "required", "provider_id": provider.id},
    )
    assert put.status_code == 200, put.text
    assert put.json() == {
        "policy": "required",
        "provider_id": provider.id,
        "provider_slug": "corp",
        "provider_display_name": "Corp SSO",
        "require_methods": [],
    }

    got = await client.get(f"/api/v1/guilds/{guild.id}/auth-policy", headers=headers)
    assert got.json()["policy"] == "required"

    guild_id = guild.id
    cleared = await client.put(
        f"/api/v1/guilds/{guild_id}/auth-policy",
        headers=headers,
        json={"policy": "open"},
    )
    assert cleared.json()["policy"] == "open"
    session.expire_all()
    assert await session.get(GuildAuthPolicy, guild_id) is None


async def test_non_admin_cannot_manage_policy(
    client: AsyncClient, session: AsyncSession
):
    member = await create_user(session)
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )
    provider = await create_auth_provider(session, slug="corp")

    response = await client.put(
        f"/api/v1/guilds/{guild.id}/auth-policy",
        headers=_sat_headers(member, [provider.id]),
        json={"policy": "required", "provider_id": provider.id},
    )
    assert response.status_code == 403


async def test_policy_rejects_unusable_provider(
    client: AsyncClient, session: AsyncSession
):
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.security_admin
    )
    disabled = await create_auth_provider(
        session, slug="off", enabled=False, guild_id=guild.id
    )
    headers = _sat_headers(admin, [disabled.id])

    response = await client.put(
        f"/api/v1/guilds/{guild.id}/auth-policy",
        headers=headers,
        json={"policy": "required", "provider_id": disabled.id},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "GUILD_AUTH_POLICY_INVALID_PROVIDER"

    missing = await client.put(
        f"/api/v1/guilds/{guild.id}/auth-policy",
        headers=headers,
        json={"policy": "required"},
    )
    assert missing.status_code == 400


async def test_policy_rejects_other_namespace_providers(
    client: AsyncClient, session: AsyncSession
):
    """A requirement can only name one of the guild's own providers — never an
    operator-global row (dormant under per-guild auth) or another guild's."""
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.security_admin
    )
    other_guild = await create_guild(session)
    global_row = await create_auth_provider(session, slug="corp")
    foreign_row = await create_auth_provider(
        session, slug="corp", guild_id=other_guild.id
    )

    for provider in (global_row, foreign_row):
        response = await client.put(
            f"/api/v1/guilds/{guild.id}/auth-policy",
            headers=_sat_headers(admin, [provider.id]),
            json={"policy": "required", "provider_id": provider.id},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "GUILD_AUTH_POLICY_INVALID_PROVIDER"


async def test_policy_requires_admin_own_session_to_satisfy(
    client: AsyncClient, session: AsyncSession
):
    """An admin can only require a provider their own session has satisfied —
    proving it works and keeping them from locking out their guild."""
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.security_admin
    )
    provider = await create_auth_provider(session, slug="corp", guild_id=guild.id)

    response = await client.put(
        f"/api/v1/guilds/{guild.id}/auth-policy",
        headers=get_auth_headers(admin),  # legacy token: sat is empty
        json={"policy": "required", "provider_id": provider.id},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "GUILD_AUTH_POLICY_SELF_UNSATISFIED"


async def test_a_requirement_can_be_cleared_without_the_entitlement(
    client: AsyncClient, session: AsyncSession
):
    """A requirement can be read and lifted by a guild admin whatever the
    guild's entitlement says.

    Enforcement reads the policy row alone, so a requirement outlives the
    entitlement that allowed it to be set; the way to lift one outlives it too.
    Lifting only ever admits more, so it carries none of the gating the setting
    path does."""
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.security_admin
    )
    provider = await create_auth_provider(session, slug="corp", guild_id=guild.id)
    await _require_provider(session, guild.id, provider)
    headers = _sat_headers(admin, [provider.id])
    guild_id = guild.id

    # Platform posture: the requirement is still there, and still visible.
    got = await client.get(f"/api/v1/guilds/{guild_id}/auth-policy", headers=headers)
    assert got.status_code == 200
    assert got.json()["policy"] == "required"
    assert got.json()["provider_slug"] == "corp"

    cleared = await client.put(
        f"/api/v1/guilds/{guild_id}/auth-policy",
        headers=headers,
        json={"policy": "open"},
    )
    assert cleared.status_code == 200
    assert cleared.json()["policy"] == "open"
    session.expire_all()
    assert await session.get(GuildAuthPolicy, guild_id) is None


async def test_policy_surface_404_when_guild_auth_disabled(
    client: AsyncClient, session: AsyncSession
):
    """With the operator toggle off, a guild cannot acquire a requirement: the
    PUT that would set one 404s with the same GUILD_AUTH_NOT_ENABLED shape as
    platform posture, and nothing is written. Reading stays open, as it does
    under platform posture."""
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin, auth_options=[])
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.security_admin
    )
    provider = await create_auth_provider(session, slug="corp", guild_id=guild.id)
    headers = _sat_headers(admin, [provider.id])
    guild_id = guild.id

    got = await client.get(f"/api/v1/guilds/{guild_id}/auth-policy", headers=headers)
    assert got.status_code == 200
    assert got.json()["policy"] == "open"

    put = await client.put(
        f"/api/v1/guilds/{guild_id}/auth-policy",
        headers=headers,
        json={"policy": "required", "provider_id": provider.id},
    )
    assert put.status_code == 404
    assert put.json()["detail"] == "GUILD_AUTH_NOT_ENABLED"
    session.expire_all()
    assert await session.get(GuildAuthPolicy, guild_id) is None


async def test_disabling_guild_auth_keeps_existing_requirement_enforced(
    client: AsyncClient, session: AsyncSession
):
    """Turning the operator toggle OFF closes the config surface but never
    un-enforces an already-set requirement — unsatisfied sessions still step up
    (parity with the posture gate: management is gated, enforcement is not)."""
    member = await create_user(session)
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )
    provider = await create_auth_provider(session, slug="corp")
    await _require_provider(session, guild.id, provider)

    # Operator turns per-guild sign-in off after the requirement was set.
    await guild_administration(session, guild, auth_options=[])

    blocked = await client.get(
        f"/api/v1/g/{guild.id}/initiatives/", headers=get_auth_headers(member)
    )
    assert blocked.status_code == 401
    assert blocked.json()["detail"] == "GUILD_AUTH_STEP_UP_REQUIRED"
    assert blocked.headers["X-Auth-Step-Up"] == "corp"

    allowed = await client.get(
        f"/api/v1/g/{guild.id}/initiatives/",
        headers=_sat_headers(member, [provider.id]),
    )
    assert allowed.status_code == 200


async def test_required_guild_steps_up_unsatisfied_sessions(
    client: AsyncClient, session: AsyncSession
):
    member = await create_user(session)
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )
    provider = await create_auth_provider(session, slug="corp")
    await _require_provider(session, guild.id, provider)

    # Unsatisfied (legacy) session: 401 naming the provider to step up with.
    blocked = await client.get(
        f"/api/v1/g/{guild.id}/initiatives/", headers=get_auth_headers(member)
    )
    assert blocked.status_code == 401
    assert blocked.json()["detail"] == "GUILD_AUTH_STEP_UP_REQUIRED"
    assert blocked.headers["X-Auth-Step-Up"] == "corp"
    # And the same answer in the standard form (RFC 9470 §3), for a client
    # that knows OAuth and nothing about this app.
    assert (
        blocked.headers["WWW-Authenticate"]
        == 'Bearer error="insufficient_user_authentication"'
    )

    # A session that satisfied the provider passes.
    allowed = await client.get(
        f"/api/v1/g/{guild.id}/initiatives/",
        headers=_sat_headers(member, [provider.id]),
    )
    assert allowed.status_code == 200


async def test_the_step_up_challenge_is_not_what_an_ordinary_401_says(
    client: AsyncClient, session: AsyncSession
):
    """Both answers are 401 and both name Bearer, and a client has to tell them
    apart: one is renewed by refreshing, the other by presenting a factor. The
    ``error`` parameter is the difference, so an ordinary 401 must not carry
    it."""
    guild = await create_guild(session)

    no_credential = await client.get(f"/api/v1/g/{guild.id}/initiatives/")

    assert no_credential.status_code == 401
    assert no_credential.headers["WWW-Authenticate"] == "Bearer"
    assert "error=" not in no_credential.headers["WWW-Authenticate"]


async def test_open_guild_admits_any_session(
    client: AsyncClient, session: AsyncSession
):
    member = await create_user(session)
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )

    response = await client.get(
        f"/api/v1/g/{guild.id}/initiatives/", headers=get_auth_headers(member)
    )
    assert response.status_code == 200


async def _blocked_by_the_requirement(response) -> None:
    """The answer a session that has not satisfied the requirement gets."""
    assert response.status_code == 401, response.text
    assert response.json()["detail"] == "GUILD_AUTH_STEP_UP_REQUIRED"
    assert response.headers["X-Auth-Step-Up"] == "corp"


async def _member_of_a_guild_requiring_corp(session: AsyncSession):
    member = await create_user(session)
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )
    provider = await create_auth_provider(session, slug="corp")
    await _require_provider(session, guild.id, provider)
    return member, guild


async def test_an_exchanged_device_token_session_does_not_satisfy_a_requirement(
    client: AsyncClient, session: AsyncSession
):
    """A device token records nothing about how its owner first signed in, so
    the session it buys carries no providers, and a guild requiring one answers
    it the way it answers any session that has not satisfied the requirement.

    Pinned because the requirement is about to gain a second thing it can ask
    for, and this answer must stay the same one."""
    member, guild = await _member_of_a_guild_requiring_corp(session)
    device_token = await user_tokens.create_device_token(
        session, user_id=member.id, device_name="old-phone"
    )
    await session.commit()

    exchanged = await client.post(
        "/api/v1/auth/device-token/exchange", json={"device_token": device_token}
    )
    assert exchanged.status_code == 200, exchanged.text

    await _blocked_by_the_requirement(
        await client.get(
            f"/api/v1/g/{guild.id}/initiatives/",
            headers={"Authorization": f"Bearer {exchanged.json()['access_token']}"},
        )
    )


async def test_a_device_token_presented_directly_does_not_satisfy_a_requirement(
    client: AsyncClient, session: AsyncSession
):
    """The same credential used as one, rather than traded for a session."""
    member, guild = await _member_of_a_guild_requiring_corp(session)
    device_token = await user_tokens.create_device_token(
        session, user_id=member.id, device_name="old-phone"
    )
    await session.commit()

    await _blocked_by_the_requirement(
        await client.get(
            f"/api/v1/g/{guild.id}/initiatives/",
            headers={"Authorization": f"DeviceToken {device_token}"},
        )
    )


async def test_an_api_key_does_not_satisfy_a_requirement(
    client: AsyncClient, session: AsyncSession
):
    """An API key is derived from a sign-in that already happened and carries
    nothing about it, so it reaches a guild that requires one no further than
    a device token does."""
    member, guild = await _member_of_a_guild_requiring_corp(session)
    secret, _row = await api_keys_service.create_api_key(
        session, user=member, name="ci"
    )
    await session.commit()

    await _blocked_by_the_requirement(
        await client.get(
            f"/api/v1/g/{guild.id}/initiatives/",
            headers={"Authorization": f"Bearer {secret}"},
        )
    )


async def _guild_with_a_seat_and_a_requirement(session: AsyncSession):
    """One security admin, one member, and a standing requirement."""
    from app.models.platform.user import UserRole

    founder = await create_user(session)
    guild = await create_guild(session, creator=founder)
    await create_guild_membership(
        session, user=founder, guild=guild, role=GuildRole.admin
    )
    keyholder = await create_user(session)
    await create_guild_membership(
        session, user=keyholder, guild=guild, role=GuildRole.security_admin
    )
    provider = await create_auth_provider(session, slug="corp", guild_id=guild.id)
    await _require_provider(session, guild.id, provider)
    operator = await create_user(session, role=UserRole.operator)
    return keyholder, guild, operator


async def test_an_ordinary_admin_reads_the_policy_but_does_not_write_it(
    client: AsyncClient, session: AsyncSession
):
    """The split in one test: an admin who cannot see what is set cannot ask
    for it to be changed, so reading is theirs; deciding who may enter is not."""
    keyholder, guild, _operator = await _guild_with_a_seat_and_a_requirement(session)
    admin = await create_user(session)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    headers = get_auth_headers(admin)

    read = await client.get(f"/api/v1/guilds/{guild.id}/auth-policy", headers=headers)
    assert read.status_code == 200
    assert read.json()["policy"] == "required"

    for body in ({"policy": "open"}, {"policy": "required", "provider_id": 1}):
        refused = await client.put(
            f"/api/v1/guilds/{guild.id}/auth-policy", headers=headers, json=body
        )
        assert refused.status_code == 403, refused.text
        assert refused.json()["detail"] == "GUILD_SECURITY_ADMIN_REQUIRED"

    # And the row is untouched.
    guild_id = guild.id
    session.expire_all()
    still_required = await session.get(GuildAuthPolicy, guild_id)
    assert still_required is not None and still_required.policy == "required"


async def test_an_ordinary_admin_lists_providers_but_does_not_change_them(
    client: AsyncClient, session: AsyncSession
):
    keyholder, guild, _operator = await _guild_with_a_seat_and_a_requirement(session)
    admin = await create_user(session)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    headers = get_auth_headers(admin)
    base = f"/api/v1/guilds/{guild.id}/auth/providers"

    listed = await client.get(base, headers=headers)
    assert listed.status_code == 200
    assert [row["slug"] for row in listed.json()] == ["corp"]

    created = await client.post(
        base,
        headers=headers,
        json={
            "slug": "other",
            "display_name": "Other",
            "issuer": "https://idp.example.com",
            "client_id": "c",
        },
    )
    assert created.status_code == 403
    assert created.json()["detail"] == "GUILD_SECURITY_ADMIN_REQUIRED"


async def test_the_last_seat_cannot_be_demoted_while_a_requirement_stands(
    client: AsyncClient, session: AsyncSession
):
    """The requirement is lifted from the surface the seat holds, so the last
    holder stays for as long as the requirement does. The operator's role
    endpoint is the one that could otherwise reach them."""
    keyholder, guild, operator = await _guild_with_a_seat_and_a_requirement(session)

    refused = await client.patch(
        f"/api/v1/admin/guilds/{guild.id}/members/{keyholder.id}/role",
        headers=get_auth_headers(operator),
        json={"role": "member"},
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == "CANNOT_VACATE_LAST_SECURITY_ADMIN"


async def test_the_last_seat_cannot_leave_while_a_requirement_stands(
    client: AsyncClient, session: AsyncSession
):
    keyholder, guild, _operator = await _guild_with_a_seat_and_a_requirement(session)

    refused = await client.delete(
        f"/api/v1/guilds/{guild.id}/leave", headers=get_auth_headers(keyholder)
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == "CANNOT_VACATE_LAST_SECURITY_ADMIN"


async def test_the_seat_empties_freely_once_the_requirement_is_lifted(
    client: AsyncClient, session: AsyncSession
):
    """The condition is narrow on purpose: a guild that requires nothing is a
    guild whose seat is like any other role."""
    keyholder, guild, operator = await _guild_with_a_seat_and_a_requirement(session)
    policy_row = await session.get(GuildAuthPolicy, guild.id)
    await session.delete(policy_row)
    await session.commit()

    allowed = await client.patch(
        f"/api/v1/admin/guilds/{guild.id}/members/{keyholder.id}/role",
        headers=get_auth_headers(operator),
        json={"role": "member"},
    )
    assert allowed.status_code == 204, allowed.text


async def test_provider_delete_refused_while_required(
    client: AsyncClient, session: AsyncSession
):
    from app.models.platform.user import UserRole

    owner = await create_user(session, role=UserRole.owner)
    guild = await create_guild(session)
    provider = await create_auth_provider(session, slug="corp")
    await _require_provider(session, guild.id, provider)

    response = await client.delete(
        f"/api/v1/settings/auth/providers/{provider.id}",
        headers=get_auth_headers(owner),
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "AUTH_PROVIDER_IN_USE"


async def test_me_aggregate_includes_policy_guild_only_when_satisfied(
    client: AsyncClient, session: AsyncSession
):
    """Cross-guild /me/* views carry the session's real ``sat``: a policy-gated
    guild's content appears exactly when the session satisfies its provider —
    and its RLS keeps an unsatisfied session's aggregate empty for that guild
    without failing the whole request."""
    user = await create_user(session)
    open_guild = await create_guild(session, creator=user)
    gated_guild = await create_guild(session, creator=user)
    for g in (open_guild, gated_guild):
        await create_guild_membership(session, user=user, guild=g)
    provider = await create_auth_provider(session, slug="corp")

    open_initiative = await create_initiative(session, open_guild, user)
    gated_initiative = await create_initiative(session, gated_guild, user)
    await create_document(session, open_initiative, user, name="open doc")
    await create_document(session, gated_initiative, user, name="gated doc")
    await _require_provider(session, gated_guild.id, provider)
    provider_id = provider.id

    # Legacy/unsatisfied session: only the open guild's document.
    unsatisfied = await client.get(
        "/api/v1/me/documents", headers=get_auth_headers(user)
    )
    assert unsatisfied.status_code == 200, unsatisfied.text
    assert [d["name"] for d in unsatisfied.json()["items"]] == ["open doc"]

    # A session that satisfied the provider sees both guilds' documents.
    satisfied = await client.get(
        "/api/v1/me/documents", headers=_sat_headers(user, [provider_id])
    )
    names = {d["name"] for d in satisfied.json()["items"]}
    assert names == {"open doc", "gated doc"}


async def test_ws_token_sat_gates_policy_guild(session: AsyncSession):
    """The WebSocket join path: ``authenticate_ws_token`` records the token's
    ``sat``, and the ``establish_guild_access`` that follows applies the guild
    auth-policy gate to the socket exactly as REST would."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    provider = await create_auth_provider(session, slug="corp")
    await _require_provider(session, guild.id, provider)
    guild_id, provider_id = guild.id, provider.id

    # A session that satisfied nothing: authenticates, gate refuses.
    plain_user = await authenticate_ws_token(get_auth_token(user), session)
    assert plain_user is not None
    assert satisfied_provider_ids() == frozenset()
    with pytest.raises(GuildAccessError):
        await establish_guild_access(session, plain_user, guild_id)

    # A satisfied session token joins.
    sat_user = await authenticate_ws_token(
        get_auth_token(user, satisfied_providers=[provider_id]), session
    )
    assert sat_user is not None
    assert satisfied_provider_ids() == frozenset({provider_id})
    ctx = await establish_guild_access(session, sat_user, guild_id)
    assert ctx.guild_id == guild_id


async def test_system_sentinel_passes_policy_gate(session: AsyncSession):
    """User-attributed system work (export/import workers) passes the gate via
    the explicit sentinel — its enqueueing request already satisfied it."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    provider = await create_auth_provider(session, slug="corp")
    await _require_provider(session, guild.id, provider)
    guild_id = guild.id

    ctx = await establish_guild_access(
        session, user, guild_id, satisfied_providers=SYSTEM_SATISFIED
    )
    assert ctx.guild_id == guild_id


async def test_required_row_needs_provider_and_slug(session: AsyncSession):
    """The check constraint: a required policy must carry both the provider id
    and its denormalized slug — the step-up response depends on the slug."""
    guild = await create_guild(session)
    provider = await create_auth_provider(session, slug="corp")
    session.add(
        GuildAuthPolicy(
            guild_id=guild.id,
            policy="required",
            provider_id=provider.id,
            provider_slug=None,
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_db_layer_blocks_unsatisfied_session(session: AsyncSession, role_session):
    """The RLS gate itself: with a required policy, a routed user session that
    hasn't satisfied the provider sees ZERO content rows — regardless of any
    app-layer gate. Satisfied sessions, the user-attributed system sentinel,
    and pure system routings (no user) all see the rows."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    provider = await create_auth_provider(session, slug="corp")
    initiative = await create_initiative(session, guild, user)
    await create_project(session, initiative, user)
    await _require_provider(session, guild.id, provider)
    user_id, guild_id, provider_id = user.id, guild.id, provider.id

    app_session = await role_session("app_user")

    async def _visible_projects() -> int:
        return len((await app_session.exec(select(Project))).all())

    # Unsatisfied member/admin session: nothing.
    await set_rls_context(
        app_session, user_id=user_id, guild_id=guild_id, guild_role="admin"
    )
    assert await _visible_projects() == 0

    # Satisfied session: content visible.
    await set_rls_context(
        app_session,
        user_id=user_id,
        guild_id=guild_id,
        guild_role="admin",
        satisfied_providers=[provider_id],
    )
    assert await _visible_projects() == 1

    # User-attributed system work carries the sentinel.
    await set_rls_context(
        app_session,
        user_id=user_id,
        guild_id=guild_id,
        guild_role="admin",
        satisfied_providers=SYSTEM_SATISFIED,
    )
    assert await _visible_projects() == 1

    # Pure system routing (no user context) is not a session to gate.
    await set_rls_context(app_session, guild_id=guild_id, guild_role="admin")
    assert await _visible_projects() == 1


# --- "Any of ours": a requirement that names no single provider -------------


def _sso_headers(user, guild_ids: list[int], provider_ids: list[int] | None = None):
    """A session that completed those communities' own sign-in."""
    token = get_auth_token(
        user,
        amr=[f"guild:{gid}" for gid in guild_ids] + ["oidc:whatever"],
        satisfied_providers=provider_ids or [],
    )
    return {"Authorization": f"Bearer {token}"}


async def _guild_requiring_its_own_sso(session: AsyncSession):
    member = await create_user(session)
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )
    provider = await create_auth_provider(session, slug="corp", guild_id=guild.id)
    row = GuildAuthPolicy(guild_id=guild.id, policy="required", require_methods=["sso"])
    session.add(row)
    await session.commit()
    return member, guild, provider


async def test_any_of_this_communitys_providers_satisfies_the_rule(
    client: AsyncClient, session: AsyncSession
):
    """The rule a community with two providers could not write before: come in
    through one of ours, and we do not mind which."""
    member, guild, _provider = await _guild_requiring_its_own_sso(session)

    allowed = await client.get(
        f"/api/v1/g/{guild.id}/initiatives/",
        headers=_sso_headers(member, [guild.id]),
    )
    assert allowed.status_code == 200, allowed.text


async def test_another_communitys_sign_in_does_not_satisfy_it(
    client: AsyncClient, session: AsyncSession
):
    """Single sign-on somewhere else — the deployment's own providers included
    — is not this community's single sign-on."""
    member, guild, _provider = await _guild_requiring_its_own_sso(session)
    elsewhere = await create_guild(session)

    blocked = await client.get(
        f"/api/v1/g/{guild.id}/initiatives/",
        headers=_sso_headers(member, [elsewhere.id]),
    )
    assert blocked.status_code == 401
    assert blocked.json()["detail"] == "GUILD_AUTH_STEP_UP_REQUIRED"


async def test_a_password_session_is_stepped_up_to_the_communitys_login_page(
    client: AsyncClient, session: AsyncSession
):
    """The challenge names the community rather than a provider: a rule that
    named none is served by the community's own login page."""
    member, guild, _provider = await _guild_requiring_its_own_sso(session)

    blocked = await client.get(
        f"/api/v1/g/{guild.id}/initiatives/",
        headers={"Authorization": f"Bearer {get_auth_token(member, amr=['pwd'])}"},
    )
    assert blocked.status_code == 401
    assert blocked.json()["detail"] == "GUILD_AUTH_STEP_UP_REQUIRED"
    assert blocked.headers["X-Auth-Step-Up"] == ""
    assert blocked.headers["X-Auth-Step-Up-Guild"] == str(guild.id)


async def test_a_device_token_session_does_not_satisfy_the_rule(
    client: AsyncClient, session: AsyncSession
):
    """It records nothing about how its owner signed in, so it answers this
    the way it answers a rule naming one provider."""
    member, guild, _provider = await _guild_requiring_its_own_sso(session)
    device_token = await user_tokens.create_device_token(
        session, user_id=member.id, device_name="old-phone"
    )
    await session.commit()

    exchanged = await client.post(
        "/api/v1/auth/device-token/exchange", json={"device_token": device_token}
    )
    assert exchanged.status_code == 200, exchanged.text
    blocked = await client.get(
        f"/api/v1/g/{guild.id}/initiatives/",
        headers={"Authorization": f"Bearer {exchanged.json()['access_token']}"},
    )
    assert blocked.status_code == 401
    assert blocked.json()["detail"] == "GUILD_AUTH_STEP_UP_REQUIRED"


async def test_the_database_refuses_a_password_requirement(session: AsyncSession):
    """Whether passwords exist at all is the deployment's question, held as a
    constraint so it holds for every writer rather than only the endpoint."""
    guild = await create_guild(session)
    session.add(
        GuildAuthPolicy(
            guild_id=guild.id, policy="required", require_methods=["password"]
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


# --- The rule is decided twice, and the two must agree ----------------------


async def _database_admits(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
    satisfied: list[int],
    sso_guilds: list[int],
    session_mfa: bool = False,
) -> bool:
    """What ``public.guild_auth_satisfied()`` says, given the GUCs a request
    with this standing would have set.

    One statement, so the settings and the question are certainly in the same
    transaction — the context is transaction-local and replays on each new one.
    """
    verdict = (
        await session.exec(
            text(
                "SELECT set_config('app.current_user_id', :uid, true), "
                "set_config('app.current_guild_id', :gid, true), "
                "set_config('app.satisfied_providers', :satp, true), "
                "set_config('app.sso_guilds', :ssog, true), "
                "set_config('app.session_mfa', :mfa, true), "
                "public.guild_auth_satisfied() AS verdict"
            ),
            params={
                "uid": str(user_id),
                "gid": str(guild_id),
                "satp": ",".join(str(p) for p in satisfied),
                "ssog": ",".join(str(g) for g in sso_guilds),
                "mfa": "true" if session_mfa else "false",
            },
        )
    ).one()
    return bool(verdict.verdict)


def _app_admits(
    policy, guild_id: int, satisfied, sso_guilds, session_mfa: bool = False
) -> bool:
    """What the gate in ``deps.py`` says, given the same standing."""
    try:
        _enforce_guild_auth_policy(
            policy,
            guild_id,
            frozenset(satisfied),
            frozenset(sso_guilds),
            session_mfa,
        )
    except GuildAccessError:
        return False
    return True


async def test_the_gate_and_the_database_agree_on_every_rule(session: AsyncSession):
    """A rule is enforced in two places — Python before the request is routed,
    SQL inside the community's own row-level rules — and a disagreement between
    them is either a rule that does nothing or a refusal nobody can explain.

    Every shape a rule can take, against every standing a session can have.
    """
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(
        session, user=user, guild=guild, role=GuildRole.member
    )
    provider = await create_auth_provider(session, slug="corp", guild_id=guild.id)
    guild_id, user_id, provider_id = int(guild.id), int(user.id), int(provider.id)
    other_provider_id, other_guild_id = provider_id + 1000, guild_id + 1000

    rules: list[tuple[str, dict]] = [
        ("open", {"policy": "open"}),
        (
            "one named provider",
            {"policy": "required", "provider_id": provider_id, "provider_slug": "corp"},
        ),
        ("any of ours", {"policy": "required", "require_methods": ["sso"]}),
        ("a second factor", {"policy": "required", "require_methods": ["totp"]}),
        (
            "any of ours, and a second factor",
            {"policy": "required", "require_methods": ["sso", "totp"]},
        ),
        (
            "that provider, and any of ours",
            {
                "policy": "required",
                "provider_id": provider_id,
                "provider_slug": "corp",
                "require_methods": ["sso"],
            },
        ),
    ]
    bare: list[tuple[str, list[int], list[int]]] = [
        ("nothing at all", [], []),
        ("that provider, recorded both ways", [provider_id], [guild_id]),
        (
            "this community's sign-in, some other provider",
            [other_provider_id],
            [guild_id],
        ),
        ("another community's sign-in", [other_provider_id], [other_guild_id]),
        ("that provider, no community recorded", [provider_id], []),
        ("this community recorded, no provider", [], [guild_id]),
    ]
    # Each of those twice: a session that presented the account's second factor
    # and one that did not. A rule asking for a factor is answered by nothing
    # else on this list.
    standings: list[tuple[str, list[int], list[int], bool]] = [
        (f"{name}{', with a factor' if mfa else ''}", sat, guilds, mfa)
        for name, sat, guilds in bare
        for mfa in (False, True)
    ]

    for rule_name, fields in rules:
        row = await session.get(GuildAuthPolicy, guild_id)
        if row is not None:
            await session.delete(row)
            await session.commit()
        stored = GuildAuthPolicy(guild_id=guild_id, **fields)
        session.add(stored)
        await session.commit()
        await session.refresh(stored)

        for standing, satisfied, guilds, mfa in standings:
            in_app = _app_admits(stored, guild_id, satisfied, guilds, mfa)
            in_db = await _database_admits(
                session,
                guild_id=guild_id,
                user_id=user_id,
                satisfied=satisfied,
                sso_guilds=guilds,
                session_mfa=mfa,
            )
            assert in_app == in_db, (
                f"rule {rule_name!r} against a session showing {standing!r}: "
                f"the gate says {in_app}, the database says {in_db}"
            )

    # The matrix would pass if both layers refused everything, so pin the two
    # ends of it: an open community admits a bare session, and a rule refuses one.
    await session.exec(
        text("DELETE FROM guild_auth_policies WHERE guild_id = :g"),
        params={"g": guild_id},
    )
    await session.commit()
    assert await _database_admits(
        session, guild_id=guild_id, user_id=user_id, satisfied=[], sso_guilds=[]
    )
    session.add(
        GuildAuthPolicy(guild_id=guild_id, policy="required", require_methods=["sso"])
    )
    await session.commit()
    assert not await _database_admits(
        session, guild_id=guild_id, user_id=user_id, satisfied=[], sso_guilds=[]
    )


# --- A community that asks for a second factor -------------------------------


async def _guild_requiring_a_factor(session: AsyncSession):
    member = await create_user(session)
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )
    session.add(
        GuildAuthPolicy(guild_id=guild.id, policy="required", require_methods=["totp"])
    )
    await session.commit()
    return member, guild


def _factor_headers(user, *, with_factor: bool):
    token = get_auth_token(user, amr=["pwd", "otp", "mfa"] if with_factor else ["pwd"])
    return {"Authorization": f"Bearer {token}"}


async def test_a_session_carrying_the_factor_is_admitted(
    client: AsyncClient, session: AsyncSession
):
    member, guild = await _guild_requiring_a_factor(session)
    allowed = await client.get(
        f"/api/v1/g/{guild.id}/initiatives/",
        headers=_factor_headers(member, with_factor=True),
    )
    assert allowed.status_code == 200, allowed.text


async def test_a_password_session_is_asked_for_the_factor(
    client: AsyncClient, session: AsyncSession
):
    """A 401 that names no provider: what answers it is a code against the
    session already open, not a sign-in page."""
    member, guild = await _guild_requiring_a_factor(session)
    refused = await client.get(
        f"/api/v1/g/{guild.id}/initiatives/",
        headers=_factor_headers(member, with_factor=False),
    )
    assert refused.status_code == 401
    assert refused.json()["detail"] == "GUILD_AUTH_FACTOR_REQUIRED"
    assert refused.headers["X-Auth-Step-Up-Guild"] == str(guild.id)
    assert "insufficient_user_authentication" in refused.headers["WWW-Authenticate"]


async def test_a_recovery_code_session_is_admitted_too(
    client: AsyncClient, session: AsyncSession
):
    """The set exists to be used. A recovery code records ``mfa`` without
    ``otp``, and the rule asks for the factor rather than for a live one."""
    member, guild = await _guild_requiring_a_factor(session)
    token = get_auth_token(member, amr=["pwd", "mfa"])
    allowed = await client.get(
        f"/api/v1/g/{guild.id}/initiatives/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert allowed.status_code == 200, allowed.text


async def test_the_database_refuses_it_even_where_the_gate_is_skipped(
    session: AsyncSession, role_session
):
    """Both layers or neither: the row-level rule answers on its own."""
    member, guild = await _guild_requiring_a_factor(session)
    guild_id, user_id = int(guild.id), int(member.id)

    assert not await _database_admits(
        session, guild_id=guild_id, user_id=user_id, satisfied=[], sso_guilds=[]
    )
    assert await _database_admits(
        session,
        guild_id=guild_id,
        user_id=user_id,
        satisfied=[],
        sso_guilds=[],
        session_mfa=True,
    )
