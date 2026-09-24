"""The dependency a route names to admit an installed app.

A probe route is mounted for these tests that names ``documents:read`` with
:func:`app_scope` and reads documents through :data:`ActorSessionDep`. No real
route opts in yet, so the probe is what exercises the marker end to end: an
installation token is verified, routed through the install seam and held to
the route's scope; a person passes through the ordinary seam unchanged; and a
route that names no scope refuses the token before anything is read.
"""

from __future__ import annotations

import time
from typing import Annotated, Any

import pytest
from fastapi import APIRouter, Depends
from sqlalchemy import event
from sqlmodel import select
from starlette.requests import Request

from app.api.actor_route import ActorRoute
from app.api.deps import (
    APP_SCOPE_ATTRIBUTE,
    ActorContext,
    ActorSessionDep,
    app_scope,
    route_app_scope,
)
from app.core.app_access_token import seal_app_token, seal_install_token
from app.core.identity_boundary import boundary_scope
from app.core.messages import AppMessages, AuthMessages
from app.db.guild_standing import GuildContext, InstallContext
from app.main import app
from app.models.platform.guild import GuildRole
from app.models.tenant.document import Document
from app.testing import create_document
from app.testing.app_clients import CLIENT, install_app, share_with_members

_PROBE_PATH = "/api/v1/g/{guild_id}/app-scope-probe/documents"
_read_documents = app_scope("documents:read")

_probe = APIRouter(route_class=ActorRoute)


@_probe.get(_PROBE_PATH)
async def _probe_documents(
    actor: Annotated[ActorContext, Depends(_read_documents)],
    session: ActorSessionDep,
) -> dict[str, Any]:
    names = sorted((await session.exec(select(Document.name))).all())
    return {
        "actor": "install" if isinstance(actor, InstallContext) else "person",
        "documents": names,
    }


@pytest.fixture(autouse=True)
def _mounted():
    """Put the probe ahead of the SPA's catch-all, and take it away after."""
    routes = list(_probe.routes)
    app.router.routes[0:0] = routes
    try:
        yield
    finally:
        for route in routes:
            app.router.routes.remove(route)


def _url(guild_id: int) -> str:
    return _PROBE_PATH.format(guild_id=guild_id)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _install_token(installed, scopes, **overrides) -> str:
    token, _exp = seal_install_token(
        guild_id=overrides.pop("guild_id", installed.guild.id),
        install_id=installed.app.id,
        client_id=CLIENT,
        scopes=frozenset(scopes),
        initiative_id=None,
        **overrides,
    )
    return token


async def _with_shared_document(session, installed):
    document = await create_document(
        session, installed.placed, installed.seat.user, name="Shared"
    )
    await share_with_members(session, document, installed.placed.id)
    await create_document(
        session, installed.placed, installed.seat.user, name="Private"
    )


# ---------------------------------------------------------------------------
# The marker
# ---------------------------------------------------------------------------


def test_the_dependency_carries_its_scope():
    assert getattr(_read_documents, APP_SCOPE_ATTRIBUTE) == "documents:read"
    (route,) = _probe.routes
    assert route_app_scope(route) == "documents:read"


def test_an_unknown_scope_fails_where_the_route_is_written():
    with pytest.raises(ValueError):
        app_scope("documents:admin")


# ---------------------------------------------------------------------------
# An installed app
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_an_installation_token_reads_through_the_routed_session(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    await _with_shared_document(session, installed)

    response = await client.get(
        _url(installed.guild.id),
        headers=_bearer(_install_token(installed, ["documents:read"])),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"actor": "install", "documents": ["Shared"]}


@pytest.mark.integration
async def test_the_guild_comes_from_the_token_not_the_path(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    await _with_shared_document(session, installed)

    response = await client.get(
        _url(installed.guild.id + 100_000),
        headers=_bearer(_install_token(installed, ["documents:read"])),
    )

    assert response.status_code == 200, response.text
    assert response.json()["documents"] == ["Shared"]


@pytest.mark.integration
async def test_write_covers_read(client, session, acting_user, role_session):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:write"]
    )
    await _with_shared_document(session, installed)

    response = await client.get(
        _url(installed.guild.id),
        headers=_bearer(_install_token(installed, ["documents:write"])),
    )

    assert response.status_code == 200, response.text


@pytest.mark.integration
async def test_a_token_without_the_scope_is_forbidden(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session,
        acting_user,
        role_session,
        granted=["documents:read", "comments:read"],
    )

    response = await client.get(
        _url(installed.guild.id),
        headers=_bearer(_install_token(installed, ["comments:read"])),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == AppMessages.SCOPE_REQUIRED


@pytest.mark.integration
@pytest.mark.parametrize("shape", ["tampered", "expired", "app-token", "not-live"])
async def test_a_token_that_is_not_a_live_install_is_unauthorized(
    client, session, acting_user, role_session, shape
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    if shape == "tampered":
        good = _install_token(installed, ["documents:read"])
        flipped = "A" if good[-5] != "A" else "B"
        token = good[:-5] + flipped + good[-4:]
    elif shape == "expired":
        token = _install_token(installed, ["documents:read"], now=time.time() - 700)
    elif shape == "app-token":
        token, _exp = seal_app_token(client_id=CLIENT)
    else:
        # Sealed correctly, for a community the install is not in.
        token = _install_token(
            installed, ["documents:read"], guild_id=installed.guild.id + 100_000
        )

    response = await client.get(_url(installed.guild.id), headers=_bearer(token))

    assert response.status_code == 401
    assert response.json()["detail"] == AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS


# ---------------------------------------------------------------------------
# A person
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_person_passes_through_unchanged(client, session, acting_user):
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    await create_document(session, a.initiative, a.user, name="Mine")

    response = await client.get(_url(a.guild.id), headers=a.headers)

    assert response.status_code == 200, response.text
    assert response.json() == {"actor": "person", "documents": ["Mine"]}


@pytest.mark.integration
async def test_a_person_route_refuses_an_installation_token(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )

    response = await client.get(
        "/api/v1/users/me",
        headers=_bearer(_install_token(installed, ["documents:read"])),
    )

    assert response.status_code == 401
    assert response.json()["detail"] == AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS


# ---------------------------------------------------------------------------
# Round trips
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_an_install_request_spends_two_statements_before_its_handler(
    session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    token = _install_token(installed, ["documents:read"])
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": _url(installed.guild.id),
            "query_string": b"",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
            "client": ("198.51.100.7", 40404),
        }
    )

    s = await role_session("app_user")
    await s.connection()
    statements: list[str] = []

    def count(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    engine = s.bind.sync_engine
    event.listen(engine, "before_cursor_execute", count)
    try:
        # The slot ActorRoute opens for every request it serves.
        with boundary_scope():
            # ``person`` is what ``get_actor_user`` answers for an access token.
            context = await _read_documents(
                request, s, installed.guild.id, person=None, bearer_token=token
            )
    finally:
        event.remove(engine, "before_cursor_execute", count)

    assert isinstance(context, InstallContext)
    assert not isinstance(context, GuildContext)
    assert len(statements) == 2, statements
    assert request.state.app_install == (CLIENT, installed.guild.id, installed.app.id)
    await s.rollback()
