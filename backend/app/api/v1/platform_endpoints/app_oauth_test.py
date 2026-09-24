"""The app platform's token endpoint and the listing an app token reaches.

An app authenticates with a JWT it signs (RFC 7523 §2.2) against the key set
its registration publishes, and is issued an app token or an installation
token. Every refusal is the OAuth error body RFC 6749 §5.2 defines.
"""

from __future__ import annotations

import time

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.app_access_token import (
    ACCESS_TOKEN_PREFIX,
    AppAccessToken,
    InstallAccessToken,
    unseal_access_token,
)
from app.services.marketplace import app_oauth
from app.services.marketplace.app_refs import ensure_app_guild_ref
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


@pytest.mark.integration
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


@pytest.mark.integration
async def test_a_p256_key_authenticates_too(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    await install_app(session, acting_user, role_session, granted=["documents:read"])

    response = await _ask(client, assertion=_assertion(key="ec"))

    assert response.status_code == 200, response.text


# ---------------------------------------------------------------------------
# Installation tokens
# ---------------------------------------------------------------------------


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
async def test_an_unknown_installation_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    await install_app(session, acting_user, role_session, granted=["documents:read"])

    response = await _ask(client, installation="not-a-reference")

    assert response.status_code == 400
    assert _error(response) == "invalid_grant"


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
async def test_a_disabled_registration_is_an_invalid_client(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    await install_app(
        session, acting_user, role_session, granted=["documents:read"], enabled=False
    )

    response = await _ask(client)

    assert response.status_code == 401
    assert _error(response) == "invalid_client"


@pytest.mark.integration
async def test_no_assertion_is_an_invalid_client(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    await install_app(session, acting_user, role_session, granted=["documents:read"])

    response = await client.post(TOKEN_URL, data={"grant_type": "client_credentials"})

    assert response.status_code == 401
    assert _error(response) == "invalid_client"


@pytest.mark.integration
async def test_a_json_body_is_an_invalid_request(client: AsyncClient):
    response = await client.post(TOKEN_URL, json={"grant_type": "client_credentials"})

    assert response.status_code == 400
    assert _error(response) == "invalid_request"


# ---------------------------------------------------------------------------
# The app's installs
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_an_app_token_lists_the_installs(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_app(
        session,
        acting_user,
        role_session,
        granted=["documents:write", "comments:read"],
    )
    app_token = (await _ask(client)).json()["access_token"]

    response = await client.get(
        INSTALLATIONS_URL, headers={"Authorization": f"Bearer {app_token}"}
    )

    assert response.status_code == 200, response.text
    assert response.json() == [
        {
            "installation": await _installation(installed),
            "scopes": ["comments:read", "documents:write"],
            "initiatives": [installed.placed.id],
        }
    ]


@pytest.mark.integration
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
