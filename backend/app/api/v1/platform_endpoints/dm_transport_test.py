"""The transport endpoints: keys in, ciphertext through, nothing kept.

The assertions worth keeping are about what the server *cannot* do and what a
sender *cannot* learn: that a stranger gets no keys, that an ignored sender is
answered exactly like an un-ignored one while nothing arrives, and that a
collected message stops existing.
"""

import base64

import pytest
from sqlalchemy import text

from app.models.platform.user_dm_settings import DmPolicy
from app.models.platform.user_ignore import UserIgnore

pytestmark = pytest.mark.asyncio


def _key(seed: int) -> str:
    """One public key, written the way the ratchet writes it: no padding."""
    return base64.b64encode(bytes([seed % 251]) * 32).decode().rstrip("=")


def _registration(seed: int = 1) -> dict:
    return {
        "identity_key": _key(seed),
        "fingerprint_key": _key(seed + 1),
        "fallback_key": {"key_id": "fb", "public_key": _key(seed + 2)},
        "one_time_keys": [{"key_id": "otk-1", "public_key": _key(seed + 3)}],
    }


async def _set_policy(session, user, policy: DmPolicy) -> None:
    await session.exec(
        text(
            "UPDATE public.user_dm_settings SET dm_policy = CAST(:p AS user_dm_policy) "
            "WHERE user_id = :u"
        ).bindparams(p=policy.value, u=user.id)
    )
    await session.commit()


async def _open_channel(session, a, b) -> None:
    """The accepted message grant a request earns, applied directly."""
    low, high = (a.id, b.id) if a.id < b.id else (b.id, a.id)
    await session.exec(
        text(
            "INSERT INTO public.contact_grants "
            "(user_id_low, user_id_high, kind, state, requested_by, created_at) "
            "VALUES (:lo, :hi, 'message', 'accepted', :by, now()) "
            "ON CONFLICT DO NOTHING"
        ).bindparams(lo=low, hi=high, by=a.id)
    )
    await session.commit()


async def _register(client, actor, seed=1, user_agent="Firefox on Linux") -> str:
    response = await client.post(
        "/api/v1/me/dm/devices",
        json=_registration(seed),
        headers={**actor.headers, "user-agent": user_agent},
    )
    assert response.status_code == 201, response.text
    # Newest last: the list is ordered by creation, and a second registration
    # must return the device it just made rather than the first one.
    return response.json()["devices"][-1]["id"]


# ------------------------------------------------------------------ devices ---


async def test_a_device_publishes_only_public_keys(client, acting_user):
    a = await acting_user()

    device_id = await _register(client, a)
    listed = await client.get("/api/v1/me/dm/devices", headers=a.headers)

    body = listed.json()["devices"][0]
    assert body["id"] == device_id
    # Named by what connected, not by what the client asked to be called.
    assert body["label"] == "Firefox on Linux"
    assert body["one_time_key_count"] == 1
    # The account's own public keys, which is what it needs to recognise a
    # message arriving from another of its own clients. Both are public halves;
    # nothing here could open anything.
    assert body["identity_key"]
    assert body["fingerprint_key"]


async def test_a_malformed_key_is_refused(client, acting_user):
    a = await acting_user()
    payload = _registration()
    payload["identity_key"] = "not-base64!!"

    response = await client.post(
        "/api/v1/me/dm/devices", json=payload, headers=a.headers
    )
    assert response.status_code == 422


async def test_a_payload_is_handed_back_the_way_the_ratchet_reads_it(
    client, acting_user
):
    """The ciphertext decoder on the client keeps its padding, so the server
    must too -- a value whose length is not a multiple of three comes back
    unreadable otherwise, which is two messages in every three."""
    a = await acting_user()
    payload = _registration()
    payload["identity_key"] = base64.b64encode(b"\x01" * 32).decode()

    response = await client.post(
        "/api/v1/me/dm/devices", json=payload, headers=a.headers
    )
    assert response.status_code == 201
    assert (
        response.json()["devices"][0]["identity_key"]
        == base64.b64encode(b"\x01" * 32).decode()
    )


async def test_padded_keys_are_accepted_too(client, acting_user):
    """The ratchet omits the padding; a client that sends it is not refused."""
    a = await acting_user()
    payload = _registration()
    payload["identity_key"] = base64.b64encode(b"\x01" * 32).decode()

    response = await client.post(
        "/api/v1/me/dm/devices", json=payload, headers=a.headers
    )
    assert response.status_code == 201


