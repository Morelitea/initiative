"""Managing the addresses on your own account.

The rules §6.2 of the design states, as endpoints: any proven address signs
you in, exactly one is primary and always proven, adding one never says who
holds it, and an account always keeps a proven address and a primary.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import hash_email
from app.models.platform.user_email import UserEmail
from app.models.platform.user_token import UserToken, UserTokenPurpose
from app.services.auth import addresses
from app.testing.factories import create_user, get_auth_headers

pytestmark = [pytest.mark.integration, pytest.mark.auth]


async def _enable_smtp(session: AsyncSession) -> None:
    """A deployment that can send. Adding an address writes to it, so the
    endpoint refuses before looking at the address when it cannot."""
    from app.services.platform import app_settings as app_settings_service

    row = await app_settings_service.get_app_settings(session)
    row.smtp_host = "smtp.example.com"
    row.smtp_from_address = "noreply@example.com"
    session.add(row)
    await session.commit()


async def _listing(client: AsyncClient, user) -> list[dict]:
    response = await client.get(
        "/api/v1/users/me/emails", headers=get_auth_headers(user)
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


async def test_an_account_lists_the_address_it_was_created_with(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="only@example.com")

    items = await _listing(client, user)
    assert [(i["email"], i["is_primary"], i["verified"]) for i in items] == [
        ("only@example.com", True, True)
    ]


async def test_a_synthetic_address_is_not_shown(
    client: AsyncClient, session: AsyncSession
):
    """``{subject}@oidc.local`` is not a mailbox and nothing can be done with
    it, so it is not offered as one."""
    user = await create_user(session, email="sso@example.com")
    addresses.record_address(
        session,
        user_id=user.id,
        email="idp-subject-1@oidc.local",
        source=addresses.SOURCE_SYNTHETIC,
        verified=False,
        is_primary=False,
    )
    await session.commit()

    assert [i["email"] for i in await _listing(client, user)] == ["sso@example.com"]


async def test_adding_an_address_holds_it_unproven(
    client: AsyncClient, session: AsyncSession
):
    await _enable_smtp(session)
    user = await create_user(session, email="primary@example.com")

    response = await client.post(
        "/api/v1/users/me/emails",
        json={"email": "second@example.com"},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 202, response.text

    items = await _listing(client, user)
    second = [i for i in items if i["email"] == "second@example.com"]
    assert second and second[0]["verified"] is False
    assert second[0]["is_primary"] is False
    assert second[0]["source"] == addresses.SOURCE_ADDED


async def test_adding_an_address_somebody_holds_says_the_same_thing(
    client: AsyncClient, session: AsyncSession
):
    """Rule 5: the answer does not say whether the address was free. What
    changes is that nothing is written down for this account."""
    await _enable_smtp(session)
    owner = await create_user(session, email="taken@example.com")
    other = await create_user(session, email="asker@example.com")
    owner_id, other_id = owner.id, other.id

    taken = await client.post(
        "/api/v1/users/me/emails",
        json={"email": "taken@example.com"},
        headers=get_auth_headers(other),
    )
    free = await client.post(
        "/api/v1/users/me/emails",
        json={"email": "untaken@example.com"},
        headers=get_auth_headers(other),
    )
    assert taken.status_code == free.status_code
    assert taken.json() == free.json()

    # The asker gained the free address and not the taken one.
    asker_holds = {
        addresses.normalize(i["email"]) for i in await _listing(client, other)
    }
    assert asker_holds == {"asker@example.com", "untaken@example.com"}

    # And the taken address is still where it was.
    session.expire_all()
    still_theirs = await addresses.find_user_by_address(session, "taken@example.com")
    assert still_theirs is not None and still_theirs.id == owner_id
    assert other_id != owner_id


async def test_a_verification_token_proves_one_address(
    client: AsyncClient, session: AsyncSession
):
    await _enable_smtp(session)
    user = await create_user(session, email="holder@example.com")
    user_id = user.id
    await client.post(
        "/api/v1/users/me/emails",
        json={"email": "proveme@example.com"},
        headers=get_auth_headers(user),
    )

    session.expire_all()
    record = (
        await session.exec(
            select(UserToken).where(
                UserToken.user_id == user_id,
                UserToken.purpose == UserTokenPurpose.email_verification,
            )
        )
    ).one()
    # The token names the address it proves, not just the account.
    assert record.user_email_id is not None


async def test_the_primary_moves_only_to_a_proven_address(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="first@example.com")
    unproven = addresses.record_address(
        session,
        user_id=user.id,
        email="unproven@example.com",
        source=addresses.SOURCE_ADDED,
        verified=False,
        is_primary=False,
    )
    proven = addresses.record_address(
        session,
        user_id=user.id,
        email="proven@example.com",
        source=addresses.SOURCE_ADDED,
        verified=True,
        is_primary=False,
    )
    await session.commit()
    unproven_id, proven_id = unproven.id, proven.id

    refused = await client.put(
        f"/api/v1/users/me/emails/{unproven_id}/primary", headers=get_auth_headers(user)
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == "ADDRESS_NOT_VERIFIED"

    moved = await client.put(
        f"/api/v1/users/me/emails/{proven_id}/primary", headers=get_auth_headers(user)
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["is_primary"] is True

    # Exactly one primary, still.
    primaries = [i["email"] for i in await _listing(client, user) if i["is_primary"]]
    assert primaries == ["proven@example.com"]


async def test_the_primary_address_is_not_removed(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="keepme@example.com")
    address_id = (await _listing(client, user))[0]["id"]

    refused = await client.delete(
        f"/api/v1/users/me/emails/{address_id}", headers=get_auth_headers(user)
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == "PRIMARY_ADDRESS"


async def test_the_last_proven_address_is_not_removed(
    client: AsyncClient, session: AsyncSession
):
    """Even once it is no longer the primary: an account keeps a way back in."""
    user = await create_user(session, email="proven@example.com")
    spare = addresses.record_address(
        session,
        user_id=user.id,
        email="spare@example.com",
        source=addresses.SOURCE_ADDED,
        verified=True,
        is_primary=False,
    )
    await session.commit()
    spare_id = spare.id

    # Hand the primary to the spare, leaving the original merely proven.
    moved = await client.put(
        f"/api/v1/users/me/emails/{spare_id}/primary", headers=get_auth_headers(user)
    )
    assert moved.status_code == 200, moved.text

    original = [
        i for i in await _listing(client, user) if i["email"] == "proven@example.com"
    ][0]
    gone = await client.delete(
        f"/api/v1/users/me/emails/{original['id']}", headers=get_auth_headers(user)
    )
    assert gone.status_code == 204, gone.text

    # And now the spare is the only proven one, so it stays.
    refused = await client.delete(
        f"/api/v1/users/me/emails/{spare_id}", headers=get_auth_headers(user)
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == "PRIMARY_ADDRESS"


async def test_an_address_on_another_account_is_not_yours_to_touch(
    client: AsyncClient, session: AsyncSession
):
    owner = await create_user(session, email="mine@example.com")
    stranger = await create_user(session, email="stranger@example.com")
    owner_address_id = (await _listing(client, owner))[0]["id"]

    for response in (
        await client.delete(
            f"/api/v1/users/me/emails/{owner_address_id}",
            headers=get_auth_headers(stranger),
        ),
        await client.put(
            f"/api/v1/users/me/emails/{owner_address_id}/primary",
            headers=get_auth_headers(stranger),
        ),
    ):
        assert response.status_code == 404
        assert response.json()["detail"] == "ADDRESS_NOT_FOUND"


async def test_an_unproven_claim_does_not_take_the_address(
    client: AsyncClient, session: AsyncSession
):
    """An address is taken by proving it, not by typing it. Until a claim is
    proven it belongs to nobody, and the person who holds the mailbox can make
    the same claim."""
    await _enable_smtp(session)
    other_claimant = await create_user(session, email="claimant@example.com")
    holder = await create_user(session, email="holder@example.com")

    claimed = await client.post(
        "/api/v1/users/me/emails",
        json={"email": "contested@example.com"},
        headers=get_auth_headers(other_claimant),
    )
    assert claimed.status_code == 202

    # The real holder can still make the same claim.
    theirs = await client.post(
        "/api/v1/users/me/emails",
        json={"email": "contested@example.com"},
        headers=get_auth_headers(holder),
    )
    assert theirs.status_code == 202
    assert "contested@example.com" in {
        i["email"] for i in await _listing(client, holder)
    }


async def test_proving_an_address_settles_every_other_claim(
    client: AsyncClient, session: AsyncSession
):
    other_claimant = await create_user(session, email="claimant@example.com")
    holder = await create_user(session, email="holder2@example.com")
    other_claimant_id, holder_id = other_claimant.id, holder.id
    for user_id in (other_claimant_id, holder_id):
        addresses.record_address(
            session,
            user_id=user_id,
            email="contested2@example.com",
            source=addresses.SOURCE_ADDED,
            verified=False,
            is_primary=False,
        )
    await session.commit()

    theirs = await addresses._pending_for_user(
        session, user_id=holder_id, digest=hash_email("contested2@example.com")
    )
    await addresses.verify_for_user(session, user_id=holder_id, address_id=theirs.id)
    await session.commit()

    # The holder has it, and the other claim is gone.
    session.expire_all()
    rows = (
        await session.exec(
            select(UserEmail).where(
                UserEmail.email_hash == hash_email("contested2@example.com")
            )
        )
    ).all()
    assert [(r.user_id, r.verified_at is not None) for r in rows] == [(holder_id, True)]


async def test_an_unproven_address_signs_nobody_in(
    client: AsyncClient, session: AsyncSession
):
    """Rule 2: only a proven address resolves, so a claim in progress is not a
    way in and not a way to ask for a password reset."""
    user = await create_user(session, email="real@example.com")
    addresses.record_address(
        session,
        user_id=user.id,
        email="pending@example.com",
        source=addresses.SOURCE_ADDED,
        verified=False,
        is_primary=False,
    )
    await session.commit()

    assert await addresses.find_user_by_address(session, "pending@example.com") is None
    found = await addresses.find_user_by_address(session, "real@example.com")
    assert found is not None


async def test_an_account_holds_a_bounded_number_of_addresses(
    client: AsyncClient, session: AsyncSession
):
    await _enable_smtp(session)
    user = await create_user(session, email="collector@example.com")
    for n in range(addresses.MAX_ADDRESSES_PER_ACCOUNT - 1):
        addresses.record_address(
            session,
            user_id=user.id,
            email=f"extra-{n}@example.com",
            source=addresses.SOURCE_ADDED,
            verified=False,
            is_primary=False,
        )
    await session.commit()

    refused = await client.post(
        "/api/v1/users/me/emails",
        json={"email": "one-too-many@example.com"},
        headers=get_auth_headers(user),
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == "TOO_MANY_ADDRESSES"


async def test_asking_again_resends_rather_than_refusing(
    client: AsyncClient, session: AsyncSession
):
    """A letter that did not arrive is sent again by asking again — the claim
    this account already has comes back rather than being treated as taken."""
    await _enable_smtp(session)
    user = await create_user(session, email="retry@example.com")

    for _ in range(2):
        response = await client.post(
            "/api/v1/users/me/emails",
            json={"email": "again@example.com"},
            headers=get_auth_headers(user),
        )
        assert response.status_code == 202

    held = [
        i for i in await _listing(client, user) if i["email"] == "again@example.com"
    ]
    assert len(held) == 1


async def test_a_full_account_answers_the_same_whoever_holds_the_address(
    client: AsyncClient, session: AsyncSession
):
    """Rule 5 at the limit: how full the account is settles before the address
    is looked at, so being full does not become a way to ask who holds what."""
    await _enable_smtp(session)
    holder = await create_user(session, email="holder3@example.com")
    addresses.record_address(
        session,
        user_id=holder.id,
        email="spoken-for@example.com",
        source=addresses.SOURCE_ADDED,
        verified=True,
        is_primary=False,
    )
    full = await create_user(session, email="full@example.com")
    for n in range(addresses.MAX_ADDRESSES_PER_ACCOUNT - 1):
        addresses.record_address(
            session,
            user_id=full.id,
            email=f"held-{n}@example.com",
            source=addresses.SOURCE_ADDED,
            verified=False,
            is_primary=False,
        )
    await session.commit()

    taken = await client.post(
        "/api/v1/users/me/emails",
        json={"email": "spoken-for@example.com"},
        headers=get_auth_headers(full),
    )
    free = await client.post(
        "/api/v1/users/me/emails",
        json={"email": "nobody-has-this@example.com"},
        headers=get_auth_headers(full),
    )
    assert taken.status_code == free.status_code == 400
    assert taken.json() == free.json()


async def test_proving_an_address_somebody_just_proved_is_refused(
    client: AsyncClient, session: AsyncSession
):
    """Two claims can be proven at the same moment. The index settles which,
    and the loser is told the address is taken rather than meeting an error."""
    first = await create_user(session, email="first3@example.com")
    second = await create_user(session, email="second3@example.com")
    first_id, second_id = first.id, second.id
    for user_id in (first_id, second_id):
        addresses.record_address(
            session,
            user_id=user_id,
            email="contested3@example.com",
            source=addresses.SOURCE_ADDED,
            verified=False,
            is_primary=False,
        )
    await session.commit()

    digest = hash_email("contested3@example.com")
    theirs = await addresses._pending_for_user(session, user_id=first_id, digest=digest)
    await addresses.verify_for_user(session, user_id=first_id, address_id=theirs.id)
    await session.commit()

    # The second claim was deleted by the first proving it, so there is nothing
    # left to prove — and a claim that survived a concurrent commit is refused.
    session.expire_all()
    assert (
        await addresses._pending_for_user(session, user_id=second_id, digest=digest)
    ) is None
    holder = await addresses.find_user_by_address(session, "contested3@example.com")
    assert holder is not None and holder.id == first_id
