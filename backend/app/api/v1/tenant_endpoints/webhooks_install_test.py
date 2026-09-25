"""The webhook subscription routes an installed app calls.

An install registers subscriptions as its community, naming no person. Each
event type it names needs the read scope of its tool, a token narrowed to one
initiative registers for that initiative only, and a community-wide
subscription needs a token that is not narrowed. It sees and removes only the
subscriptions it registered.
"""

from __future__ import annotations

import socket
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

from sqlmodel import select

from app.core.audit_events import AuditEventType
from app.core.messages import AppMessages, WebhookSubscriptionMessages
from app.models.tenant.webhook_subscription import WebhookSubscription
from app.services.marketplace import app_refs
from app.testing import create_guild_app, emitted, route_session_to_guild
from app.testing.app_clients import (
    CLIENT,
    assert_names_nobody,
    install_app,
    install_headers,
    lift_person_and_guild_ids,
)


_WEBHOOK_HOST = "hooks.example.com"
_FAKE_INFOS = [
    (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 0))
]


@contextmanager
def _mock_public_dns():
    """Resolve the webhook host to a fixed public address, and pass every other
    lookup through to the real resolver."""
    real_getaddrinfo = socket.getaddrinfo

    def fake(host, *args, **kwargs):
        if host == _WEBHOOK_HOST:
            return _FAKE_INFOS
        return real_getaddrinfo(host, *args, **kwargs)

    with patch("app.services.webhook_target_url.socket.getaddrinfo", side_effect=fake):
        yield


def _url(guild_id: int, suffix: str = "") -> str:
    return f"/api/v1/c/{guild_id}/webhooks/subscriptions{suffix}"


def _body(**overrides: Any) -> dict:
    return {
        "target_url": f"https://{_WEBHOOK_HOST}/in",
        "event_types": ["documents.created"],
        **overrides,
    }


async def _subscribe(client: Any, installed: Any, headers: dict, **body: Any) -> Any:
    with _mock_public_dns():
        return await client.post(
            _url(installed.guild.id), headers=headers, json=_body(**body)
        )


async def _row(session: Any, guild_id: int, subscription_id: int) -> Any:
    await route_session_to_guild(session, guild_id)
    return (
        await session.exec(
            select(WebhookSubscription).where(WebhookSubscription.id == subscription_id)
        )
    ).one_or_none()


# ---------------------------------------------------------------------------
# Registering
# ---------------------------------------------------------------------------