async def test_a_fallback_key_may_reuse_a_prekey_id(client, acting_user):
    """Fallback keys are numbered in their own sequence on the client, so the
    same id string can arrive on both -- registration must not collide."""
    a = await acting_user()
    payload = _registration()
    payload["fallback_key"]["key_id"] = "AAAAAAAAAAA"
    payload["one_time_keys"][0]["key_id"] = "AAAAAAAAAAA"

    response = await client.post(
        "/api/v1/me/dm/devices", json=payload, headers=a.headers
    )
    assert response.status_code == 201


async def test_a_short_key_is_refused(client, acting_user):
    a = await acting_user()
    payload = _registration()
    payload["identity_key"] = base64.b64encode(b"tooshort").decode()

    response = await client.post(
        "/api/v1/me/dm/devices", json=payload, headers=a.headers
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "DM_MALFORMED_KEY"


async def test_removing_a_device_takes_its_queue_with_it(client, session, acting_user):
    a = await acting_user()
    b = await acting_user()
    await _set_policy(session, a.user, DmPolicy.public)
    await _set_policy(session, b.user, DmPolicy.public)
    await _open_channel(session, a.user, b.user)
    b_device = await _register(client, b, seed=20)
    await _register(client, a, seed=1)

    conversation = await client.post(
        "/api/v1/me/dm/conversations",
        json={"user_id": b.user.id},
        headers=a.headers,
    )
    conversation_id = conversation.json()["id"]
    await client.post(
        f"/api/v1/me/dm/conversations/{conversation_id}/messages",
        json={
            "messages": [
                {
                    "recipient_device_id": b_device,
                    "message_type": 0,
                    "payload": base64.b64encode(b"ciphertext").decode(),
                }
            ]
        },
        headers=a.headers,
    )

    removed = await client.delete(
        f"/api/v1/me/dm/devices/{b_device}", headers=b.headers
    )
    assert removed.status_code == 204
    remaining = (
        await session.exec(text("SELECT count(*) FROM public.dm_queue"))
    ).scalar_one()
    assert remaining == 0


# ---------------------------------------------------------------- directory ---


async def test_a_stranger_gets_no_session_keys(client, session, acting_user):
    a = await acting_user()
    b = await acting_user()
    await _register(client, b, seed=30)

    response = await client.post(
        f"/api/v1/users/{b.user.id}/dm/session-keys", headers=a.headers
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "DM_NOT_REACHABLE"


async def test_claiming_spends_a_prekey_but_never_the_fallback(
    client, session, acting_user
):
    a = await acting_user()
    b = await acting_user()
    await _set_policy(session, a.user, DmPolicy.public)
    await _set_policy(session, b.user, DmPolicy.public)
    await _open_channel(session, a.user, b.user)
    await _register(client, b, seed=40)

    first = await client.post(
        f"/api/v1/users/{b.user.id}/dm/session-keys", headers=a.headers
    )
    assert first.status_code == 200, first.text
    assert first.json()["devices"][0]["one_time_key"]["key_id"] == "otk-1"

    # The pool is empty now, so the reusable last-resort key answers instead of
    # the account becoming unreachable.
    second = await client.post(
        f"/api/v1/users/{b.user.id}/dm/session-keys", headers=a.headers
    )
    assert second.json()["devices"][0]["one_time_key"]["key_id"] == "fb"


# ------------------------------------------------------------ conversations ---


async def test_a_conversation_needs_an_accepted_grant(client, session, acting_user):
    a = await acting_user()
    b = await acting_user()
    await _set_policy(session, a.user, DmPolicy.public)
    await _set_policy(session, b.user, DmPolicy.public)

    response = await client.post(
        "/api/v1/me/dm/conversations",
        json={"user_id": b.user.id},
        headers=a.headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "DM_NOT_REACHABLE"


async def test_asking_twice_returns_the_same_channel(client, session, acting_user):
    a = await acting_user()
    b = await acting_user()
    await _set_policy(session, a.user, DmPolicy.public)
    await _set_policy(session, b.user, DmPolicy.public)
    await _open_channel(session, a.user, b.user)

    first = await client.post(
        "/api/v1/me/dm/conversations", json={"user_id": b.user.id}, headers=a.headers
    )
    second = await client.post(
        "/api/v1/me/dm/conversations", json={"user_id": b.user.id}, headers=a.headers
    )
    assert first.json()["id"] == second.json()["id"]


async def test_a_third_account_cannot_see_the_conversation(
    client, session, acting_user
):
    a = await acting_user()
    b = await acting_user()
    carol = await acting_user()
    await _set_policy(session, a.user, DmPolicy.public)
    await _set_policy(session, b.user, DmPolicy.public)
    await _open_channel(session, a.user, b.user)
    await client.post(
        "/api/v1/me/dm/conversations", json={"user_id": b.user.id}, headers=a.headers
    )

    listed = await client.get("/api/v1/me/dm/conversations", headers=carol.headers)
    assert listed.json()["conversations"] == []


# ------------------------------------------------------------------- queue ---


async def _conversation_with_devices(client, session, a, b):
    await _set_policy(session, a.user, DmPolicy.public)
    await _set_policy(session, b.user, DmPolicy.public)
    await _open_channel(session, a.user, b.user)
    a_device = await _register(client, a, seed=1)
    b_device = await _register(client, b, seed=60)
    created = await client.post(
        "/api/v1/me/dm/conversations", json={"user_id": b.user.id}, headers=a.headers
    )
    return created.json()["id"], a_device, b_device


async def test_a_message_reaches_the_recipient_and_the_senders_own_device(
    client, session, acting_user
):
    a = await acting_user()
    b = await acting_user()
    conversation_id, a_device, b_device = await _conversation_with_devices(
        client, session, a, b
    )

    sent = await client.post(
        f"/api/v1/me/dm/conversations/{conversation_id}/messages",
        json={
            "messages": [
                {
                    "recipient_device_id": b_device,
                    "message_type": 0,
                    "payload": base64.b64encode(b"for-bob").decode(),
                },
                {
                    "recipient_device_id": a_device,
                    "message_type": 0,
                    "payload": base64.b64encode(b"for-my-other-tab").decode(),
                },
            ]
        },
        headers=a.headers,
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["accepted"] == 2

    collected = await client.get(
        f"/api/v1/me/dm/queue?device_id={b_device}", headers=b.headers
    )
    items = collected.json()["items"]
    assert len(items) == 1
    assert base64.b64decode(items[0]["payload"]) == b"for-bob"


async def test_an_ignored_sender_is_answered_the_same_and_reaches_nobody(
    client, session, acting_user
):
    """The whole point of the ignore, on the wire.

    The send succeeds, the response is identical, and nothing lands in the
    recipient's queue.
    """
    a = await acting_user()
    b = await acting_user()
    conversation_id, a_device, b_device = await _conversation_with_devices(
        client, session, a, b
    )
    session.add(UserIgnore(user_id=b.user.id, ignored_user_id=a.user.id))
    await session.commit()

    sent = await client.post(
        f"/api/v1/me/dm/conversations/{conversation_id}/messages",
        json={
            "messages": [
                {
                    "recipient_device_id": b_device,
                    "message_type": 0,
                    "payload": base64.b64encode(b"unheard").decode(),
                },
                {
                    "recipient_device_id": a_device,
                    "message_type": 0,
                    "payload": base64.b64encode(b"my own copy").decode(),
                },
            ]
        },
        headers=a.headers,
    )
    assert sent.status_code == 200, sent.text

    collected = await client.get(
        f"/api/v1/me/dm/queue?device_id={b_device}", headers=b.headers
    )
    assert collected.json()["items"] == []
    # The sender's own outbox copy still lands, so their other tabs render it.
    own = await client.get(
        f"/api/v1/me/dm/queue?device_id={a_device}", headers=a.headers
    )
    assert len(own.json()["items"]) == 1


async def test_collecting_then_acknowledging_removes_the_row(
    client, session, acting_user
):
    a = await acting_user()
    b = await acting_user()
    conversation_id, _a_device, b_device = await _conversation_with_devices(
        client, session, a, b
    )
    await client.post(
        f"/api/v1/me/dm/conversations/{conversation_id}/messages",
        json={
            "messages": [
                {
                    "recipient_device_id": b_device,
                    "message_type": 0,
                    "payload": base64.b64encode(b"collect me").decode(),
                }
            ]
        },
        headers=a.headers,
    )
    collected = await client.get(
        f"/api/v1/me/dm/queue?device_id={b_device}", headers=b.headers
    )
    message_id = collected.json()["items"][0]["id"]

    acked = await client.post(
        "/api/v1/me/dm/queue/ack",
        json={"device_id": b_device, "message_ids": [message_id]},
        headers=b.headers,
    )
    assert acked.status_code == 204

    remaining = (
        await session.exec(text("SELECT count(*) FROM public.dm_queue"))
    ).scalar_one()
    assert remaining == 0


async def test_a_queue_belongs_to_its_device(client, session, acting_user):
    a = await acting_user()
    b = await acting_user()
    _conversation_id, _a_device, b_device = await _conversation_with_devices(
        client, session, a, b
    )

    response = await client.get(
        f"/api/v1/me/dm/queue?device_id={b_device}", headers=a.headers
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "DM_DEVICE_NOT_FOUND"


async def test_messaging_yourself_is_refused(client, acting_user):
    a = await acting_user()

    response = await client.post(
        "/api/v1/me/dm/conversations", json={"user_id": a.user.id}, headers=a.headers
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "DM_CANNOT_MESSAGE_SELF"


# ------------------------------------------------------- own devices ---


async def test_the_directory_hands_over_keys_without_claiming_one(
    client, session, acting_user
):
    """The route an inbound pre-key message is answered with.

    It reads; it must not spend. Reading it to decrypt somebody's message would
    otherwise cost a prekey per collection.
    """
    a = await acting_user()
    b = await acting_user()
    await _set_policy(session, a.user, DmPolicy.public)
    await _set_policy(session, b.user, DmPolicy.public)
    await _open_channel(session, a.user, b.user)
    await _register(client, b, seed=90)

    response = await client.get(
        f"/api/v1/users/{b.user.id}/dm/devices", headers=a.headers
    )
    assert response.status_code == 200, response.text
    device = response.json()["devices"][0]
    assert device["identity_key"]
    assert device["one_time_key"] is None

    remaining = (
        await session.exec(
            text("SELECT count(*) FROM public.dm_one_time_keys WHERE fallback IS FALSE")
        )
    ).scalar_one()
    assert remaining == 1


async def test_a_stranger_reads_no_directory(client, session, acting_user):
    a = await acting_user()
    b = await acting_user()
    await _register(client, b, seed=91)

    response = await client.get(
        f"/api/v1/users/{b.user.id}/dm/devices", headers=a.headers
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "DM_NOT_REACHABLE"


async def test_own_session_keys_skip_the_asking_device(client, acting_user):
    a = await acting_user()
    first = await _register(client, a, seed=92)
    second = await _register(client, a, seed=93)

    response = await client.post(
        "/api/v1/me/dm/session-keys", json={"device_id": first}, headers=a.headers
    )
    assert response.status_code == 200, response.text
    devices = response.json()["devices"]
    assert [device["device_id"] for device in devices] == [second]
    # A device of your own is a separate ratchet, so it costs a prekey like
    # anybody else's.
    assert devices[0]["one_time_key"]["key_id"] == "otk-1"


async def test_a_message_reaches_the_senders_other_device(client, session, acting_user):
    """The outbox, which is what makes a second client usable at all."""
    a = await acting_user()
    b = await acting_user()
    await _set_policy(session, a.user, DmPolicy.public)
    await _set_policy(session, b.user, DmPolicy.public)
    await _open_channel(session, a.user, b.user)
    a_laptop = await _register(client, a, seed=94)
    a_phone = await _register(client, a, seed=95)
    b_device = await _register(client, b, seed=96)

    created = await client.post(
        "/api/v1/me/dm/conversations", json={"user_id": b.user.id}, headers=a.headers
    )
    conversation_id = created.json()["id"]

    keys = await client.post(
        "/api/v1/me/dm/session-keys", json={"device_id": a_laptop}, headers=a.headers
    )
    targets = [device["device_id"] for device in keys.json()["devices"]]
    assert a_phone in targets

    await client.post(
        f"/api/v1/me/dm/conversations/{conversation_id}/messages",
        json={
            "messages": [
                {
                    "recipient_device_id": device,
                    "message_type": 0,
                    "payload": base64.b64encode(b"outbox").decode(),
                }
                for device in [b_device, a_phone]
            ]
        },
        headers=a.headers,
    )

    waiting = await client.get(
        f"/api/v1/me/dm/queue?device_id={a_phone}", headers=a.headers
    )
    assert len(waiting.json()["items"]) == 1
