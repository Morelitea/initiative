"""What reaches an account with more than one address.

Two things stopped being true when an account gained a second address: an
invite bound to one of them, and a letter about the account itself. Both are
about the whole set now, and both fall back to what ``users`` carries.
"""

from __future__ import annotations

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import hash_email
from app.models.platform.user_email import UserEmail
from app.services.auth import addresses
from app.testing.factories import create_user

pytestmark = [pytest.mark.auth]


async def _second_address(session: AsyncSession, user_id: int, email: str, **kw):
    row = addresses.record_address(
        session,
        user_id=user_id,
        email=email,
        source=addresses.SOURCE_ADDED,
        is_primary=False,
        **{"verified": True, **kw},
    )
    await session.commit()
    return row


@pytest.mark.unit
async def test_account_mail_reaches_every_proven_address(session: AsyncSession):
    user = await create_user(session, email="primary@example.com")
    user_id = user.id
    await _second_address(session, user_id, "work@example.com")

    reach = await addresses.proven_addresses(session, user_id=user_id)
    # The primary leads, so a single-recipient reading still gets the right one.
    assert reach == ["primary@example.com", "work@example.com"]


@pytest.mark.unit
async def test_account_mail_skips_an_unproven_address(session: AsyncSession):
    user = await create_user(session, email="primary2@example.com")
    user_id = user.id
    await _second_address(session, user_id, "pending@example.com", verified=False)

    assert await addresses.proven_addresses(session, user_id=user_id) == [
        "primary2@example.com"
    ]


@pytest.mark.unit
async def test_account_mail_falls_back_to_what_users_carries(
    session: AsyncSession, caplog
):
    """An account whose rows did not come across still gets its mail."""
    import logging

    user = await create_user(session, email="stranded@example.com")
    user_id = user.id
    for row in (
        await session.exec(select(UserEmail).where(UserEmail.user_id == user_id))
    ).all():
        await session.delete(row)
    await session.commit()

    with caplog.at_level(logging.WARNING, logger="app.services.auth.addresses"):
        reach = await addresses.proven_addresses(session, user_id=user_id)

    assert reach == ["stranded@example.com"]
    assert f"account {user_id}" in caplog.text


@pytest.mark.unit
async def test_an_account_holds_the_address_an_invite_names(session: AsyncSession):
    user = await create_user(session, email="me@example.com")
    stranger = await create_user(session, email="stranger@example.com")
    user_id, stranger_id = user.id, stranger.id
    await _second_address(session, user_id, "me-at-work@example.com")

    for address in ("me@example.com", "me-at-work@example.com"):
        assert await addresses.holds_address(session, user_id=user_id, email=address)
        assert not await addresses.holds_address(
            session, user_id=stranger_id, email=address
        )


@pytest.mark.unit
async def test_an_unproven_claim_is_not_holding_the_address(session: AsyncSession):
    """An invite is for the person who holds the address, and a claim in
    progress is not holding it."""
    user = await create_user(session, email="claimer@example.com")
    user_id = user.id
    await _second_address(session, user_id, "claimed@example.com", verified=False)

    assert not await addresses.holds_address(
        session, user_id=user_id, email="claimed@example.com"
    )


@pytest.mark.unit
async def test_erasure_knows_every_address_to_scrub(session: AsyncSession):
    """Including the unproven ones: a claim is still a recorded address, and an
    invite bound to one keeps the same trace."""
    user = await create_user(session, email="erase@example.com")
    user_id = user.id
    await _second_address(session, user_id, "erase-work@example.com")
    await _second_address(session, user_id, "erase-pending@example.com", verified=False)

    assert await addresses.held_hashes(session, user_id=user_id) == {
        hash_email("erase@example.com"),
        hash_email("erase-work@example.com"),
        hash_email("erase-pending@example.com"),
    }


@pytest.mark.integration
async def test_a_reset_is_written_to_every_address_the_account_holds(
    client, session: AsyncSession, monkeypatch
):
    """End to end, through the endpoint that asks for a reset — the path that
    decides the recipients runs on its own system-engine session, because the
    request path holds nothing on the address set."""
    from app.services import email as email_service
    from app.services.platform import app_settings as app_settings_service

    row = await app_settings_service.get_app_settings(session)
    row.smtp_host = "smtp.example.com"
    row.smtp_from_address = "noreply@example.com"
    session.add(row)

    user = await create_user(session, email="reset-primary@example.com")
    user_id = user.id
    await _second_address(session, user_id, "reset-work@example.com")

    sent: list[list[str]] = []

    async def _capture(session_, *, recipients, **kwargs):
        sent.append(list(recipients))

    monkeypatch.setattr(email_service, "send_email", _capture)

    response = await client.post(
        "/api/v1/auth/password/forgot", json={"email": "reset-work@example.com"}
    )
    assert response.status_code == 200, response.text
    assert sent == [["reset-primary@example.com", "reset-work@example.com"]]
