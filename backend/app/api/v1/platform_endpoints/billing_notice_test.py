"""``POST /api/v1/billing/community-notice``: billing asks for a fixed notice
to reach a community's owner.

Pinned: the same double envelope as the tier write (HMAC + one-shot RS256
jti); exactly-once per ``event_id`` via ``billing_event_log``; only the trial
source and the two trial kinds; the owner billing names while they are still
a member, else the community's superadmins; nothing for a deleted community;
and the letter in each recipient's own language.
"""

from __future__ import annotations

import secrets

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.platform_endpoints.billing_test import (
    _configure_billing,  # noqa: F401 - autouse: the envelope's keys
    _mint_token,
    _post,
)
from app.models.platform.billing import BillingEventLog
from app.models.platform.guild import GuildRole, GuildStatus
from app.models.platform.notification import Notification, NotificationType
from app.core.notification_categories import NotificationCategory
from app.services.platform import email_outbox, identity_refs, notice_outbox
from app.testing import (
    billing_guild_ref,
    create_guild,
    create_guild_membership,
    create_user,
    drain_notices,
)


@pytest.fixture
def letters(monkeypatch) -> list[dict]:
    """The letters the notice worker hands the email outbox, by recipient."""
    sent: list[dict] = []

    async def _enqueue(_session, recipient, *, category, pieces, **kwargs):
        sent.append({"user_id": recipient.id, "category": category, "pieces": pieces})
        return True

    monkeypatch.setattr(email_outbox, "enqueue", _enqueue)
    return sent


async def _community(session: AsyncSession):
    """A community with an owner (superadmin), a second superadmin and an
    admin, and somebody who used to be in it."""
    guild = await create_guild(session, name="Acme")
    owner = await create_user(session, email="owner@example.com")
    other_seat = await create_user(session, email="seat@example.com", locale="de")
    admin = await create_user(session, email="admin@example.com")
    gone = await create_user(session, email="gone@example.com")
    await create_guild_membership(
        session, user=owner, guild=guild, role=GuildRole.superadmin
    )
    await create_guild_membership(
        session, user=other_seat, guild=guild, role=GuildRole.superadmin
    )
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    return guild.id, owner.id, other_seat.id, admin.id, gone.id


async def _notice(guild_id: int, **fields) -> dict:
    return {
        "guild_ref": await billing_guild_ref(guild_id),
        "event_id": fields.pop("event_id", f"evt-{secrets.token_hex(6)}"),
        "source": fields.pop("source", "trial_expiry"),
        "kind": fields.pop("kind", "trial_ending"),
        "recipient_user_ref": fields.pop("recipient_user_ref", None),
        "trial_ends_on": fields.pop("trial_ends_on", "2026-10-08"),
        **fields,
    }


async def _told(session: AsyncSession, user_id: int) -> list[Notification]:
    """The trial lines in this person's bell, once the outbox has run."""
    session.expire_all()
    await drain_notices()
    return list(
        (
            await session.exec(
                select(Notification).where(
                    Notification.user_id == user_id,
                    Notification.type.in_(  # type: ignore[union-attr]
                        [
                            NotificationType.guild_trial_ending,
                            NotificationType.guild_trial_ended,
                        ]
                    ),
                )
            )
        ).all()
    )


async def test_the_owner_billing_names_is_told(
    client: AsyncClient, session: AsyncSession, letters
):
    guild_id, owner_id, other_seat_id, admin_id, _ = await _community(session)
    owner_ref = await identity_refs.billing_user_ref(user_id=owner_id)

    response = await _post(
        client,
        "community-notice",
        await _notice(guild_id, recipient_user_ref=owner_ref),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"delivered": True}
    (line,) = await _told(session, owner_id)
    assert line.type == NotificationType.guild_trial_ending
    assert line.data == {
        "community": "Acme",
        "trial_ends_on": "2026-10-08",
        "guild_id": guild_id,
        "target_path": "/settings/usage",
    }
    assert await _told(session, other_seat_id) == []
    assert await _told(session, admin_id) == []
    (letter,) = letters
    assert letter["user_id"] == owner_id
    # An account letter, filed under no community.
    assert letter["category"] is NotificationCategory.account
    pieces = letter["pieces"]
    assert pieces.subject == "Acme's trial ends on 8 October 2026"
    assert pieces.link is not None and pieces.link.endswith(
        f"/c/{guild_id}/settings/usage"
    )
    assert "read-only until a plan is chosen" in pieces.body


