"""Giving the password up, and getting one back with a recovery code.

What these cover is the surface either side of the change: what an account has
to hold before it may let its password go, what happens to the sessions and the
device it was done from, and the one answer every refused recovery gets.
"""

import pytest
from httpx import AsyncClient, Response
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.messages import PasswordMessages
from app.core.security import (
    REFRESH_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    get_password_hash,
)
from app.models.platform.audit_event import AuditEvent
from app.models.platform.auth_session import AuthSession
from app.models.platform.user import User, UserStatus
from app.models.platform.user_passkey import UserPasskey
from app.services import email as email_service
from app.services.auth import sessions as session_service
from app.services.auth import totp as totp_service
from app.services.platform import app_settings as app_settings_service
from app.testing import create_user, get_auth_headers

pytestmark = [pytest.mark.integration, pytest.mark.auth]

PASSWORD = "correct-horse-battery-staple"
NEW_PASSWORD = "a-different-horse-entirely"

REMOVE = "/api/v1/auth/password/remove"
RECOVER = "/api/v1/auth/password/recover"


async def _account(
    session: AsyncSession,
    email: str,
    *,
    password: str | None = PASSWORD,
    status: UserStatus = UserStatus.active,
) -> User:
    return await create_user(
        session,
        email=email,
        hashed_password=get_password_hash(password) if password else None,
        status=status,
        email_verified=True,
    )


async def _seed_passkey(
    session: AsyncSession, user: User, *, credential_id: str = "way-in"
) -> UserPasskey:
    """A registered credential, written straight in.

    The ceremony belongs to the library and is covered where it is run; what
    matters here is only that the account holds one.
    """
    row = UserPasskey(
        user_id=user.id,
        credential_id=f"{credential_id}-{user.id}".encode(),
        public_key=b"public-key-bytes",
        rp_id="localhost",
        sign_count=0,
        transports=["internal"],
        name="Laptop",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def _withdraw_passkeys(session: AsyncSession) -> None:
    """Leave the deployment permitting the other three."""
    row = await app_settings_service.get_app_settings(session)
    row.login_methods = ["password", "sso", "totp"]
    session.add(row)
    await session.commit()


async def _issue_codes(session: AsyncSession, user: User) -> list[str]:
    codes = await totp_service.issue_recovery_codes(session, user_id=user.id)
    await session.commit()
    return codes


async def _another_session(session: AsyncSession, user: User) -> AuthSession:
    issued = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[]
    )
    await session.commit()
    return issued.session


async def _sign_in(
    client: AsyncClient, email: str, password: str = PASSWORD
) -> Response:
    return await client.post(
        "/api/v1/auth/token", data={"username": email, "password": password}
    )


async def _events(
    session: AsyncSession, user_id: int, event_type: AuditEventType
) -> list[AuditEvent]:
    """Every record of one kind naming this account, as actor or as target.

    A refused recovery is unauthenticated, so the account it named is the
    target rather than the actor; a change the account made itself is the
    other way round.
    """
    session.expire_all()
    rows = (
        await session.exec(
            select(AuditEvent).where(AuditEvent.event_type == event_type.value)
        )
    ).all()
    return [row for row in rows if user_id in (row.actor_user_id, row.target_user_id)]


# ---------------------------------------------------------------------------
# Giving the password up
# ---------------------------------------------------------------------------


