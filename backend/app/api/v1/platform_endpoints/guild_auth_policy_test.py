"""Guild auth policy: admin endpoints, the step-up gate, and the DB-layer
session-satisfaction enforcement inside the guild RLS."""

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import GuildAccessError, establish_guild_access
from app.core.auth_context import satisfied_provider_ids
from app.db.session import SYSTEM_SATISFIED, set_rls_context
from app.models.platform.guild import GuildRole
from app.models.platform.guild_auth_policy import GuildAuthPolicy
from app.models.tenant.project import Project
from app.services.platform.ws_auth import authenticate_ws_token
from app.testing.factories import (
    create_auth_provider,
    create_document,
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_user,
    get_auth_headers,
    get_auth_token,
    get_new_access_token,
)

pytestmark = [pytest.mark.integration, pytest.mark.auth]


def _sat_headers(user, provider_ids: list[int]) -> dict[str, str]:
    token = get_new_access_token(user, satisfied_providers=provider_ids)
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


async def test_admin_sets_reads_and_clears_policy(
    client: AsyncClient, session: AsyncSession
):
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    provider = await create_auth_provider(session, slug="corp")
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
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    disabled = await create_auth_provider(session, slug="off", enabled=False)
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


async def test_policy_requires_admin_own_session_to_satisfy(
    client: AsyncClient, session: AsyncSession
):
    """An admin can only require a provider their own session has satisfied —
    proving it works and keeping them from locking out their guild."""
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    provider = await create_auth_provider(session, slug="corp")

    response = await client.put(
        f"/api/v1/guilds/{guild.id}/auth-policy",
        headers=get_auth_headers(admin),  # legacy token: sat is empty
        json={"policy": "required", "provider_id": provider.id},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "GUILD_AUTH_POLICY_SELF_UNSATISFIED"


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

    # A session that satisfied the provider passes.
    allowed = await client.get(
        f"/api/v1/g/{guild.id}/initiatives/",
        headers=_sat_headers(member, [provider.id]),
    )
    assert allowed.status_code == 200


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
    await create_document(session, open_initiative, user, title="open doc")
    await create_document(session, gated_initiative, user, title="gated doc")
    await _require_provider(session, gated_guild.id, provider)
    provider_id = provider.id

    # Legacy/unsatisfied session: only the open guild's document.
    unsatisfied = await client.get(
        "/api/v1/me/documents", headers=get_auth_headers(user)
    )
    assert unsatisfied.status_code == 200, unsatisfied.text
    assert [d["title"] for d in unsatisfied.json()["items"]] == ["open doc"]

    # A session that satisfied the provider sees both guilds' documents.
    satisfied = await client.get(
        "/api/v1/me/documents", headers=_sat_headers(user, [provider_id])
    )
    titles = {d["title"] for d in satisfied.json()["items"]}
    assert titles == {"open doc", "gated doc"}


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

    # Legacy session token: authenticates, but the policy gate refuses.
    legacy_user = await authenticate_ws_token(get_auth_token(user), session)
    assert legacy_user is not None
    assert satisfied_provider_ids() == frozenset()
    with pytest.raises(GuildAccessError):
        await establish_guild_access(session, legacy_user, guild_id)

    # A satisfied session token joins.
    sat_user = await authenticate_ws_token(
        get_new_access_token(user, satisfied_providers=[provider_id]), session
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