async def test_an_owner_moved_off_the_seat_falls_back_to_the_superadmins(
    client: AsyncClient, session: AsyncSession, letters
):
    """Still a member, no longer the seat: the plan is not theirs to act on."""
    guild_id, _, other_seat_id, admin_id, _ = await _community(session)
    admin_ref = await identity_refs.billing_user_ref(user_id=admin_id)

    response = await _post(
        client,
        "community-notice",
        await _notice(guild_id, recipient_user_ref=admin_ref),
    )

    assert response.json() == {"delivered": True}
    assert await _told(session, admin_id) == []
    assert len(await _told(session, other_seat_id)) == 1


async def test_a_notice_that_could_not_be_written_is_not_recorded(
    client: AsyncClient, session: AsyncSession, letters, monkeypatch
):
    """Nothing is claimed until the notice is written down, so billing's retry
    of the same event delivers it."""
    guild_id, owner_id, *_ = await _community(session)
    payload = await _notice(guild_id, event_id="evt-retry")
    real_enqueue = notice_outbox.enqueue

    async def _broken(*_args, **_kwargs):
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(notice_outbox, "enqueue", _broken)
    failed = await _post(client, "community-notice", payload)
    assert failed.status_code == 503, failed.text
    assert failed.json()["detail"] == "BILLING_NOTICE_NOT_DELIVERED"
    assert (
        await session.exec(
            select(BillingEventLog.event_id).where(
                BillingEventLog.event_id == "evt-retry"
            )
        )
    ).all() == []
    assert await _told(session, owner_id) == []

    monkeypatch.setattr(notice_outbox, "enqueue", real_enqueue)
    retried = await _post(client, "community-notice", payload)
    assert retried.json() == {"delivered": True}
    assert len(await _told(session, owner_id)) == 1
    again = await _post(client, "community-notice", payload)
    assert again.json() == {"delivered": False}
    assert len(await _told(session, owner_id)) == 1


async def test_an_owner_who_left_falls_back_to_the_superadmins(
    client: AsyncClient, session: AsyncSession, letters
):
    guild_id, owner_id, other_seat_id, admin_id, gone_id = await _community(session)
    gone_ref = await identity_refs.billing_user_ref(user_id=gone_id)

    response = await _post(
        client,
        "community-notice",
        await _notice(guild_id, kind="trial_ended", recipient_user_ref=gone_ref),
    )

    assert response.json() == {"delivered": True}
    assert await _told(session, gone_id) == []
    assert len(await _told(session, owner_id)) == 1
    assert len(await _told(session, other_seat_id)) == 1
    assert await _told(session, admin_id) == []


@pytest.mark.parametrize(
    "recipient_user_ref", [None, "not-a-reference", "guild"], ids=str
)
async def test_nobody_named_falls_back_to_the_superadmins(
    client: AsyncClient, session: AsyncSession, letters, recipient_user_ref
):
    guild_id, owner_id, other_seat_id, _, _ = await _community(session)
    if recipient_user_ref == "guild":
        # A reference billing holds, but for the guild rather than a person.
        recipient_user_ref = await billing_guild_ref(guild_id)

    response = await _post(
        client,
        "community-notice",
        await _notice(guild_id, recipient_user_ref=recipient_user_ref),
    )

    assert response.json() == {"delivered": True}
    assert len(await _told(session, owner_id)) == 1
    assert len(await _told(session, other_seat_id)) == 1


async def test_each_letter_is_in_its_readers_language(
    client: AsyncClient, session: AsyncSession, letters
):
    guild_id, owner_id, other_seat_id, *_ = await _community(session)

    await _post(client, "community-notice", await _notice(guild_id, kind="trial_ended"))
    await _told(session, owner_id)

    by_recipient = {letter["user_id"]: letter["pieces"] for letter in letters}
    assert set(by_recipient) == {owner_id, other_seat_id}
    assert by_recipient[owner_id].subject == "Acme's trial has ended"
    german = by_recipient[other_seat_id]
    assert german.subject == "Die Testphase von Acme ist beendet"
    assert "schreibgeschützt" in german.body


