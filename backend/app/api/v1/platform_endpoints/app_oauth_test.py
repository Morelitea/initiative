"""The app platform's token endpoint and the listing an app token reaches.

An app authenticates with a JWT it signs (RFC 7523 §2.2) against the key set
its registration publishes, and is issued an app token or an installation
token. Every refusal is the OAuth error body RFC 6749 §5.2 defines.
"""

from __future__ import annotations

import time

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.app_access_token import (
    ACCESS_TOKEN_PREFIX,
    AppAccessToken,
    InstallAccessToken,
    unseal_access_token,
)
from app.models.tenant.guild_app import GuildApp
from app.services.marketplace import app_oauth
from app.services.marketplace.app_refs import ensure_app_guild_ref
from app.services.tenant import app_revocation, app_updates
from app.testing import route_session_to_guild
from app.testing.app_clients import (
    CLIENT,
    RSA_KID,
    InstalledApp,
    install_app,
    mint_client_assertion,
)

TOKEN_URL = "/api/v1/app-platform/oauth/token"
INSTALLATIONS_URL = "/api/v1/app-platform/installations"
ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"


def _assertion(**overrides) -> str:
    overrides.setdefault("audience", app_oauth.token_endpoint_url())
    return mint_client_assertion(**overrides)


async def _ask(client: AsyncClient, *, assertion: str | None = None, **form):
    body = {
        "grant_type": "client_credentials",
        "client_assertion_type": ASSERTION_TYPE,
        "client_assertion": assertion if assertion is not None else _assertion(),
        **form,
    }
    return await client.post(TOKEN_URL, data=body)


def _error(response) -> str:
    return response.json()["error"]


async def _installation(installed: InstalledApp) -> str:
    return await ensure_app_guild_ref(
        guild_id=installed.guild.id, app_install_id=installed.app.id
    )


# ---------------------------------------------------------------------------
# App tokens
# ---------------------------------------------------------------------------


