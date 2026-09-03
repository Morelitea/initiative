"""The bell line a direct message produces.

One rolled-up line per (recipient, conversation) — the same shape reactions use.
The assertions worth keeping are that a flurry is one line rather than twenty,
that reading it makes the next message a *new* line, and that the line names the
sender and counts the messages without ever carrying one.
"""

import base64
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from app.api.v1.platform_endpoints.dm_transport_test import (
    _open_channel,
    _register,
    _set_policy,
)
from app.models.platform.user_dm_settings import DmPolicy
from app.models.platform.user_ignore import UserIgnore

pytestmark = pytest.mark.asyncio


async def _lines(session, user_id: int) -> list[dict]:
    rows = (
        await session.exec(
            text(
                "SELECT data, read_at FROM public.notifications "
                "WHERE user_id = :u AND type = 'direct_message' "
                "ORDER BY created_at"
            ).bindparams(u=user_id)
        )
    ).all()
    return [{"data": row[0], "read_at": row[1]} for row in rows]


async def _channel(client, session, a, b):
    await _set_policy(session, a.user, DmPolicy.public)
    await _set_policy(session, b.user, DmPolicy.public)
    await _open_channel(session, a.user, b.user)
    await _register(client, a, seed=1)
    b_device = await _register(client, b, seed=80)
    created = await client.post(
        "/api/v1/me/dm/conversations", json={"user_id": b.user.id}, headers=a.headers
    )
    return created.json()["id"], b_device


async def _send(client, actor, conversation_id, device_id, text_bytes=b"x"):
    return await client.post(
        f"/api/v1/me/dm/conversations/{conversation_id}/messages",
        json={
            "messages": [
                {
                    "recipient_device_id": device_id,
                    "message_type": 0,
                    "payload": base64.b64encode(text_bytes).decode(),
                }
            ]
        },
        headers=actor.headers,
    )


async def test_a_message_names_the_sender_and_counts_one(client, session, acting_user):
    a = await acting_user()
    b = await acting_user()
    conversation_id, b_device = await _channel(client, session, a, b)

    await _send(client, a, conversation_id, b_device)

    lines = await _lines(session, b.user.id)
    assert len(lines) == 1
    assert lines[0]["data"]["count"] == 1
    assert lines[0]["data"]["sender_id"] == a.user.id
    assert lines[0]["data"]["conversation_id"] == conversation_id
    # The line says who and how many. It never says what.
    assert "payload" not in lines[0]["data"]
    assert "body" not in lines[0]["data"]


async def test_a_flurry_is_one_line(client, session, acting_user):
    a = await acting_user()
    b = await acting_user()
    conversation_id, b_device = await _channel(client, session, a, b)

    for _ in range(4):
        await _send(client, a, conversation_id, b_device)

    lines = await _lines(session, b.user.id)
    assert len(lines) == 1
    assert lines[0]["data"]["count"] == 4


async def test_reading_the_line_makes_the_next_message_a_new_one(
    client, session, acting_user
):
    """Once read, "new" has to start meaning something again."""
    a = await acting_user()
    b = await acting_user()
    conversation_id, b_device = await _channel(client, session, a, b)
    await _send(client, a, conversation_id, b_device)

    await session.exec(
        text(
            "UPDATE public.notifications SET read_at = now() "
            "WHERE user_id = :u AND type = 'direct_message'"
        ).bindparams(u=b.user.id)
    )
    await session.commit()

    await _send(client, a, conversation_id, b_device)

    lines = await _lines(session, b.user.id)
    assert len(lines) == 2
    assert lines[1]["data"]["count"] == 1
    assert lines[1]["read_at"] is None


async def test_an_ignored_sender_produces_no_line(client, session, acting_user):
    a = await acting_user()
    b = await acting_user()
    conversation_id, b_device = await _channel(client, session, a, b)
    session.add(UserIgnore(user_id=b.user.id, ignored_user_id=a.user.id))
    await session.commit()

    sent = await _send(client, a, conversation_id, b_device)
    assert sent.status_code == 200, sent.text

    assert await _lines(session, b.user.id) == []


class TestChannels:
    """Both channels fire once per unread conversation, and neither carries the
    message."""

    async def test_email_names_the_sender_and_never_the_message(
        self, client, session, acting_user
    ):
        a = await acting_user()
        b = await acting_user()
        conversation_id, b_device = await _channel(client, session, a, b)

        with patch(
            "app.services.email.send_direct_message_email", new_callable=AsyncMock
        ) as send:
            await _send(client, a, conversation_id, b_device, b"a secret")

        assert send.await_count == 1
        kwargs = send.await_args.kwargs
        assert kwargs["sender_name"]
        assert kwargs["link"].endswith("/messages")
        # The whole call: a name and a link. Nothing that could carry a message.
        assert set(kwargs) == {"sender_name", "link"}
        assert b"a secret" not in repr(send.await_args).encode()

    async def test_a_flurry_is_one_email(self, client, session, acting_user):
        a = await acting_user()
        b = await acting_user()
        conversation_id, b_device = await _channel(client, session, a, b)

        with patch(
            "app.services.email.send_direct_message_email", new_callable=AsyncMock
        ) as send:
            for _ in range(4):
                await _send(client, a, conversation_id, b_device)

        assert send.await_count == 1

    async def test_turning_the_preference_off_stops_it(
        self, client, session, acting_user
    ):
        a = await acting_user()
        b = await acting_user()
        conversation_id, b_device = await _channel(client, session, a, b)
        await session.exec(
            text(
                "UPDATE public.users SET email_direct_messages = false WHERE id = :u"
            ).bindparams(u=b.user.id)
        )
        await session.commit()

        with patch(
            "app.services.email.send_direct_message_email", new_callable=AsyncMock
        ) as send:
            await _send(client, a, conversation_id, b_device)

        assert send.await_count == 0