async def test_a_replayed_event_tells_nobody_twice(
    client: AsyncClient, session: AsyncSession, letters
):
    guild_id, owner_id, *_ = await _community(session)
    payload = await _notice(guild_id, event_id="evt-notice-dup")

    first = await _post(client, "community-notice", payload)
    again = await _post(client, "community-notice", payload)

    assert first.json() == {"delivered": True}
    assert again.status_code == 200, again.text
    assert again.json() == {"delivered": False}
    assert len(await _told(session, owner_id)) == 1
    assert len(letters) == 2  # one letter for each seat, once
    rows = (
        await session.exec(
            select(BillingEventLog).where(BillingEventLog.event_id == "evt-notice-dup")
        )
    ).all()
    assert [(row.op, row.source) for row in rows] == [
        ("community_notice", "trial_expiry")
    ]


@pytest.mark.parametrize("status", [GuildStatus.deleted, GuildStatus.suspended])
async def test_a_deleted_or_suspended_community_is_recorded_and_told_nothing(
    client: AsyncClient, session: AsyncSession, letters, status
):
    guild_id, owner_id, *_ = await _community(session)
    from app.models.platform.guild import Guild

    guild = (await session.exec(select(Guild).where(Guild.id == guild_id))).one()
    guild.status = status.value
    session.add(guild)
    await session.commit()

    response = await _post(
        client, "community-notice", await _notice(guild_id, event_id="evt-gone")
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"delivered": False}
    assert await _told(session, owner_id) == []
    assert letters == []
    assert (
        await session.exec(
            select(BillingEventLog.event_id).where(
                BillingEventLog.event_id == "evt-gone"
            )
        )
    ).all() == ["evt-gone"]


@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"kind": "trial_extended"}, "BILLING_INVALID_PAYLOAD"),
        ({"kind": "trial_ending", "message": "free text"}, None),
        ({"source": "paddle_webhook"}, "BILLING_NOTICE_SOURCE_NOT_ALLOWED"),
        ({"source": "made_up"}, "BILLING_INVALID_PAYLOAD"),
        ({"trial_ends_on": "soon"}, "BILLING_INVALID_PAYLOAD"),
        ({"event_id": "x" * 129}, "BILLING_INVALID_PAYLOAD"),
    ],
)
async def test_only_the_fixed_notices_are_taken(
    client: AsyncClient, session: AsyncSession, letters, fields, code
):
    guild_id, owner_id, *_ = await _community(session)

    response = await _post(
        client,
        "community-notice",
        await _notice(guild_id, **{"event_id": "evt-x", **fields}),
    )

    if code is None:
        # An unknown field carries nothing anywhere: the words are ours.
        assert response.status_code == 200, response.text
        (line,) = await _told(session, owner_id) or [None]
        assert line is not None and "message" not in line.data
        return
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == code
    assert await _told(session, owner_id) == []
    assert (
        await session.exec(
            select(BillingEventLog.event_id).where(BillingEventLog.event_id == "evt-x")
        )
    ).all() == []


async def test_the_envelope_is_the_tier_writes(
    client: AsyncClient, session: AsyncSession, letters
):
    guild_id, owner_id, *_ = await _community(session)
    payload = await _notice(guild_id)

    unsigned = await client.post("/api/v1/billing/community-notice", json=payload)
    assert unsigned.status_code == 403
    assert unsigned.json()["detail"] == "BILLING_MISSING_SIGNATURE"

    wrong_audience = await _post(
        client, "community-notice", payload, token=_mint_token(aud="initiative:other")
    )
    assert wrong_audience.status_code == 403

    token = _mint_token(jti="notice-once")
    first = await _post(client, "community-notice", payload, token=token)
    assert first.status_code == 200, first.text
    replayed = await _post(
        client, "community-notice", await _notice(guild_id), token=token
    )
    assert replayed.status_code == 403
    assert replayed.json()["detail"] == "BILLING_REPLAYED_TOKEN"
    assert len(await _told(session, owner_id)) == 1


async def test_an_unknown_community_is_404_and_consumes_nothing(
    client: AsyncClient, session: AsyncSession, letters
):
    payload = {
        "guild_ref": "gbil_nobody",
        "event_id": "evt-unknown",
        "source": "trial_expiry",
        "kind": "trial_ending",
        "recipient_user_ref": None,
        "trial_ends_on": "2026-10-08",
    }
    response = await _post(client, "community-notice", payload)
    assert response.status_code == 404
    assert (
        await session.exec(
            select(BillingEventLog.event_id).where(
                BillingEventLog.event_id == "evt-unknown"
            )
        )
    ).all() == []
