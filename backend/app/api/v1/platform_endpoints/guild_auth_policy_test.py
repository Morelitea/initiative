"""Guild auth policy: admin endpoints, the step-up gate, and the DB-layer
session-satisfaction enforcement inside the guild RLS."""

import json
from dataclasses import dataclass
from collections.abc import Awaitable, Callable

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
from app.core.auth_context import (
    satisfied_provider_ids,
    set_satisfied_claims,
    set_satisfied_providers,
)
from app.db.session import SYSTEM_SATISFIED, set_rls_context
from app.models.platform.guild import Guild, GuildRole
from app.models.platform.guild_auth_policy import GuildAuthPolicy
from app.models.platform.user import User
from app.models.tenant.project import Project
from app.services.auth.assurance import SECOND_FACTOR_AMR
from app.services.platform import api_keys as api_keys_service
from app.services.platform import user_tokens
from app.services.platform.ws_auth import authenticate_ws_token
from app.testing.actor import Actor
from app.testing.factories import (
    create_auth_provider,
    create_document,
    create_guild,
    create_guild_auth_policy,
    create_guild_membership,
    create_guild_provider_connection,
    create_initiative,
    get_auth_token,
    guild_administration,
)

pytestmark = [pytest.mark.integration, pytest.mark.auth]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _sat_headers(user: User, provider_ids: list[int]) -> dict[str, str]:
    """A session that came in through those providers."""
    return _bearer(get_auth_token(user, satisfied_providers=provider_ids))


def _policy(guild_id: int) -> str:
    """The surface the seat holds: one community's sign-in requirement."""
    return f"/api/v1/guilds/{guild_id}/auth-policy"


# --- Setting, reading and lifting a requirement ------------------------------


async def test_the_seat_sets_reads_and_clears_the_policy(
    client: AsyncClient, session: AsyncSession, acting_user
):
    seat = await acting_user(guild_role=GuildRole.superadmin)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_provider_connection(session, guild=seat.guild, provider=provider)
    headers = _sat_headers(seat.user, [provider.id])
    guild_id = seat.guild.id

    put = await client.put(
        _policy(guild_id),
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
        # The deployment asks nothing of its own, so the community's box for a
        # second factor is still the community's to tick.
        "factor_required_by_platform": False,
    }

    got = await client.get(_policy(guild_id), headers=headers)
    assert got.json()["policy"] == "required"

    cleared = await client.put(
        _policy(guild_id), headers=headers, json={"policy": "open"}
    )
    assert cleared.json()["policy"] == "open"
    session.expire_all()
    assert await session.get(GuildAuthPolicy, guild_id) is None


async def test_non_admin_cannot_manage_policy(
    client: AsyncClient, session: AsyncSession, acting_user
):
    member = await acting_user(guild_role=GuildRole.member)
    provider = await create_auth_provider(session, slug="corp")

    response = await client.put(
        _policy(member.guild.id),
        headers=_sat_headers(member.user, [provider.id]),
        json={"policy": "required", "provider_id": provider.id},
    )
    assert response.status_code == 403


async def _one_the_deployment_switched_off(
    session: AsyncSession, guild: Guild
) -> int | None:
    """Connected, and no longer login-ready."""
    provider = await create_auth_provider(session, slug="off", enabled=False)
    await create_guild_provider_connection(session, guild=guild, provider=provider)
    return provider.id


async def _one_nobody_connects_to(session: AsyncSession, guild: Guild) -> int | None:
    return (await create_auth_provider(session, slug="corp")).id


async def _another_communitys(session: AsyncSession, guild: Guild) -> int | None:
    provider = await create_auth_provider(session, slug="other-corp")
    await create_guild_provider_connection(
        session, guild=await create_guild(session), provider=provider
    )
    return provider.id


async def _no_provider_and_no_method(session: AsyncSession, guild: Guild) -> None:
    return None


