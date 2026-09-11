"""An account's addresses, and the lookup that resolves one.

Pins the shape the login now runs on: the address set is what signs somebody
in, an account that predates the set still signs in through the fallback and
says so in the log, and erasure takes every address rather than the one
``users`` happens to carry.
"""

from __future__ import annotations

import logging

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import SALT_EMAIL, decrypt_field, hash_email
from app.models.platform.user import User
from app.models.platform.user_email import UserEmail
from app.services.auth import addresses
from app.testing.factories import create_user

pytestmark = [pytest.mark.auth]


async def _addresses(session: AsyncSession, user_id: int) -> list[UserEmail]:
    session.expire_all()
    return list(
        (
            await session.exec(
                select(UserEmail)
                .where(UserEmail.user_id == user_id)
                .order_by(UserEmail.id)
            )
        ).all()
    )


@pytest.mark.unit
async def test_an_account_is_created_holding_its_address(session: AsyncSession):
    user = await create_user(session, email="held@example.com")

    rows = await _addresses(session, user.id)
    assert len(rows) == 1
    assert rows[0].email_hash == hash_email("held@example.com")
    assert decrypt_field(rows[0].email_encrypted, SALT_EMAIL) == "held@example.com"
    assert rows[0].is_primary is True
    assert rows[0].source == addresses.SOURCE_SIGNUP
    assert rows[0].verified_at is not None


@pytest.mark.unit
async def test_any_of_an_accounts_addresses_resolves_to_it(session: AsyncSession):
    """The point of the table: one account, more than one way in."""
    user = await create_user(session, email="first@example.com")
    addresses.record_address(
        session,
        user_id=user.id,
        email="second@example.com",
        source=addresses.SOURCE_ADDED,
        verified=True,
        is_primary=False,
    )
    await session.commit()

    for address in ("first@example.com", "second@example.com"):
        found = await addresses.find_user_by_address(session, address)
        assert found is not None and found.id == user.id


@pytest.mark.unit
async def test_an_address_is_matched_however_it_is_typed(session: AsyncSession):
    user = await create_user(session, email="cased@example.com")

    found = await addresses.find_user_by_address(session, "  CaSeD@Example.COM ")
    assert found is not None and found.id == user.id


@pytest.mark.unit
async def test_an_address_nobody_holds_resolves_to_nobody(session: AsyncSession):
    await create_user(session, email="somebody@example.com")

    assert await addresses.find_user_by_address(session, "nobody@example.com") is None


@pytest.mark.unit
async def test_an_account_with_no_address_row_still_resolves_and_says_so(
    session: AsyncSession, caplog
):
    """An account with no row in the address set signs in on what ``users``
    carries, and the log names it — which is what says whether the columns are
    still needed."""
    user = await create_user(session, email="stranded@example.com")
    user_id = user.id
    for row in await _addresses(session, user_id):
        await session.delete(row)
    await session.commit()

    with caplog.at_level(logging.WARNING, logger="app.services.auth.addresses"):
        found = await addresses.find_user_by_address(session, "stranded@example.com")

    assert found is not None and found.id == user_id
    assert f"account {user_id}" in caplog.text


@pytest.mark.unit
async def test_a_resolved_address_does_not_report_a_fallback(
    session: AsyncSession, caplog
):
    await create_user(session, email="present@example.com")

    with caplog.at_level(logging.WARNING, logger="app.services.auth.addresses"):
        assert await addresses.find_user_by_address(session, "present@example.com")

    assert caplog.text == ""


@pytest.mark.unit
async def test_two_accounts_cannot_hold_one_address(session: AsyncSession):
    await create_user(session, email="shared@example.com")
    other = await create_user(session, email="other@example.com")

    addresses.record_address(
        session,
        user_id=other.id,
        email="shared@example.com",
        source=addresses.SOURCE_ADDED,
        verified=True,
        is_primary=False,
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


@pytest.mark.unit
async def test_an_account_has_one_primary_address(session: AsyncSession):
    user = await create_user(session, email="primary@example.com")

    addresses.record_address(
        session,
        user_id=user.id,
        email="second-primary@example.com",
        source=addresses.SOURCE_ADDED,
        verified=True,
        is_primary=True,
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


@pytest.mark.integration
async def test_erasure_takes_every_address(session: AsyncSession):
    """Erasing an account has to reach the whole set, not the one address
    ``users`` happens to carry — and the fallback must not resolve what was
    erased."""
    from app.services.platform import users as users_service

    user = await create_user(session, email="erase-me@example.com")
    user_id = user.id
    addresses.record_address(
        session,
        user_id=user_id,
        email="erase-me-too@example.com",
        source=addresses.SOURCE_ADDED,
        verified=True,
        is_primary=False,
    )
    await session.commit()

    await users_service.soft_delete_user(session, user_id)

    rows = await _addresses(session, user_id)
    assert len(rows) == 1
    assert decrypt_field(rows[0].email_encrypted, SALT_EMAIL).startswith("anonymized-")
    for gone in ("erase-me@example.com", "erase-me-too@example.com"):
        assert await addresses.find_user_by_address(session, gone) is None


@pytest.mark.integration
async def test_registering_records_the_address(
    client: AsyncClient, session: AsyncSession
):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "registered@example.com",
            "password": "testpassword123",
            "full_name": "Registered Person",
            "username": "registered",
        },
    )
    assert response.status_code == 201, response.text

    session.expire_all()
    user = (
        await session.exec(
            select(User).where(User.email_hash == hash_email("registered@example.com"))
        )
    ).one()
    rows = await _addresses(session, user.id)
    assert [(r.is_primary, r.source) for r in rows] == [(True, addresses.SOURCE_SIGNUP)]


