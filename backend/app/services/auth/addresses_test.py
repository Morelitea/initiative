"""An account's addresses, and the lookup that resolves one.

Pins the shape the login now runs on: the address set is what signs somebody
in, an account that predates the set still signs in through the fallback and
says so in the log, and erasure takes every address rather than the one
``users`` happens to carry.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import SALT_EMAIL, decrypt_field, hash_email
from app.models.platform.user import User
from app.models.platform.user_email import UserEmail
from app.models.platform.user_email_assertion import UserEmailAssertion
from app.services.auth import addresses
from app.testing.factories import create_user

pytestmark = [pytest.mark.auth]


async def _asserters(session: AsyncSession, user_email_id: int) -> list[int]:
    """The providers claiming one address, by id.

    Deliberately does not expire the session: a caller is usually holding the
    address rows it just read, and expiring them here would detach those.
    """
    rows = (
        await session.exec(
            select(UserEmailAssertion).where(
                UserEmailAssertion.user_email_id == user_email_id
            )
        )
    ).all()
    return sorted(r.provider_id for r in rows)


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
async def test_an_account_with_no_address_row_does_not_sign_in(
    session: AsyncSession,
):
    """The address set is the whole answer. An account holding no row in it is
    resolved by nothing — there is no second place to look."""
    user = await create_user(session, email="stranded@example.com")
    for row in await _addresses(session, user.id):
        await session.delete(row)
    await session.commit()

    assert await addresses.find_user_by_address(session, "stranded@example.com") is None


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
            select(User)
            .join(UserEmail, UserEmail.user_id == User.id)
            .where(UserEmail.email_hash == hash_email("registered@example.com"))
        )
    ).one()
    rows = await _addresses(session, user.id)
    assert [(r.is_primary, r.source) for r in rows] == [(True, addresses.SOURCE_SIGNUP)]


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


@pytest.mark.unit
async def test_an_address_somebody_typed_is_asserted_by_nobody(
    session: AsyncSession,
):
    user = await create_user(session, email="typed@example.com")
    rows = await _addresses(session, user.id)
    assert await _asserters(session, rows[0].id) == []


@pytest.mark.unit
async def test_a_provider_asserting_a_new_address_adds_it(session: AsyncSession):
    from app.testing.factories import create_auth_provider

    user = await create_user(session, email="alice@personal.example.com")
    provider = await create_auth_provider(session, slug="acme")
    user_id, provider_id = user.id, provider.id

    await addresses.ensure_address(
        session,
        user_id=user_id,
        email="alice@acme.example.com",
        source=addresses.SOURCE_OIDC,
        verified=True,
        provider_id=provider_id,
    )
    await session.commit()

    rows = {r.email_hash: r for r in await _addresses(session, user_id)}
    personal = rows[hash_email("alice@personal.example.com")]
    work = rows[hash_email("alice@acme.example.com")]
    assert personal.is_primary is True
    assert await _asserters(session, personal.id) == []
    # The asserted one arrives beside it, claimed, and never as the primary.
    assert work.is_primary is False
    assert await _asserters(session, work.id) == [provider_id]


@pytest.mark.unit
async def test_two_providers_can_assert_one_address(session: AsyncSession):
    """A contractor at two organisations signs into both with one address, and
    neither directory's claim displaces the other."""
    from app.testing.factories import create_auth_provider

    user = await create_user(session, email="contractor@example.com")
    acme = await create_auth_provider(session, slug="acme")
    beta = await create_auth_provider(session, slug="beta")
    user_id, acme_id, beta_id = user.id, acme.id, beta.id

    for provider_id in (acme_id, beta_id):
        await addresses.ensure_address(
            session,
            user_id=user_id,
            email="contractor@example.com",
            source=addresses.SOURCE_OIDC,
            verified=True,
            provider_id=provider_id,
        )
    await session.commit()

    rows = await _addresses(session, user_id)
    assert len(rows) == 1
    assert await _asserters(session, rows[0].id) == sorted([acme_id, beta_id])