async def test_an_app_token_names_only_the_client(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    await install_app(session, acting_user, role_session, granted=["documents:read"])

    response = await _ask(client)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 600
    assert body["scope"] == ""
    assert body["access_token"].startswith(ACCESS_TOKEN_PREFIX)
    assert response.headers["cache-control"] == "no-store"
    token = unseal_access_token(body["access_token"])
    assert token == AppAccessToken(client_id=CLIENT, exp=token.exp)


async def test_a_p256_key_authenticates_too(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    await install_app(session, acting_user, role_session, granted=["documents:read"])

    response = await _ask(client, assertion=_assertion(key="ec"))

    assert response.status_code == 200, response.text


# ---------------------------------------------------------------------------
# Installation tokens
# ---------------------------------------------------------------------------


async def test_an_installation_token_carries_every_granted_scope(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_app(
        session,
        acting_user,
        role_session,
        granted=["documents:write", "comments:read"],
    )

    response = await _ask(client, installation=await _installation(installed))

    assert response.status_code == 200, response.text
    assert response.json()["scope"] == "comments:read documents:write"
    token = unseal_access_token(response.json()["access_token"])
    assert isinstance(token, InstallAccessToken)
    assert token.guild_id == installed.guild.id
    assert token.install_id == installed.app.id
    assert token.client_id == CLIENT
    assert token.scopes == frozenset({"documents:write", "comments:read"})
    assert token.initiative_id is None


async def test_an_installation_token_can_be_down_scoped(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_app(
        session,
        acting_user,
        role_session,
        granted=["documents:write", "comments:read"],
    )

    response = await _ask(
        client, installation=await _installation(installed), scope="comments:read"
    )

    assert response.status_code == 200, response.text
    assert response.json()["scope"] == "comments:read"
    token = unseal_access_token(response.json()["access_token"])
    assert isinstance(token, InstallAccessToken)
    assert token.scopes == frozenset({"comments:read"})


async def test_a_written_resource_may_be_asked_for_at_read(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:write"]
    )

    response = await _ask(
        client, installation=await _installation(installed), scope="documents:read"
    )

    assert response.status_code == 200, response.text
    assert response.json()["scope"] == "documents:read"


async def test_a_scope_to_use_another_app_is_issued_and_asked_for_by_name(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_app(
        session,
        acting_user,
        role_session,
        granted=["documents:read", "apps:tests.github"],
        requested=["documents:read", "apps:tests.github"],
    )
    installation = await _installation(installed)

    everything = await _ask(client, installation=installation)
    assert everything.status_code == 200, everything.text
    assert everything.json()["scope"] == "apps:tests.github documents:read"

    narrowed = await _ask(client, installation=installation, scope="apps:tests.github")
    assert narrowed.status_code == 200, narrowed.text
    token = unseal_access_token(narrowed.json()["access_token"])
    assert isinstance(token, InstallAccessToken)
    assert token.scopes == frozenset({"apps:tests.github"})

    other = await _ask(client, installation=installation, scope="apps:tests.other")
    assert other.status_code == 400
    assert _error(other) == "invalid_scope"


@pytest.mark.parametrize("scope", ["projects:read", "documents:write", "not-a-scope"])
async def test_a_scope_beyond_the_grant_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, scope
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )

    response = await _ask(
        client, installation=await _installation(installed), scope=scope
    )

    assert response.status_code == 400
    assert _error(response) == "invalid_scope"


async def _upgrade_dropping(session: AsyncSession, installed: InstalledApp, keep):
    """Move the install to a version whose manifest requests only ``keep``,
    through the same re-pin the Update button and the sweep use."""
    await route_session_to_guild(session, installed.guild.id)
    row = (
        await session.exec(select(GuildApp).where(GuildApp.id == installed.app.id))
    ).one()
    definition = {
        **row.definition,
        "service": {**row.definition["service"], "scopes": list(keep)},
    }
    await app_updates.apply_version(
        session,
        row,
        app_updates.PendingUpdate(version="1.1.0", definition=definition),
        guild_id=installed.guild.id,
    )
    await session.commit()
    app_revocation.drain_revocations(session)


async def test_a_scope_the_pinned_version_dropped_is_not_issued(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    """The seat's grant is left as it was; the next token carries only what
    the pinned version still requests."""
    installed = await install_app(
        session,
        acting_user,
        role_session,
        granted=["documents:write", "comments:read"],
    )
    installation = await _installation(installed)
    before = await _ask(client, installation=installation)
    assert before.json()["scope"] == "comments:read documents:write"

    await _upgrade_dropping(session, installed, ["comments:read"])

    after = await _ask(client, installation=installation)
    assert after.status_code == 200, after.text
    assert after.json()["scope"] == "comments:read"
    refused = await _ask(client, installation=installation, scope="documents:write")
    assert refused.status_code == 400
    assert _error(refused) == "invalid_scope"

    (row,) = (await session.exec(select(GuildApp))).all()
    assert sorted(row.granted_scopes) == ["comments:read", "documents:write"]


async def test_a_placed_initiative_narrows_the_token(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )

    response = await _ask(
        client,
        installation=await _installation(installed),
        resource=f"urn:initiative:initiative:{installed.placed.id}",
    )

    assert response.status_code == 200, response.text
    token = unseal_access_token(response.json()["access_token"])
    assert isinstance(token, InstallAccessToken)
    assert token.initiative_id == installed.placed.id


@pytest.mark.parametrize("which", ["unplaced", "malformed"])
async def test_an_initiative_it_is_not_placed_in_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, which
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    resource = (
        f"urn:initiative:initiative:{installed.unplaced.id}"
        if which == "unplaced"
        else "urn:initiative:project:1"
    )

    response = await _ask(
        client, installation=await _installation(installed), resource=resource
    )

    assert response.status_code == 400
    assert _error(response) == "invalid_target"


async def test_an_unknown_installation_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    await install_app(session, acting_user, role_session, granted=["documents:read"])

    response = await _ask(client, installation="not-a-reference")

    assert response.status_code == 400
    assert _error(response) == "invalid_grant"


async def test_another_clients_installation_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    await install_app(session, acting_user, role_session, granted=["documents:read"])
    other = await install_app(
        session,
        acting_user,
        role_session,
        granted=["documents:read"],
        client_id="tests.other-client",
        listing_uid="OTHERCLIENT001",
    )

    response = await _ask(client, installation=await _installation(other))

    assert response.status_code == 400
    assert _error(response) == "invalid_grant"


async def test_the_member_grant_takes_no_client_assertion(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    """Its assertion authenticates the client (RFC 7523 §3); the member grant
    itself is in ``app_member_tokens_test``."""
    await install_app(session, acting_user, role_session, granted=["documents:read"])

    response = await _ask(
        client, grant_type="urn:ietf:params:oauth:grant-type:jwt-bearer"
    )

    assert response.status_code == 400
    assert _error(response) == "invalid_request"


async def test_an_unknown_grant_type_is_unsupported(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    await install_app(session, acting_user, role_session, granted=["documents:read"])

    response = await _ask(client, grant_type="password")

    assert response.status_code == 400
    assert _error(response) == "unsupported_grant_type"


# ---------------------------------------------------------------------------
# Client authentication
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"audience": "https://elsewhere.example/token"}, id="bad-aud"),
        pytest.param({"kid": "no-such-kid"}, id="unknown-kid"),
        # Signed with the P-256 key under the RSA key's kid: the header says
        # ES256 and the key it names is RSA.
        pytest.param({"key": "ec", "kid": RSA_KID}, id="alg-disagrees-with-key"),
        pytest.param({"lifetime": 301}, id="lives-too-long"),
        pytest.param({"issued_ago": 120, "lifetime": 60}, id="expired"),
        pytest.param({"issued_ago": -300, "lifetime": 60}, id="issued-in-future"),
        pytest.param({"client_id": "tests.nobody"}, id="unknown-iss"),
        pytest.param({"subject": "tests.someone-else"}, id="sub-is-not-iss"),
    ],
)
async def test_a_bad_assertion_is_an_invalid_client(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, overrides
):
    await install_app(session, acting_user, role_session, granted=["documents:read"])
    overrides = dict(overrides)
    issued_ago = overrides.pop("issued_ago", None)
    if issued_ago is not None:
        overrides["issued_at"] = time.time() - issued_ago

    response = await _ask(client, assertion=_assertion(**overrides))

    assert response.status_code == 401
    assert _error(response) == "invalid_client"


async def test_an_assertion_is_used_once(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    await install_app(session, acting_user, role_session, granted=["documents:read"])
    assertion = _assertion()

    first = await _ask(client, assertion=assertion)
    second = await _ask(client, assertion=assertion)

    assert first.status_code == 200, first.text
    assert second.status_code == 401
    assert _error(second) == "invalid_client"


async def test_a_disabled_registration_is_an_invalid_client(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    await install_app(
        session, acting_user, role_session, granted=["documents:read"], enabled=False
    )

    response = await _ask(client)

    assert response.status_code == 401
    assert _error(response) == "invalid_client"


async def test_no_assertion_is_an_invalid_client(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    await install_app(session, acting_user, role_session, granted=["documents:read"])

    response = await client.post(TOKEN_URL, data={"grant_type": "client_credentials"})

    assert response.status_code == 401
    assert _error(response) == "invalid_client"


async def test_a_json_body_is_an_invalid_request(client: AsyncClient):
    response = await client.post(TOKEN_URL, json={"grant_type": "client_credentials"})

    assert response.status_code == 400
    assert _error(response) == "invalid_request"


# ---------------------------------------------------------------------------
# The app's installs
# ---------------------------------------------------------------------------


async def test_an_app_token_lists_the_installs_a_page_at_a_time(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    """Read from the install index, with the next page named in a ``Link``
    header until the last."""
    first = await install_app(
        session, acting_user, role_session, granted=["documents:write"]
    )
    second = await install_app(
        session, acting_user, role_session, granted=[], register=False
    )
    app_token = (await _ask(client)).json()["access_token"]
    headers = {"Authorization": f"Bearer {app_token}"}

    page = await client.get(INSTALLATIONS_URL, params={"limit": 1}, headers=headers)

    assert page.status_code == 200, page.text
    assert page.json() == [{"installation": await _installation(first), "active": True}]
    link = page.headers["link"]
    assert link.startswith("<?") and link.endswith('>; rel="next"')
    last = await client.get(f"{INSTALLATIONS_URL}{link[1:-13]}", headers=headers)
    assert last.json() == [
        {"installation": await _installation(second), "active": True}
    ]
    assert "link" not in last.headers


@pytest.mark.parametrize("paused_by", ["install_off", "guild_on_hold", "guild_deleted"])
async def test_a_paused_install_is_listed_as_inactive(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    role_session,
    paused_by: str,
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    app_token = (await _ask(client)).json()["access_token"]
    installation = await _installation(installed)
    if paused_by == "install_off":
        switched = await client.patch(
            installed.seat.g(f"/apps/{installed.app.id}"),
            json={"enabled": False},
            headers=installed.seat.headers,
        )
        assert switched.status_code == 200, switched.text
    else:
        status = "on_hold" if paused_by == "guild_on_hold" else "deleted"
        await session.exec(
            text("UPDATE public.guilds SET status = :s WHERE id = :id").bindparams(
                s=status, id=installed.guild.id
            )
        )
    await session.commit()

    response = await client.get(
        INSTALLATIONS_URL, headers={"Authorization": f"Bearer {app_token}"}
    )

    assert response.status_code == 200, response.text
    [listed] = response.json()
    assert listed["installation"] == installation
    assert listed["active"] is False


async def test_an_installation_token_does_not_list_installs(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    installation_token = (
        await _ask(client, installation=await _installation(installed))
    ).json()["access_token"]

    response = await client.get(
        INSTALLATIONS_URL, headers={"Authorization": f"Bearer {installation_token}"}
    )

    assert response.status_code == 401