@pytest.mark.integration
async def test_the_backfill_carries_every_account(session: AsyncSession):
    """The statement the migration runs, against rows.

    A fresh install has no accounts to carry, so this is the only place the
    statement meets data: what it selects, what it casts, and what each account
    ends up holding.
    """
    import importlib.util

    verified = await create_user(session, email="carry-verified@example.com")
    unverified = await create_user(
        session, email="carry-unverified@example.com", email_verified=False
    )
    verified_id, unverified_id = verified.id, unverified.id
    ids = [verified_id, unverified_id]

    for user_id in ids:
        for row in await _addresses(session, user_id):
            await session.delete(row)
    await session.commit()

    spec = importlib.util.spec_from_file_location(
        "_backfill_migration",
        "alembic/versions/20260911_0261_an_account_has_addresses.py",
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    from sqlalchemy import text

    await session.exec(text(migration._BACKFILL))
    await session.commit()

    # Plain values, taken as each account's rows are read: the next read
    # expires the objects from the one before it.
    carried = {}
    for user_id in ids:
        rows = await _addresses(session, user_id)
        carried[user_id] = [(r.is_primary, r.source, r.verified_at) for r in rows]

    assert [len(rows) for rows in carried.values()] == [1, 1]
    for rows in carried.values():
        is_primary, source, _ = rows[0]
        assert is_primary is True
        assert source == addresses.SOURCE_SIGNUP

    # The flag each account had comes across as a time, or as nothing.
    assert carried[verified_id][0][2] is not None
    assert carried[unverified_id][0][2] is None

    # And the addresses resolve through the new table afterwards.
    for address in ("carry-verified@example.com", "carry-unverified@example.com"):
        assert await addresses.find_user_by_address(session, address) is not None


@pytest.mark.integration
async def test_signing_in_stamps_the_address_it_resolved_through(
    client: AsyncClient, session: AsyncSession
):
    """Which address somebody actually uses is the point of keeping several."""
    user = await create_user(session, email="stamped@example.com")
    user_id = user.id
    assert (await _addresses(session, user_id))[0].last_login_at is None

    response = await client.post(
        "/api/v1/auth/token",
        data={"username": "stamped@example.com", "password": "testpassword123"},
    )
    assert response.status_code == 200, response.text

    assert (await _addresses(session, user_id))[0].last_login_at is not None


@pytest.mark.integration
async def test_an_address_is_taken_whichever_account_holds_it(
    client: AsyncClient, session: AsyncSession
):
    """Registering against a secondary address of somebody else's account is
    refused by the duplicate check rather than by the unique constraint."""
    user = await create_user(session, email="holder@example.com")
    addresses.record_address(
        session,
        user_id=user.id,
        email="also-theirs@example.com",
        source=addresses.SOURCE_ADDED,
        verified=True,
        is_primary=False,
    )
    await session.commit()

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "also-theirs@example.com",
            "password": "testpassword123",
            "full_name": "Someone Else",
            "username": "someoneelse",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "EMAIL_ALREADY_REGISTERED"


@pytest.mark.integration
async def test_a_password_reset_finds_any_of_an_accounts_addresses(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="reset-primary@example.com")
    addresses.record_address(
        session,
        user_id=user.id,
        email="reset-second@example.com",
        source=addresses.SOURCE_ADDED,
        verified=True,
        is_primary=False,
    )
    await session.commit()

    async def _forgot(email: str) -> int:
        return (
            await client.post("/api/v1/auth/password/forgot", json={"email": email})
        ).status_code

    # An address nobody holds is answered as if it had been sent; one that
    # reaches an account goes on to actually send. The secondary address has to
    # land on the same side of that as the primary.
    assert await _forgot("reset-second@example.com") == await _forgot(
        "reset-primary@example.com"
    )
    assert await _forgot("nobody@example.com") != await _forgot(
        "reset-primary@example.com"
    )