@pytest.mark.unit
async def test_asserting_again_refreshes_rather_than_duplicates(
    session: AsyncSession,
):
    from app.testing.factories import create_auth_provider

    user = await create_user(session, email="repeat@example.com")
    provider = await create_auth_provider(session, slug="acme")
    user_id, provider_id = user.id, provider.id
    row_id = (await _addresses(session, user_id))[0].id

    first = datetime(2026, 9, 1, tzinfo=timezone.utc)
    later = datetime(2026, 9, 13, tzinfo=timezone.utc)
    for moment in (first, later):
        await addresses.ensure_address(
            session,
            user_id=user_id,
            email="repeat@example.com",
            source=addresses.SOURCE_OIDC,
            verified=True,
            provider_id=provider_id,
            now=moment,
        )
    await session.commit()

    session.expire_all()
    claim = (
        await session.exec(
            select(UserEmailAssertion).where(UserEmailAssertion.user_email_id == row_id)
        )
    ).one()
    assert claim.first_asserted_at == first
    assert claim.last_asserted_at == later


@pytest.mark.unit
async def test_asserting_an_address_the_account_already_holds_claims_it(
    session: AsyncSession,
):
    from app.testing.factories import create_auth_provider

    user = await create_user(session, email="same@example.com", email_verified=False)
    provider = await create_auth_provider(session, slug="acme")
    user_id, provider_id = user.id, provider.id

    await addresses.ensure_address(
        session,
        user_id=user_id,
        email="same@example.com",
        source=addresses.SOURCE_OIDC,
        verified=True,
        provider_id=provider_id,
    )
    await session.commit()

    rows = await _addresses(session, user_id)
    assert len(rows) == 1
    assert await _asserters(session, rows[0].id) == [provider_id]
    # The provider verified an address the account had not.
    assert rows[0].verified_at is not None
    assert rows[0].is_primary is True


@pytest.mark.unit
async def test_a_provider_cannot_move_somebody_elses_address(session: AsyncSession):
    from app.testing.factories import create_auth_provider

    owner = await create_user(session, email="theirs@example.com")
    other = await create_user(session, email="mine@example.com")
    provider = await create_auth_provider(session, slug="acme")
    owner_id, other_id = owner.id, other.id

    result = await addresses.ensure_address(
        session,
        user_id=other_id,
        email="theirs@example.com",
        source=addresses.SOURCE_OIDC,
        verified=True,
        provider_id=provider.id,
    )
    await session.commit()

    assert result is None
    assert len(await _addresses(session, other_id)) == 1
    still_theirs = await addresses.find_user_by_address(session, "theirs@example.com")
    assert still_theirs is not None and still_theirs.id == owner_id


@pytest.mark.unit
async def test_losing_a_race_to_insert_an_address_resolves_to_the_winner(
    session: AsyncSession, monkeypatch
):
    """Two sign-ins for one previously unseen address both find no row. The
    unique index settles which insert stands, and the loser reads back the row
    that won."""
    from app.testing.factories import create_auth_provider

    user = await create_user(session, email="racer@example.com")
    provider = await create_auth_provider(session, slug="acme")
    user_id, provider_id = user.id, provider.id

    # Stand in for the concurrent writer: the row lands between this call's
    # lookup and its insert.
    real_by_hash = addresses._by_hash
    calls = {"n": 0}

    async def _first_lookup_sees_nothing(sess, digest):
        calls["n"] += 1
        if calls["n"] == 1:
            addresses.record_address(
                sess,
                user_id=user_id,
                email="raced@example.com",
                source=addresses.SOURCE_ADDED,
                verified=True,
                is_primary=False,
            )
            await sess.flush()
            return None
        return await real_by_hash(sess, digest)

    monkeypatch.setattr(addresses, "_by_hash", _first_lookup_sees_nothing)
    landed = await addresses.ensure_address(
        session,
        user_id=user_id,
        email="raced@example.com",
        source=addresses.SOURCE_OIDC,
        verified=True,
        provider_id=provider_id,
    )
    monkeypatch.undo()
    await session.commit()

    assert landed is not None
    rows = {r.email_hash: r for r in await _addresses(session, user_id)}
    assert hash_email("raced@example.com") in rows
    # One row, and the provider's claim is on it.
    assert len([r for r in rows.values()]) == 2
    assert await _asserters(session, rows[hash_email("raced@example.com")].id) == [
        provider_id
    ]
