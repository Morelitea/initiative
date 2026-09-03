"""The DM settings, ignore list and permission endpoints.

The assertions worth keeping are the ones about what an account *cannot* learn:
that the permission endpoint answers identically whether or not the target
ignores the caller, and that the ignore list never answers the other direction.
"""

import pytest
from sqlalchemy import text

from app.models.platform.guild import GuildRole
from app.models.platform.user_dm_settings import DmPolicy
from app.models.platform.user_ignore import UserIgnore
from app.testing import (
    create_guild,
    create_user,
)

pytestmark = pytest.mark.asyncio


async def _set_policy(session, user, policy: DmPolicy) -> None:
    await session.exec(
        text(
            "UPDATE public.user_dm_settings SET dm_policy = CAST(:p AS user_dm_policy) "
            "WHERE user_id = :u"
        ).bindparams(p=policy.value, u=user.id)
    )
    await session.commit()


# ------------------------------------------------------------- dm-settings ---


async def test_settings_come_back_with_every_community_switched_on(
    client, session, acting_user
):
    a = await acting_user(guild_role=GuildRole.member)

    response = await client.get("/api/v1/me/dm-settings", headers=a.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dm_policy"] == "private"
    assert [c["guild_id"] for c in body["communities"]] == [a.guild.id]
    assert body["communities"][0]["enabled"] is True


async def test_raising_the_policy_needs_an_age_answer(client, session, acting_user):
    a = await acting_user()
    a.user.age_confirmed_at = None
    session.add(a.user)
    await session.commit()

    response = await client.patch(
        "/api/v1/me/dm-settings", json={"dm_policy": "community"}, headers=a.headers
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "DM_AGE_CONFIRMATION_REQUIRED"


async def test_staying_private_needs_no_age_answer(client, session, acting_user):
    a = await acting_user()
    a.user.age_confirmed_at = None
    session.add(a.user)
    await session.commit()

    response = await client.patch(
        "/api/v1/me/dm-settings", json={"dm_policy": "private"}, headers=a.headers
    )
    assert response.status_code == 200, response.text


async def test_switching_a_community_off_and_on(client, session, acting_user):
    a = await acting_user(guild_role=GuildRole.member)
    guild = a.guild

    off = await client.patch(
        "/api/v1/me/dm-settings",
        json={"communities": [{"guild_id": guild.id, "enabled": False}]},
        headers=a.headers,
    )
    assert off.status_code == 200, off.text
    assert off.json()["communities"][0]["enabled"] is False

    on = await client.patch(
        "/api/v1/me/dm-settings",
        json={"communities": [{"guild_id": guild.id, "enabled": True}]},
        headers=a.headers,
    )
    assert on.json()["communities"][0]["enabled"] is True


async def test_a_community_you_are_not_in_is_refused(client, session, acting_user):
    a = await acting_user()
    other = await create_user(session)
    elsewhere = await create_guild(session, creator=other)
    await session.commit()

    response = await client.patch(
        "/api/v1/me/dm-settings",
        json={"communities": [{"guild_id": elsewhere.id, "enabled": False}]},
        headers=a.headers,
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "DM_NOT_A_MEMBER"


# ----------------------------------------------------------------- ignored ---


async def test_ignoring_is_idempotent_and_reversible(client, session, acting_user):
    a = await acting_user()
    target = await create_user(session)
    await session.commit()

    for _ in range(2):
        assert (
            await client.put(f"/api/v1/me/ignored/{target.id}", headers=a.headers)
        ).status_code == 204

    listing = await client.get("/api/v1/me/ignored", headers=a.headers)
    assert listing.status_code == 200
    assert [row["user_id"] for row in listing.json()["items"]] == [target.id]
    assert listing.json()["total"] == 1

    assert (
        await client.delete(f"/api/v1/me/ignored/{target.id}", headers=a.headers)
    ).status_code == 204
    assert (await client.get("/api/v1/me/ignored", headers=a.headers)).json()[
        "total"
    ] == 0


async def test_you_cannot_ignore_yourself(client, acting_user):
    a = await acting_user()
    response = await client.put(f"/api/v1/me/ignored/{a.user.id}", headers=a.headers)
    assert response.status_code == 422
    assert response.json()["detail"] == "DM_CANNOT_IGNORE_SELF"


async def test_the_list_never_answers_the_other_direction(client, session, acting_user):
    """Ada ignores Bram. Bram's own list is empty, and nothing tells him."""
    ada = await acting_user()
    bram = await acting_user()
    session.add(UserIgnore(user_id=ada.user.id, ignored_user_id=bram.user.id))
    await session.commit()

    mine = await client.get("/api/v1/me/ignored", headers=ada.headers)
    assert [r["user_id"] for r in mine.json()["items"]] == [bram.user.id]

    theirs = await client.get("/api/v1/me/ignored", headers=bram.headers)
    assert theirs.json() == {"items": [], "total": 0}


# -------------------------------------------------------------- permission ---


async def test_permission_is_identical_across_being_ignored(
    client, session, acting_user
):
    """The oracle guard, end to end: same body, same status, before and after."""
    ada = await acting_user(guild_role=GuildRole.member)
    bram = await acting_user(guild_role=GuildRole.member, guild=ada.guild)
    await _set_policy(session, ada.user, DmPolicy.community)
    await _set_policy(session, bram.user, DmPolicy.community)

    url = f"/api/v1/users/{ada.user.id}/dm-permission"
    before = await client.get(url, headers=bram.headers)
    assert before.status_code == 200
    assert before.json() == {"permission": "may_request"}

    session.add(UserIgnore(user_id=ada.user.id, ignored_user_id=bram.user.id))
    await session.commit()

    after = await client.get(url, headers=bram.headers)
    assert after.status_code == before.status_code
    assert after.json() == before.json()


async def test_a_private_target_is_denied(client, session, acting_user):
    ada = await acting_user(guild_role=GuildRole.member)
    bram = await acting_user(guild_role=GuildRole.member, guild=ada.guild)
    await _set_policy(session, ada.user, DmPolicy.private)
    await _set_policy(session, bram.user, DmPolicy.community)

    response = await client.get(
        f"/api/v1/users/{ada.user.id}/dm-permission", headers=bram.headers
    )
    assert response.json() == {"permission": "denied"}


async def test_an_unknown_account_is_not_found(client, acting_user):
    a = await acting_user()
    response = await client.get(
        "/api/v1/users/99999999/dm-permission", headers=a.headers
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "DM_USER_NOT_FOUND"


# ------------------------------------------------- connections & requests ---


async def _handle(session, user) -> dict:
    await session.refresh(user)
    return {"username": user.username, "discriminator": user.discriminator}


async def test_a_connection_is_addressed_by_handle(client, session, acting_user):
    a = await acting_user()
    b = await acting_user()

    response = await client.post(
        "/api/v1/me/connections", json=await _handle(session, b.user), headers=a.headers
    )
    assert response.status_code == 202, response.text
    assert response.json()["user_id"] == b.user.id
    assert response.json()["state"] == "pending"
    assert response.json()["outgoing"] is True

    incoming = await client.get("/api/v1/me/connections", headers=b.headers)
    assert [r["user_id"] for r in incoming.json()["incoming"]] == [a.user.id]


async def test_an_unknown_handle_answers_like_an_unreachable_one(
    client, session, acting_user
):
    """Both are a 409 with a code and nothing else, so the endpoint is not a
    way to sweep the discriminator space."""
    a = await acting_user()
    b = await acting_user()
    b.user.age_confirmed_at = None
    session.add(b.user)
    await session.commit()

    missing = await client.post(
        "/api/v1/me/connections",
        json={"username": "nobodyhere", "discriminator": 9999},
        headers=a.headers,
    )
    unreachable = await client.post(
        "/api/v1/me/connections", json=await _handle(session, b.user), headers=a.headers
    )
    # The whole response, not just the status: an earlier version matched on
    # 409 alone and let two different detail codes through, which is the
    # difference between "cannot connect" and "that account is here".
    assert missing.status_code == unreachable.status_code == 409
    assert missing.json() == unreachable.json()


async def test_accepting_a_connection_opens_the_channel(client, session, acting_user):
    a = await acting_user()
    b = await acting_user()

    await client.post(
        "/api/v1/me/connections", json=await _handle(session, b.user), headers=a.headers
    )
    accepted = await client.post(
        f"/api/v1/me/connections/{a.user.id}/accept", headers=b.headers
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["state"] == "accepted"

    channels = await client.get("/api/v1/me/message-requests", headers=a.headers)
    assert [r["user_id"] for r in channels.json()["accepted"]] == [b.user.id]

    permission = await client.get(
        f"/api/v1/users/{b.user.id}/dm-permission", headers=a.headers
    )
    assert permission.json() == {"permission": "open"}


async def test_a_request_from_an_ignored_account_is_never_surfaced(
    client, session, acting_user
):
    """Stored, and invisible to the person who is ignoring them."""
    ada = await acting_user()
    bram = await acting_user()
    await client.put(f"/api/v1/me/ignored/{bram.user.id}", headers=ada.headers)

    sent = await client.post(
        "/api/v1/me/connections",
        json=await _handle(session, ada.user),
        headers=bram.headers,
    )
    assert sent.status_code == 202, sent.text

    theirs = await client.get("/api/v1/me/connections", headers=ada.headers)
    assert theirs.json()["incoming"] == []

    # Bram sees his own outgoing request exactly as if it had landed.
    mine = await client.get("/api/v1/me/connections", headers=bram.headers)
    assert [r["user_id"] for r in mine.json()["outgoing"]] == [ada.user.id]


async def test_removing_a_connection_keeps_a_community_channel(
    client, session, acting_user
):
    ada = await acting_user(guild_role=GuildRole.member)
    bram = await acting_user(guild_role=GuildRole.member, guild=ada.guild)
    await _set_policy(session, ada.user, DmPolicy.community)
    await _set_policy(session, bram.user, DmPolicy.community)

    await client.post(
        "/api/v1/me/connections",
        json=await _handle(session, bram.user),
        headers=ada.headers,
    )
    await client.post(
        f"/api/v1/me/connections/{ada.user.id}/accept", headers=bram.headers
    )
    removed = await client.delete(
        f"/api/v1/me/connections/{bram.user.id}", headers=ada.headers
    )
    assert removed.status_code == 204

    permission = await client.get(
        f"/api/v1/users/{bram.user.id}/dm-permission", headers=ada.headers
    )
    assert permission.json() == {"permission": "open"}


async def test_ignoring_someone_does_not_stop_you_reaching_them(
    client, session, acting_user
):
    """Ignoring runs one way.

    Bram ignores Ada, then asks to connect. Ada sees it: what Bram switched off
    is Ada reaching *him*, not him reaching her. The mirror of
    ``test_a_request_from_an_ignored_account_is_never_surfaced``, and the pair
    of them is what pins the direction.
    """
    ada = await acting_user()
    bram = await acting_user()
    await client.put(f"/api/v1/me/ignored/{ada.user.id}", headers=bram.headers)

    sent = await client.post(
        "/api/v1/me/connections",
        json=await _handle(session, ada.user),
        headers=bram.headers,
    )
    assert sent.status_code == 202, sent.text

    theirs = await client.get("/api/v1/me/connections", headers=ada.headers)
    assert [r["user_id"] for r in theirs.json()["incoming"]] == [bram.user.id]
