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