async def test_an_install_subscribes_to_what_its_scopes_read(
    client, session, acting_user, role_session, capfd
):
    await lift_person_and_guild_ids(session)
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    headers = install_headers(installed, ["documents:read"])
    capfd.readouterr()

    response = await _subscribe(
        client,
        installed,
        headers,
        initiative_id=installed.placed.id,
        event_types=["documents.created", "documents.updated"],
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert isinstance(body["guild_ref"], str)
    assert body["created_by_ref"] is None
    assert body["hmac_secret"]
    assert_names_nobody(response.text, [installed.seat.user.id, installed.guild.id])
    # The same name every other response to this install gives its community.
    assert body["guild_ref"] == await app_refs.ensure_app_guild_ref(
        guild_id=installed.guild.id, app_install_id=installed.app.id
    )

    row = await _row(session, installed.guild.id, body["id"])
    assert row.app_install_id == installed.app.id
    assert row.created_by is None
    assert row.initiative_id == installed.placed.id

    (line,) = emitted(capfd, AuditEventType.WEBHOOK_CREATED)
    assert line["actor_user_id"] is None
    assert line["detail"]["app_install_id"] == installed.app.id
    assert line["context"]["app"] == CLIENT
    assert line["context"]["install_id"] == installed.app.id


async def test_an_install_is_refused_events_its_scopes_do_not_read(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    # The token asks for more than the seat granted; the grant is what holds.
    headers = install_headers(installed, ["documents:read", "projects:read"])

    for event_types in (["tasks.created"], ["documents.created", "tasks.updated"]):
        response = await _subscribe(
            client,
            installed,
            headers,
            initiative_id=installed.placed.id,
            event_types=event_types,
        )
        assert response.status_code == 403, (event_types, response.text)
        assert response.json()["detail"] == AppMessages.SCOPE_REQUIRED

    await route_session_to_guild(session, installed.guild.id)
    assert (await session.exec(select(WebhookSubscription))).all() == []


async def test_a_token_hears_only_the_scopes_it_carries(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session,
        acting_user,
        role_session,
        granted=["documents:read", "projects:read"],
    )

    left_out = await _subscribe(
        client,
        installed,
        install_headers(installed, ["documents:read"]),
        initiative_id=installed.placed.id,
        event_types=["tasks.created"],
    )
    assert left_out.status_code == 403, left_out.text

    carried = await _subscribe(
        client,
        installed,
        install_headers(installed, ["documents:read", "projects:read"]),
        initiative_id=installed.placed.id,
        event_types=["tasks.created", "documents.created"],
    )
    assert carried.status_code == 201, carried.text


async def test_an_install_subscribes_only_where_it_is_placed(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    response = await _subscribe(
        client,
        installed,
        install_headers(installed, ["documents:read"]),
        initiative_id=installed.unplaced.id,
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == AppMessages.SCOPE_REQUIRED


async def test_a_narrowed_token_subscribes_to_its_initiative_only(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    narrowed = install_headers(
        installed, ["documents:read"], initiative_id=installed.placed.id
    )

    community_wide = await _subscribe(client, installed, narrowed)
    assert community_wide.status_code == 403, community_wide.text
    assert community_wide.json()["detail"] == AppMessages.SCOPE_REQUIRED

    own = await _subscribe(
        client, installed, narrowed, initiative_id=installed.placed.id
    )
    assert own.status_code == 201, own.text

    # The same community-wide request on a token that is not narrowed.
    wide = await _subscribe(
        client, installed, install_headers(installed, ["documents:read"])
    )
    assert wide.status_code == 201, wide.text
    assert wide.json()["initiative_id"] is None


async def test_an_unknown_event_type_is_still_a_400(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    response = await _subscribe(
        client,
        installed,
        install_headers(installed, ["documents:read"]),
        initiative_id=installed.placed.id,
        event_types=["documents.renamed"],
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == WebhookSubscriptionMessages.UNKNOWN_EVENT_TYPE


async def test_listing_and_rewriting_stay_with_people(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    headers = install_headers(installed, ["documents:read"])
    created = await _subscribe(
        client, installed, headers, initiative_id=installed.placed.id
    )
    assert created.status_code == 201, created.text

    listed = await client.get(_url(installed.guild.id), headers=headers)
    assert listed.status_code == 401, listed.text
    patched = await client.patch(
        _url(installed.guild.id, f"/{created.json()['id']}"),
        headers=headers,
        json={"active": False},
    )
    assert patched.status_code == 401, patched.text


# ---------------------------------------------------------------------------
# Removing
# ---------------------------------------------------------------------------


async def test_an_install_removes_its_own_subscription(
    client, session, acting_user, role_session, capfd
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    headers = install_headers(installed, ["documents:read"])
    created = await _subscribe(
        client, installed, headers, initiative_id=installed.placed.id
    )
    assert created.status_code == 201, created.text
    subscription_id = created.json()["id"]
    capfd.readouterr()

    response = await client.delete(
        _url(installed.guild.id, f"/{subscription_id}"), headers=headers
    )

    assert response.status_code == 204, response.text
    assert await _row(session, installed.guild.id, subscription_id) is None
    (line,) = emitted(capfd, AuditEventType.WEBHOOK_DELETED)
    assert line["actor_user_id"] is None
    assert line["detail"]["app_install_id"] == installed.app.id
    assert line["context"]["app"] == CLIENT
    assert line["context"]["install_id"] == installed.app.id


async def test_an_install_cannot_remove_what_it_did_not_register(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    guild_id = installed.guild.id

    # A person's, registered through the ordinary route.
    with _mock_public_dns():
        person = await client.post(
            _url(guild_id),
            headers=installed.seat.headers,
            json=_body(initiative_id=installed.placed.id),
        )
    assert person.status_code == 201, person.text
    assert person.json()["created_by_ref"] is not None

    # Another install's, in the same initiative.
    other = await create_guild_app(
        session,
        installed.guild,
        installed.seat.user,
        definition={
            "app_kind": "service",
            "service": {"public_id": "tests.token-client-two", "protocol": 1},
        },
        listing_uid="TOKENCLIENT002",
    )
    await route_session_to_guild(session, guild_id)
    theirs = WebhookSubscription(
        initiative_id=installed.placed.id,
        created_by=None,
        app_install_id=other.id,
        target_url=f"https://{_WEBHOOK_HOST}/other",
        hmac_secret="x" * 64,
        event_types=["documents.created"],
        active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(theirs)
    await session.commit()
    await session.refresh(theirs)

    headers = install_headers(installed, ["documents:read"])
    for subscription_id in (person.json()["id"], theirs.id):
        response = await client.delete(
            _url(guild_id, f"/{subscription_id}"), headers=headers
        )
        assert response.status_code == 404, response.text
        assert response.json()["detail"] == WebhookSubscriptionMessages.NOT_FOUND
        assert await _row(session, guild_id, subscription_id) is not None


async def test_an_install_removes_its_subscription_after_losing_the_scope(
    client, session, acting_user, role_session
):
    """Removing asks no scope of the install: it reaches only its own rows, and
    taking one away narrows what it hears."""
    installed = await install_app(
        session,
        acting_user,
        role_session,
        granted=["documents:read", "comments:read"],
    )
    created = await _subscribe(
        client,
        installed,
        install_headers(installed, ["documents:read"]),
        initiative_id=installed.placed.id,
    )
    assert created.status_code == 201, created.text

    response = await client.delete(
        _url(installed.guild.id, f"/{created.json()['id']}"),
        headers=install_headers(installed, ["comments:read"]),
    )
    assert response.status_code == 204, response.text