@pytest.mark.parametrize(
    "name_a_provider",
    [
        pytest.param(_one_the_deployment_switched_off, id="switched off"),
        pytest.param(_one_nobody_connects_to, id="nobody connects to it"),
        pytest.param(_another_communitys, id="another community's"),
        pytest.param(_no_provider_and_no_method, id="none, and no method either"),
    ],
)
async def test_a_requirement_names_a_working_provider_of_this_communitys(
    client: AsyncClient, session: AsyncSession, acting_user, name_a_provider
):
    """A connection is what makes a provider this community's, and the
    provider has to be one the deployment still offers. A requirement naming
    anything else is refused, and so is one that names nothing at all —
    ``required`` has to require something."""
    seat = await acting_user(guild_role=GuildRole.superadmin)
    provider_id = await name_a_provider(session, seat.guild)
    body: dict[str, object] = {"policy": "required"}
    if provider_id is not None:
        body["provider_id"] = provider_id

    response = await client.put(
        _policy(seat.guild.id),
        headers=_sat_headers(seat.user, [provider_id] if provider_id else []),
        json=body,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "GUILD_AUTH_POLICY_INVALID_PROVIDER"


async def test_policy_requires_admin_own_session_to_satisfy(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """An admin can only require a provider their own session has satisfied —
    proving it works and keeping them from locking out their guild."""
    seat = await acting_user(guild_role=GuildRole.superadmin)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_provider_connection(session, guild=seat.guild, provider=provider)

    response = await client.put(
        _policy(seat.guild.id),
        headers=seat.headers,  # legacy token: sat is empty
        json={"policy": "required", "provider_id": provider.id},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "GUILD_AUTH_POLICY_SELF_UNSATISFIED"
    # One code for four different asks, so the header is what tells the page
    # which line of the form the refusal is about.
    assert response.headers["X-Auth-Policy-Unmet"] == "provider"


async def test_without_the_entitlement_a_requirement_is_read_and_lifted_only(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """With the operator toggle off the config surface closes, and the three
    verbs part company: reading a standing requirement works, setting one 404s
    with the same GUILD_AUTH_NOT_ENABLED shape as platform posture and writes
    nothing, and lifting the standing one is still reachable.

    Enforcement reads the policy row alone, so a requirement outlives the
    entitlement that allowed it to be set; the way to lift one outlives it too.
    Lifting only ever admits more, so it carries none of the gating the setting
    path does."""
    guild = await create_guild(session, auth_options=[])
    seat = await acting_user(guild_role=GuildRole.superadmin, guild=guild)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_auth_policy(session, guild, provider)
    headers = _sat_headers(seat.user, [provider.id])
    guild_id, provider_id = guild.id, provider.id

    got = await client.get(_policy(guild_id), headers=headers)
    assert got.status_code == 200
    assert got.json()["policy"] == "required"
    assert got.json()["provider_slug"] == "corp"

    put = await client.put(
        _policy(guild_id),
        headers=headers,
        json={"policy": "required", "provider_id": provider_id},
    )
    assert put.status_code == 404
    assert put.json()["detail"] == "GUILD_AUTH_NOT_ENABLED"
    session.expire_all()
    untouched = await session.get(GuildAuthPolicy, guild_id)
    assert untouched is not None and untouched.policy == "required"

    cleared = await client.put(
        _policy(guild_id), headers=headers, json={"policy": "open"}
    )
    assert cleared.status_code == 200
    assert cleared.json()["policy"] == "open"
    session.expire_all()
    assert await session.get(GuildAuthPolicy, guild_id) is None


# --- The gate: what a standing requirement does to a session -----------------


async def test_a_required_provider_steps_up_every_session_that_lacks_it(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The answer a standing requirement gives, and how long it gives it for:
    turning the operator toggle OFF closes the config surface and leaves
    enforcement where it was (parity with the posture gate — management is
    gated, enforcement is not)."""
    member = await acting_user(guild_role=GuildRole.member)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_auth_policy(session, member.guild, provider)
    satisfied = _sat_headers(member.user, [provider.id])

    # Unsatisfied (legacy) session: 401 naming the provider to step up with.
    blocked = await client.get(member.g("/initiatives/"), headers=member.headers)
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
    allowed = await client.get(member.g("/initiatives/"), headers=satisfied)
    assert allowed.status_code == 200

    # Operator turns per-guild sign-in off after the requirement was set: both
    # answers stay as they were.
    await guild_administration(session, member.guild, auth_options=[])

    still_blocked = await client.get(member.g("/initiatives/"), headers=member.headers)
    assert still_blocked.status_code == 401
    assert still_blocked.json()["detail"] == "GUILD_AUTH_STEP_UP_REQUIRED"
    assert still_blocked.headers["X-Auth-Step-Up"] == "corp"

    still_allowed = await client.get(member.g("/initiatives/"), headers=satisfied)
    assert still_allowed.status_code == 200


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
    client: AsyncClient, session: AsyncSession, acting_user
):
    member = await acting_user(guild_role=GuildRole.member)

    response = await client.get(member.g("/initiatives/"), headers=member.headers)
    assert response.status_code == 200


# --- Credentials that record no sign-in --------------------------------------


async def _an_exchanged_device_token(
    client: AsyncClient, session: AsyncSession, user: User
) -> dict[str, str]:
    """The session a device token is traded for."""
    device_token = await user_tokens.create_device_token(
        session, user_id=user.id, device_name="old-phone"
    )
    await session.commit()
    exchanged = await client.post(
        "/api/v1/auth/device-token/exchange", json={"device_token": device_token}
    )
    assert exchanged.status_code == 200, exchanged.text
    return _bearer(exchanged.json()["access_token"])


async def _a_device_token(
    client: AsyncClient, session: AsyncSession, user: User
) -> dict[str, str]:
    """The same credential presented as one, rather than traded for a session."""
    device_token = await user_tokens.create_device_token(
        session, user_id=user.id, device_name="old-phone"
    )
    await session.commit()
    return {"Authorization": f"DeviceToken {device_token}"}


async def _an_api_key(
    client: AsyncClient, session: AsyncSession, user: User
) -> dict[str, str]:
    secret, _row = await api_keys_service.create_api_key(session, user=user, name="ci")
    await session.commit()
    return _bearer(secret)


async def _require_one_named_provider(session: AsyncSession, guild: Guild) -> None:
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_auth_policy(session, guild, provider)


async def _require_any_of_ours(session: AsyncSession, guild: Guild) -> None:
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_provider_connection(session, guild=guild, provider=provider)
    session.add(
        GuildAuthPolicy(guild_id=guild.id, policy="required", require_methods=["sso"])
    )
    await session.commit()


@pytest.mark.parametrize(
    "require_a_sign_in,step_up_slug",
    [
        pytest.param(_require_one_named_provider, "corp", id="one named provider"),
        pytest.param(_require_any_of_ours, "", id="any of ours"),
    ],
)
@pytest.mark.parametrize(
    "open_credential",
    [
        pytest.param(_an_exchanged_device_token, id="exchanged device token"),
        pytest.param(_a_device_token, id="device token"),
        pytest.param(_an_api_key, id="api key"),
    ],
)
async def test_a_credential_that_records_no_sign_in_satisfies_no_requirement(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    open_credential,
    require_a_sign_in,
    step_up_slug: str,
):
    """A device token and an API key are both derived from a sign-in that
    already happened and record nothing about it, so the session each buys
    carries no providers. Whichever shape the requirement takes — one named
    provider, or any of this community's — such a session gets the answer every
    unsatisfied session gets, and the challenge names what would serve it."""
    member = await acting_user(guild_role=GuildRole.member)
    await require_a_sign_in(session, member.guild)
    headers = await open_credential(client, session, member.user)

    blocked = await client.get(member.g("/initiatives/"), headers=headers)
    assert blocked.status_code == 401, blocked.text
    assert blocked.json()["detail"] == "GUILD_AUTH_STEP_UP_REQUIRED"
    assert blocked.headers["X-Auth-Step-Up"] == step_up_slug


# --- The seat itself: who holds it, and what holds it in place ---------------


async def _a_seat_and_a_requirement(session: AsyncSession, acting_user) -> Actor:
    """A community with a standing requirement, one superadmin holding it, and
    an ordinary admin beside them. Returns the keyholder."""
    keyholder = await acting_user(guild_role=GuildRole.superadmin)
    await acting_user(guild_role=GuildRole.admin, guild=keyholder.guild)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_auth_policy(session, keyholder.guild, provider)
    return keyholder


async def test_an_ordinary_admin_reads_the_seats_surfaces_but_writes_neither(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The split in one test, across both surfaces the seat holds: an admin who
    cannot see what is set cannot ask for it to be changed, so reading the
    requirement and the connections is theirs. Deciding who may enter, and
    which providers the community signs in through, is not."""
    keyholder = await _a_seat_and_a_requirement(session, acting_user)
    admin = await acting_user(guild_role=GuildRole.admin, guild=keyholder.guild)
    guild_id = keyholder.guild.id
    connections = f"/api/v1/guilds/{guild_id}/auth/connections"

    read = await client.get(_policy(guild_id), headers=admin.headers)
    assert read.status_code == 200
    assert read.json()["policy"] == "required"

    listed = await client.get(connections, headers=admin.headers)
    assert listed.status_code == 200
    assert [row["provider_slug"] for row in listed.json()] == ["corp"]

    offered = await client.get(f"{connections}/available", headers=admin.headers)
    assert offered.status_code == 200

    writes = (
        client.put(_policy(guild_id), headers=admin.headers, json={"policy": "open"}),
        client.put(
            _policy(guild_id),
            headers=admin.headers,
            json={"policy": "required", "provider_id": 1},
        ),
        client.post(connections, headers=admin.headers, json={"provider_id": 1}),
    )
    for write in writes:
        refused = await write
        assert refused.status_code == 403, refused.text
        assert refused.json()["detail"] == "GUILD_SUPERADMIN_REQUIRED"

    # And the row is untouched.
    session.expire_all()
    still_required = await session.get(GuildAuthPolicy, guild_id)
    assert still_required is not None and still_required.policy == "required"


async def test_the_last_seat_cannot_be_vacated_while_a_requirement_stands(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The requirement is lifted from the surface the seat holds, so the last
    holder stays for as long as the requirement does — asked for by the
    operator's role endpoint, and asked for by their own hand on the way
    out."""
    keyholder = await _a_seat_and_a_requirement(session, acting_user)
    operator = await acting_user("operator")
    guild_id, keyholder_id = keyholder.guild.id, keyholder.user.id

    demoted = await client.patch(
        f"/api/v1/admin/guilds/{guild_id}/members/{keyholder_id}/role",
        headers=operator.headers,
        json={"role": "member"},
    )
    assert demoted.status_code == 400, demoted.text
    assert demoted.json()["detail"] == "CANNOT_VACATE_LAST_SUPERADMIN"

    left = await client.delete(
        f"/api/v1/guilds/{guild_id}/leave", headers=keyholder.headers
    )
    assert left.status_code == 400, left.text
    assert left.json()["detail"] == "CANNOT_VACATE_LAST_SUPERADMIN"


async def test_the_last_seat_stays_even_with_no_requirement(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Lifting the sign-in requirement does not free the seat.

    It did once, while the seat was about sign-in alone. It now holds billing
    too, and only an operator can seat a guild that has emptied it — so a guild
    keeps one whatever its sign-in rule says.
    """
    keyholder = await _a_seat_and_a_requirement(session, acting_user)
    operator = await acting_user("operator")
    policy_row = await session.get(GuildAuthPolicy, keyholder.guild.id)
    await session.delete(policy_row)
    await session.commit()
    role_url = (
        f"/api/v1/admin/guilds/{keyholder.guild.id}/members/{keyholder.user.id}/role"
    )

    refused = await client.patch(
        role_url, headers=operator.headers, json={"role": "member"}
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == "CANNOT_VACATE_LAST_SUPERADMIN"

    # A second holder is what frees the first.
    await acting_user(guild_role=GuildRole.superadmin, guild=keyholder.guild)
    allowed = await client.patch(
        role_url, headers=operator.headers, json={"role": "member"}
    )
    assert allowed.status_code == 204, allowed.text


async def test_provider_delete_refused_while_required(
    client: AsyncClient, session: AsyncSession, acting_user
):
    owner = await acting_user("owner")
    guild = await create_guild(session)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_auth_policy(session, guild, provider)

    response = await client.delete(
        f"/api/v1/settings/auth/providers/{provider.id}", headers=owner.headers
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "AUTH_PROVIDER_IN_USE"


# --- The gate on paths that are not a REST read of the guild's own content ---


async def test_me_aggregate_includes_policy_guild_only_when_satisfied(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Cross-guild /me/* views carry the session's real ``sat``: a policy-gated
    guild's content appears exactly when the session satisfies its provider —
    and its RLS keeps an unsatisfied session's aggregate empty for that guild
    without failing the whole request."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    await create_document(session, a.initiative, a.user, name="open doc")

    # The same person in a second community, which requires a sign-in.
    gated_guild = await create_guild(session)
    await create_guild_membership(session, user=a.user, guild=gated_guild)
    gated_initiative = await create_initiative(session, gated_guild, a.user)
    await create_document(session, gated_initiative, a.user, name="gated doc")
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_auth_policy(session, gated_guild, provider)
    provider_id = provider.id

    # Legacy/unsatisfied session: only the open guild's document.
    unsatisfied = await client.get("/api/v1/me/documents", headers=a.headers)
    assert unsatisfied.status_code == 200, unsatisfied.text
    assert [d["name"] for d in unsatisfied.json()["items"]] == ["open doc"]

    # A session that satisfied the provider sees both guilds' documents.
    satisfied = await client.get(
        "/api/v1/me/documents", headers=_sat_headers(a.user, [provider_id])
    )
    names = {d["name"] for d in satisfied.json()["items"]}
    assert names == {"open doc", "gated doc"}


async def test_ws_token_sat_gates_policy_guild(session: AsyncSession, acting_user):
    """The WebSocket join path: ``authenticate_ws_token`` records the token's
    ``sat``, and the ``establish_guild_access`` that follows applies the guild
    auth-policy gate to the socket exactly as REST would."""
    member = await acting_user(guild_role=GuildRole.member)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_auth_policy(session, member.guild, provider)
    guild_id, provider_id = member.guild.id, provider.id

    # A session that satisfied nothing: authenticates, gate refuses.
    plain_user = await authenticate_ws_token(get_auth_token(member.user), session)
    assert plain_user is not None
    assert satisfied_provider_ids() == frozenset()
    with pytest.raises(GuildAccessError):
        await establish_guild_access(session, plain_user, guild_id)

    # A satisfied session token joins.
    sat_user = await authenticate_ws_token(
        get_auth_token(member.user, satisfied_providers=[provider_id]), session
    )
    assert sat_user is not None
    assert satisfied_provider_ids() == frozenset({provider_id})
    ctx = await establish_guild_access(session, sat_user, guild_id)
    assert ctx.guild_id == guild_id


async def test_ws_token_carries_the_passkey_to_the_gate(
    session: AsyncSession, acting_user
):
    """The same join path against a community that asks for a passkey:
    ``authenticate_ws_token`` records what the session's ``amr`` proved, and
    the ``establish_guild_access`` that follows reads it — so a socket is
    admitted on the terms a page is."""
    member = await acting_user(guild_role=GuildRole.member)
    session.add(
        GuildAuthPolicy(
            guild_id=member.guild.id, policy="required", require_methods=["passkey"]
        )
    )
    await session.commit()
    guild_id = member.guild.id

    with_a_password = await authenticate_ws_token(
        get_auth_token(member.user, amr=["pwd"]), session
    )
    assert with_a_password is not None
    with pytest.raises(GuildAccessError):
        await establish_guild_access(session, with_a_password, guild_id)

    with_a_key = await authenticate_ws_token(
        get_auth_token(member.user, amr=["pwd", "hwk", "mfa"]), session
    )
    assert with_a_key is not None
    ctx = await establish_guild_access(session, with_a_key, guild_id)
    assert ctx.guild_id == guild_id


async def test_system_sentinel_passes_policy_gate(session: AsyncSession, acting_user):
    """User-attributed system work (export/import workers) passes the gate via
    the explicit sentinel — its enqueueing request already satisfied it."""
    member = await acting_user(guild_role=GuildRole.member)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_auth_policy(session, member.guild, provider)
    guild_id = member.guild.id

    ctx = await establish_guild_access(
        session, member.user, guild_id, satisfied_providers=SYSTEM_SATISFIED
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


async def test_db_layer_blocks_unsatisfied_session(
    session: AsyncSession, role_session, acting_user
):
    """The RLS gate itself: with a required policy, a routed user session that
    hasn't satisfied the provider sees ZERO content rows — regardless of any
    app-layer gate. Satisfied sessions, the user-attributed system sentinel,
    and pure system routings (no user) all see the rows."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_auth_policy(session, a.guild, provider)
    user_id, guild_id, provider_id = a.user.id, a.guild.id, provider.id

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


# --- The rule is decided twice, and the two must agree ----------------------


async def _database_admits(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
    satisfied: list[int],
    asserted: dict | None = None,
    markers: frozenset[str] = frozenset(),
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
                "set_config('app.satisfied_claims', :satc, true), "
                "set_config('app.session_amr', :amr, true), "
                "public.guild_auth_satisfied() AS verdict"
            ),
            params={
                "uid": str(user_id),
                "gid": str(guild_id),
                "satp": ",".join(str(p) for p in satisfied),
                "satc": json.dumps(asserted or {}),
                "amr": ",".join(sorted(markers)),
            },
        )
    ).one()
    return bool(verdict.verdict)


async def _app_admits(
    session: AsyncSession,
    policy,
    guild_id: int,
    satisfied,
    asserted: dict | None = None,
    markers: frozenset[str] = frozenset(),
) -> bool:
    """What the gate in ``deps.py`` says, given the same standing."""
    set_satisfied_providers(frozenset(satisfied))
    set_satisfied_claims(asserted or {})
    try:
        await _enforce_guild_auth_policy(
            session,
            policy,
            guild_id,
            frozenset(satisfied),
            markers,
        )
    except GuildAccessError:
        return False
    finally:
        set_satisfied_providers(None)
        set_satisfied_claims(None)
    return True


async def test_the_gate_and_the_database_agree_on_every_rule(
    session: AsyncSession, acting_user
):
    """A rule is enforced in two places — Python before the request is routed,
    SQL inside the community's own row-level rules — and a disagreement between
    them is either a rule that does nothing or a refusal nobody can explain.

    Every shape a rule can take, against every standing a session can have.
    """
    member = await acting_user(guild_role=GuildRole.member)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_provider_connection(
        session,
        guild=member.guild,
        provider=provider,
        claim="hd",
        claim_values=["acme.com"],
    )
    guild_id, user_id = int(member.guild.id), int(member.user.id)
    provider_id = int(provider.id)
    other_provider_id = provider_id + 1000

    async def db_admits(**proved) -> bool:
        """The database's verdict on a session that satisfied no provider and
        proved this much about itself."""
        return await _database_admits(
            session,
            guild_id=guild_id,
            user_id=user_id,
            satisfied=[],
            asserted={},
            **proved,
        )

    rules: list[tuple[str, dict]] = [
        ("open", {"policy": "open"}),
        (
            "one named provider",
            {"policy": "required", "provider_id": provider_id, "provider_slug": "corp"},
        ),
        ("any of ours", {"policy": "required", "require_methods": ["sso"]}),
        ("a second factor", {"policy": "required", "require_methods": ["totp"]}),
        ("a passkey", {"policy": "required", "require_methods": ["passkey"]}),
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
    ours = {str(provider_id): {"hd": ["acme.com"]}}
    theirs = {str(provider_id): {"hd": ["elsewhere.com"]}}
    bare: list[tuple[str, list[int], dict]] = [
        ("nothing at all", [], {}),
        ("that provider, counted as theirs", [provider_id], ours),
        ("that provider, counted as somebody else's", [provider_id], theirs),
        ("that provider, asserting nothing", [provider_id], {}),
        ("some other provider", [other_provider_id], {}),
        (
            "some other provider, asserting what this community counts",
            [other_provider_id],
            {str(other_provider_id): {"hd": ["acme.com"]}},
        ),
    ]
    # Each of those against what a session can have recorded about itself. A
    # rule asking for one marker is answered by nothing else on this list.
    # Both kinds of key appear, because the passkey leg takes either and a leg
    # naming only one of them would still pass a matrix that never showed it
    # the other. The key-without-a-factor row is not a session this codebase
    # opens — every ceremony verifies the person, so an assertion records
    # ``mfa`` too — and it is here to hold the two legs apart: it is the only
    # standing that answers a passkey rule and not a factor rule.
    proofs = [
        (", with a factor", frozenset({SECOND_FACTOR_AMR})),
        (", with a device-bound key", frozenset({"hwk", SECOND_FACTOR_AMR})),
        (", with a synced key", frozenset({"swk", SECOND_FACTOR_AMR})),
        (", with a key and no factor", frozenset({"hwk"})),
        ("", frozenset()),
    ]
    standings: list[tuple[str, list[int], dict, frozenset[str]]] = [
        (f"{name}{suffix}", sat, asserted, markers)
        for name, sat, asserted in bare
        for suffix, markers in proofs
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

        for standing, satisfied, asserted, markers in standings:
            in_app = await _app_admits(
                session, stored, guild_id, satisfied, asserted, markers
            )
            in_db = await _database_admits(
                session,
                guild_id=guild_id,
                user_id=user_id,
                satisfied=satisfied,
                asserted=asserted,
                markers=markers,
            )
            assert in_app == in_db, (
                f"rule {rule_name!r} against a session showing {standing!r}: "
                f"the gate says {in_app}, the database says {in_db}"
            )

    # The matrix says the two layers agree; it does not say what they agree
    # on. Name one answer outright: a community asking for a passkey takes the
    # key and takes nothing else for it.
    await session.exec(
        text("DELETE FROM guild_auth_policies WHERE guild_id = :g"),
        params={"g": guild_id},
    )
    await session.commit()
    asking_for_a_key = GuildAuthPolicy(
        guild_id=guild_id, policy="required", require_methods=["passkey"]
    )
    session.add(asking_for_a_key)
    await session.commit()
    await session.refresh(asking_for_a_key)
    a_key = frozenset({"hwk", SECOND_FACTOR_AMR})
    a_code = frozenset({SECOND_FACTOR_AMR})
    assert await _app_admits(session, asking_for_a_key, guild_id, [], None, a_key)
    assert await db_admits(markers=a_key)
    assert not await _app_admits(session, asking_for_a_key, guild_id, [], None, a_code)
    assert not await db_admits(markers=a_code)

    # The matrix would pass if both layers refused everything, so pin the two
    # ends of it: an open community admits a bare session, and a rule refuses one.
    await session.exec(
        text("DELETE FROM guild_auth_policies WHERE guild_id = :g"),
        params={"g": guild_id},
    )
    await session.commit()
    assert await db_admits()
    session.add(
        GuildAuthPolicy(guild_id=guild_id, policy="required", require_methods=["sso"])
    )
    await session.commit()
    assert not await db_admits()


# --- The three things a rule can ask for -------------------------------------
#
# ``require_methods`` names none, one or several of them, and each is read as
# itself. The table below is one row per ask: how a session that has met it is
# opened, what one that has not looks like and is told, and what the deployment
# has to offer before a community may write the ask down.


@dataclass(frozen=True, eq=False)
class Ask:
    """One thing ``require_methods`` can name, and what answers it."""

    id: str
    method: str
    # Opens a session that has met the ask, putting whatever the community
    # needs for it (a provider connection, say) in place first.
    met_by: Callable[[AsyncSession, Guild, User], Awaitable[dict[str, str]]]
    # The ``amr`` of a session that has not met it. Each is the strongest such
    # session for its ask, so the key's row carries a second factor.
    unmet_amr: list[str]
    # What that session is told, and the part of the challenge that is this
    # ask's own.
    refusal: str
    challenge: dict[str, str]
    # The deployment's login methods with this one left out; ``None`` where the
    # ask has no deployment-level switch of its own.
    withheld_by_the_deployment: list[str] | None


async def _a_session_through_one_of_ours(
    session: AsyncSession, guild: Guild, user: User
) -> dict[str, str]:
    """Came in through a provider this community connects to. Which sign-ins
    count is read from those connections, so one is made here."""
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_provider_connection(session, guild=guild, provider=provider)
    return _bearer(
        get_auth_token(user, amr=["oidc:whatever"], satisfied_providers=[provider.id])
    )


async def _a_session_carrying_the_factor(
    session: AsyncSession, guild: Guild, user: User
) -> dict[str, str]:
    return _bearer(get_auth_token(user, amr=["pwd", "otp", "mfa"]))


async def _a_session_opened_with_a_passkey(
    session: AsyncSession, guild: Guild, user: User
) -> dict[str, str]:
    return _bearer(get_auth_token(user, amr=["pwd", "hwk", "mfa"]))


ANY_OF_OURS = Ask(
    id="any of ours",
    method="sso",
    met_by=_a_session_through_one_of_ours,
    unmet_amr=["pwd"],
    refusal="GUILD_AUTH_STEP_UP_REQUIRED",
    # Named no provider, so the challenge names the community: its own login
    # page is what serves the rule.
    challenge={"X-Auth-Step-Up": ""},
    withheld_by_the_deployment=None,
)
A_SECOND_FACTOR = Ask(
    id="a second factor",
    method="totp",
    met_by=_a_session_carrying_the_factor,
    unmet_amr=["pwd"],
    refusal="GUILD_AUTH_FACTOR_REQUIRED",
    challenge={},
    withheld_by_the_deployment=["password", "sso"],
)
A_PASSKEY = Ask(
    id="a passkey",
    method="passkey",
    met_by=_a_session_opened_with_a_passkey,
    # An assertion records the second factor as well as the key, and a rule
    # naming the key reads the key's own markers.
    unmet_amr=["pwd", "otp", "mfa"],
    refusal="GUILD_AUTH_PASSKEY_REQUIRED",
    challenge={},
    withheld_by_the_deployment=["password", "sso", "totp"],
)
ASKS = [ANY_OF_OURS, A_SECOND_FACTOR, A_PASSKEY]


def _asks(*, the_deployment_can_withhold: bool = False) -> list:
    rows = [
        ask
        for ask in ASKS
        if not the_deployment_can_withhold or ask.withheld_by_the_deployment
    ]
    return [pytest.param(ask, id=ask.id) for ask in rows]


async def _a_community_asking_for(
    session: AsyncSession, acting_user, ask: Ask
) -> Actor:
    """A member of a community whose rule names ``ask``."""
    member = await acting_user(guild_role=GuildRole.member)
    session.add(
        GuildAuthPolicy(
            guild_id=member.guild.id, policy="required", require_methods=[ask.method]
        )
    )
    await session.commit()
    return member


@pytest.mark.parametrize("ask", _asks())
async def test_a_session_that_has_met_the_ask_is_admitted(
    client: AsyncClient, session: AsyncSession, acting_user, ask: Ask
):
    """Each ask has its own answer, and a member holding it is let in."""
    member = await _a_community_asking_for(session, acting_user, ask)
    headers = await ask.met_by(session, member.guild, member.user)

    allowed = await client.get(member.g("/initiatives/"), headers=headers)
    assert allowed.status_code == 200, allowed.text


@pytest.mark.parametrize("ask", _asks())
async def test_a_session_that_has_not_is_asked_for_it(
    client: AsyncClient, session: AsyncSession, acting_user, ask: Ask
):
    """The refusal says which ask is unmet, so a page knows what to put in
    front of the member: this community's login page for its own providers, a
    code or a ceremony against the session already open for the other two."""
    member = await _a_community_asking_for(session, acting_user, ask)
    guild_id = member.guild.id

    refused = await client.get(
        member.g("/initiatives/"),
        headers=_bearer(get_auth_token(member.user, amr=ask.unmet_amr)),
    )
    assert refused.status_code == 401
    assert refused.json()["detail"] == ask.refusal
    assert refused.headers["X-Auth-Step-Up-Guild"] == str(guild_id)
    # And the standard form beside it (RFC 9470), for a client that knows
    # OAuth and nothing about this app.
    assert "insufficient_user_authentication" in refused.headers["WWW-Authenticate"]
    for header, value in ask.challenge.items():
        assert refused.headers[header] == value


async def test_a_key_a_password_manager_syncs_answers_a_passkey_rule(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """``hwk`` is a key the device holds and ``swk`` one a password manager
    syncs between devices; a community asking for a passkey takes either."""
    member = await _a_community_asking_for(session, acting_user, A_PASSKEY)

    allowed = await client.get(
        member.g("/initiatives/"),
        headers=_bearer(get_auth_token(member.user, amr=["pwd", "swk", "mfa"])),
    )
    assert allowed.status_code == 200, allowed.text


async def test_a_recovery_code_session_is_admitted_too(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The set exists to be used. A recovery code records ``mfa`` without
    ``otp``, and the rule asks for the factor rather than for a live one."""
    member = await _a_community_asking_for(session, acting_user, A_SECOND_FACTOR)

    allowed = await client.get(
        member.g("/initiatives/"),
        headers=_bearer(get_auth_token(member.user, amr=["pwd", "mfa"])),
    )
    assert allowed.status_code == 200, allowed.text


async def test_another_communitys_sign_in_does_not_satisfy_any_of_ours(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Single sign-on somewhere else — the deployment's own providers included
    — is not this community's single sign-on."""
    member = await _a_community_asking_for(session, acting_user, ANY_OF_OURS)
    await create_guild_provider_connection(
        session,
        guild=member.guild,
        provider=await create_auth_provider(session, slug="corp"),
    )
    elsewhere = await create_auth_provider(session, slug="somewhere-else")

    blocked = await client.get(
        member.g("/initiatives/"),
        headers=_bearer(
            get_auth_token(
                member.user, amr=["oidc:whatever"], satisfied_providers=[elsewhere.id]
            )
        ),
    )
    assert blocked.status_code == 401
    assert blocked.json()["detail"] == "GUILD_AUTH_STEP_UP_REQUIRED"


@pytest.mark.parametrize("ask", _asks())
async def test_the_ask_is_written_only_by_a_session_that_has_met_it(
    client: AsyncClient, session: AsyncSession, acting_user, ask: Ask
):
    """The rule the provider check makes, for every other ask too: prove it
    before it binds anybody, so an ask is only ever written by somebody it
    already applies to. One code for four different asks, so the header is
    what tells the page which line of the form the refusal is about."""
    seat = await acting_user(guild_role=GuildRole.superadmin)
    # Whatever the ask needs of the community is in place, so the seat's own
    # session is the only thing standing between the form and the row.
    met = await ask.met_by(session, seat.guild, seat.user)
    body = {"policy": "required", "require_methods": [ask.method]}

    refused = await client.put(
        _policy(seat.guild.id),
        headers=_bearer(get_auth_token(seat.user, amr=ask.unmet_amr)),
        json=body,
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == "GUILD_AUTH_POLICY_SELF_UNSATISFIED"
    assert refused.headers["X-Auth-Policy-Unmet"] == ask.method

    saved = await client.put(_policy(seat.guild.id), headers=met, json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["require_methods"] == [ask.method]


@pytest.mark.parametrize("ask", _asks(the_deployment_can_withhold=True))
async def test_a_community_cannot_ask_for_what_the_deployment_withholds(
    client: AsyncClient, session: AsyncSession, acting_user, ask: Ask
):
    """A community's rule reaches only as far as the deployment's own list of
    login methods, and the header names the one that is not on it."""
    from app.services.platform import app_settings as app_settings_service

    seat = await acting_user(guild_role=GuildRole.superadmin)
    headers = await ask.met_by(session, seat.guild, seat.user)
    row = await app_settings_service.get_app_settings(session)
    assert ask.withheld_by_the_deployment is not None
    row.login_methods = ask.withheld_by_the_deployment
    session.add(row)
    await session.commit()

    refused = await client.put(
        _policy(seat.guild.id),
        headers=headers,
        json={"policy": "required", "require_methods": [ask.method]},
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == "GUILD_AUTH_POLICY_METHOD_UNAVAILABLE"
    assert refused.headers["X-Auth-Policy-Unmet"] == ask.method


async def test_a_community_is_told_when_the_deployment_asks_everybody(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Its own box for a second factor has nothing left to add, so the page
    reads this and stops offering one. Asking only the platform rungs leaves a
    community's members untouched, so that box stays."""
    from datetime import datetime, timezone

    from app.core.login_methods import SecondFactorRequirement
    from app.models.platform.user_totp import UserTotp
    from app.services.platform import app_settings as app_settings_service

    seat = await acting_user(guild_role=GuildRole.superadmin)
    # Under ``everyone`` this admin is asked for a factor like anybody else,
    # so they hold one — which is the state the page is read in.
    session.add(UserTotp(user_id=seat.user.id, confirmed_at=datetime.now(timezone.utc)))
    await session.commit()
    url = _policy(seat.guild.id)

    row = await app_settings_service.get_app_settings(session)
    for level, told in (
        (SecondFactorRequirement.platform_roles, False),
        (SecondFactorRequirement.everyone, True),
    ):
        row.second_factor_requirement = level
        session.add(row)
        await session.commit()

        read = await client.get(url, headers=seat.headers)

        assert read.status_code == 200, read.text
        assert read.json()["factor_required_by_platform"] is told