async def test_the_only_way_in_stays(client: AsyncClient, session: AsyncSession):
    """An account with nothing else to sign in with keeps its password."""
    user = await _account(session, "pl-only@example.com")

    response = await client.post(
        REMOVE, json={"current_password": PASSWORD}, headers=get_auth_headers(user)
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "PASSWORD_IS_LAST_METHOD"


async def test_removing_re_checks_the_password(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(session, "pl-wrongpw@example.com")
    await _seed_passkey(session, user)

    response = await client.post(
        REMOVE, json={"current_password": "not-it"}, headers=get_auth_headers(user)
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "USER_CURRENT_PASSWORD_INCORRECT"


async def test_an_account_holding_none_has_nothing_to_remove(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(session, "pl-nopw@example.com", password=None)
    await _seed_passkey(session, user)

    response = await client.post(
        REMOVE, json={"current_password": PASSWORD}, headers=get_auth_headers(user)
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "PASSWORD_NOT_HELD"


async def test_a_credential_the_deployment_withdrew_is_not_a_way_in(
    client: AsyncClient, session: AsyncSession
):
    """The account holds a passkey, but this deployment stopped accepting
    them — so the password is again all it has."""
    user = await _account(session, "pl-withdrawn@example.com")
    await _seed_passkey(session, user)
    await _withdraw_passkeys(session)

    response = await client.post(
        REMOVE, json={"current_password": PASSWORD}, headers=get_auth_headers(user)
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "PASSWORD_IS_LAST_METHOD"


async def test_removing_keeps_this_device_signed_in(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(session, "pl-remove@example.com")
    user_id = user.id
    version_before = user.token_version
    await _seed_passkey(session, user)
    elsewhere_id = (await _another_session(session, user)).id

    # A real sign-in, so the session this is done from is one the server wrote.
    assert (await _sign_in(client, "pl-remove@example.com")).status_code == 200

    response = await client.post(REMOVE, json={"current_password": PASSWORD})
    assert response.status_code == 200, response.text
    assert len(response.json()["codes"]) == totp_service.RECOVERY_CODE_COUNT
    assert SESSION_COOKIE_NAME in response.cookies
    assert REFRESH_COOKIE_NAME in response.cookies

    # The caller carries on, on the cookies the answer set.
    mine = await client.get("/api/v1/users/me")
    assert mine.status_code == 200, mine.text
    assert mine.json()["id"] == user_id

    session.expire_all()
    account = await session.get(User, user_id)
    assert account is not None
    assert account.hashed_password is None
    assert account.password_set_at is None
    assert account.token_version == version_before + 1

    rows = (
        await session.exec(select(AuthSession).where(AuthSession.user_id == user_id))
    ).all()
    live = [row for row in rows if row.revoked_at is None]
    assert len(live) == 1
    # What this device had already proved carries into the one that replaces it.
    assert live[0].amr == ["pwd"]
    assert live[0].id != elsewhere_id

    assert (
        len(await _events(session, user_id, AuditEventType.AUTH_PASSWORD_REMOVED)) == 1
    )
    assert (
        len(await _events(session, user_id, AuditEventType.AUTH_RECOVERY_CODES_ISSUED))
        == 1
    )


async def test_an_account_that_already_holds_codes_keeps_them(
    client: AsyncClient, session: AsyncSession
):
    """The set is issued at the moment the account becomes passwordless only if
    it has none. One that is enrolled already has a set, and it is still good."""
    user = await _account(session, "pl-hascodes@example.com")
    user_id = user.id
    await _seed_passkey(session, user)
    await _issue_codes(session, user)

    response = await client.post(
        REMOVE, json={"current_password": PASSWORD}, headers=get_auth_headers(user)
    )
    assert response.status_code == 200, response.text
    assert response.json()["codes"] == []

    session.expire_all()
    assert (
        await totp_service.remaining_recovery_codes(session, user_id=user_id)
        == totp_service.RECOVERY_CODE_COUNT
    )


async def test_the_letter_says_the_password_is_gone(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    sent: list[int] = []

    async def record(_session, user, *args, **kwargs) -> None:
        sent.append(user.id)

    monkeypatch.setattr(email_service, "send_password_removed_email", record)

    user = await _account(session, "pl-letter@example.com")
    await _seed_passkey(session, user)

    response = await client.post(
        REMOVE, json={"current_password": PASSWORD}, headers=get_auth_headers(user)
    )
    assert response.status_code == 200, response.text
    assert sent == [user.id]


async def test_a_letter_that_cannot_go_does_not_undo_the_removal(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """A deployment with no mail configured still made the change."""

    async def fail(*args, **kwargs) -> None:
        raise RuntimeError("no mail")

    monkeypatch.setattr(email_service, "send_password_removed_email", fail)

    user = await _account(session, "pl-nomail@example.com")
    user_id = user.id
    await _seed_passkey(session, user)

    response = await client.post(
        REMOVE, json={"current_password": PASSWORD}, headers=get_auth_headers(user)
    )
    assert response.status_code == 200, response.text

    session.expire_all()
    account = await session.get(User, user_id)
    assert account is not None
    assert account.hashed_password is None


# ---------------------------------------------------------------------------
# Getting one back with a recovery code
# ---------------------------------------------------------------------------


async def test_an_account_holding_a_password_recovers_by_mail_instead(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(session, "pl-haspw@example.com")
    codes = await _issue_codes(session, user)

    response = await client.post(
        RECOVER,
        json={
            "email": "pl-haspw@example.com",
            "recovery_code": codes[0],
            "password": NEW_PASSWORD,
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "RECOVERY_CODE_INVALID"


async def test_an_address_nobody_holds_gets_the_same_answer(client: AsyncClient):
    response = await client.post(
        RECOVER,
        json={
            "email": "nobody@example.com",
            "recovery_code": "aaaaa-bbbbb-ccccc-ddddd",
            "password": NEW_PASSWORD,
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "RECOVERY_CODE_INVALID"


async def test_a_code_that_does_not_match_is_written_down(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(session, "pl-badcode@example.com", password=None)
    user_id = user.id
    await _issue_codes(session, user)

    response = await client.post(
        RECOVER,
        json={
            "email": "pl-badcode@example.com",
            "recovery_code": "aaaaa-bbbbb-ccccc-ddddd",
            "password": NEW_PASSWORD,
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "RECOVERY_CODE_INVALID"

    refusals = await _events(session, user_id, AuditEventType.AUTH_SECOND_FACTOR_FAILED)
    assert len(refusals) == 1
    assert refusals[0].target_user_id == user_id
    assert refusals[0].envelope["detail"] == {
        "method": "recovery_code",
        "during": "recover",
    }


async def test_an_account_that_is_not_active_cannot_recover(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(
        session,
        "pl-inactive@example.com",
        password=None,
        status=UserStatus.deactivated,
    )
    user_id = user.id
    codes = await _issue_codes(session, user)

    response = await client.post(
        RECOVER,
        json={
            "email": "pl-inactive@example.com",
            "recovery_code": codes[0],
            "password": NEW_PASSWORD,
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "RECOVERY_CODE_INVALID"

    session.expire_all()
    # The code was not spent: nothing about the account changed.
    assert (
        await totp_service.remaining_recovery_codes(session, user_id=user_id)
        == totp_service.RECOVERY_CODE_COUNT
    )


async def test_the_policy_runs_before_the_code_is_spent(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(session, "pl-policy@example.com", password=None)
    user_id = user.id
    codes = await _issue_codes(session, user)

    response = await client.post(
        RECOVER,
        json={
            "email": "pl-policy@example.com",
            "recovery_code": codes[0],
            "password": "short",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == PasswordMessages.TOO_SHORT

    session.expire_all()
    assert (
        await totp_service.remaining_recovery_codes(session, user_id=user_id)
        == totp_service.RECOVERY_CODE_COUNT
    )


async def test_recovering_sets_the_password_and_clears_the_sessions(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(session, "pl-recover@example.com", password=None)
    user_id = user.id
    codes = await _issue_codes(session, user)
    elsewhere_id = (await _another_session(session, user)).id

    response = await client.post(
        RECOVER,
        json={
            "email": "pl-recover@example.com",
            "recovery_code": codes[0],
            "password": NEW_PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "reset"

    session.expire_all()
    assert (
        await totp_service.remaining_recovery_codes(session, user_id=user_id)
        == totp_service.RECOVERY_CODE_COUNT - 1
    )
    retired = await session.get(AuthSession, elsewhere_id)
    assert retired is not None
    assert retired.revoked_at is not None

    used = await _events(session, user_id, AuditEventType.AUTH_RECOVERY_CODE_USED)
    assert len(used) == 1
    assert used[0].envelope["detail"]["remaining"] == (
        totp_service.RECOVERY_CODE_COUNT - 1
    )
    changed = await _events(session, user_id, AuditEventType.AUTH_PASSWORD_CHANGED)
    assert len(changed) == 1
    assert changed[0].envelope["detail"] == {"via": "recovery_code"}

    # No session was opened here; the password is what signs the account in.
    signed_in = await _sign_in(client, "pl-recover@example.com", NEW_PASSWORD)
    assert signed_in.status_code == 200, signed_in.text
