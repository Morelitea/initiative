"""Enrolling a factor, and signing in against it."""

from datetime import datetime, timedelta, timezone

import pyotp
import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import get_password_hash
from app.models.platform.user import UserStatus
from app.services.auth import totp as totp_service
from app.testing import create_user, get_auth_headers

pytestmark = [pytest.mark.integration, pytest.mark.auth]

PASSWORD = "correct-horse-battery-staple"


def _next_code(secret: str) -> str:
    """The code for the interval after this one.

    Confirming an enrolment takes the interval its code came from, so a sign-in
    in the same thirty seconds cannot present that code again — which is the
    rule working, not a problem to route around. One interval ahead is inside
    the drift a clock is allowed and is still ahead of the recorded one.
    """
    at = datetime.now(timezone.utc) + timedelta(seconds=totp_service.TOTP_PERIOD)
    return pyotp.TOTP(secret).at(at)


async def _account(session: AsyncSession, email: str):
    return await create_user(
        session,
        email=email,
        hashed_password=get_password_hash(PASSWORD),
        status=UserStatus.active,
        email_verified=True,
    )


async def _sign_in(client: AsyncClient, email: str, password: str = PASSWORD):
    return await client.post(
        "/api/v1/auth/token", data={"username": email, "password": password}
    )


async def _enrol(client: AsyncClient, session: AsyncSession, email: str):
    """Enrol and confirm, returning (user, secret, recovery codes)."""
    user = await _account(session, email)
    headers = get_auth_headers(user)
    started = await client.post(
        "/api/v1/auth/totp/enroll",
        json={"current_password": PASSWORD},
        headers=headers,
    )
    assert started.status_code == 200, started.text
    secret = started.json()["secret"]
    confirmed = await client.post(
        "/api/v1/auth/totp/confirm",
        json={"code": pyotp.TOTP(secret).now()},
        headers=headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    return user, secret, confirmed.json()["codes"]


async def test_enrolling_hands_over_a_seed_and_a_uri(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(session, "enrol@example.com")
    response = await client.post(
        "/api/v1/auth/totp/enroll",
        json={"current_password": PASSWORD},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["secret"]
    assert body["otpauth_uri"].startswith("otpauth://totp/")
    assert f"secret={body['secret']}" in body["otpauth_uri"]


async def test_enrolling_re_checks_the_password(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(session, "enrol-pw@example.com")
    response = await client.post(
        "/api/v1/auth/totp/enroll",
        json={"current_password": "not-it"},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "USER_CURRENT_PASSWORD_INCORRECT"


async def test_an_unproved_enrolment_is_not_asked_for(
    client: AsyncClient, session: AsyncSession
):
    """Started and abandoned costs the account nothing — the sign-in is
    unchanged."""
    user = await _account(session, "abandoned@example.com")
    await client.post(
        "/api/v1/auth/totp/enroll",
        json={"current_password": PASSWORD},
        headers=get_auth_headers(user),
    )
    response = await _sign_in(client, "abandoned@example.com")
    assert response.status_code == 200
    assert "access_token" in response.json()


async def test_confirming_returns_the_recovery_codes_once(
    client: AsyncClient, session: AsyncSession
):
    _user, _secret, codes = await _enrol(client, session, "confirm@example.com")
    assert len(codes) == totp_service.RECOVERY_CODE_COUNT


async def test_status_reports_what_the_account_holds(
    client: AsyncClient, session: AsyncSession
):
    user, _secret, _codes = await _enrol(client, session, "status@example.com")
    response = await client.get("/api/v1/auth/totp", headers=get_auth_headers(user))
    assert response.status_code == 200
    body = response.json()
    assert body["enrolled"] is True
    assert body["confirmed_at"]
    assert body["recovery_codes_remaining"] == totp_service.RECOVERY_CODE_COUNT


async def test_signing_in_asks_for_the_code(client: AsyncClient, session: AsyncSession):
    await _enrol(client, session, "signin@example.com")
    response = await _sign_in(client, "signin@example.com")

    assert response.status_code == 401
    body = response.json()
    assert body["detail"] == "TOTP_REQUIRED"
    assert body["challenge"]
    assert "access_token" not in body


async def test_the_code_finishes_the_sign_in(
    client: AsyncClient, session: AsyncSession
):
    _user, secret, _codes = await _enrol(client, session, "answer@example.com")
    challenge = (await _sign_in(client, "answer@example.com")).json()["challenge"]

    response = await client.post(
        "/api/v1/auth/token/totp",
        json={"challenge": challenge, "code": _next_code(secret)},
    )
    assert response.status_code == 200, response.text
    assert response.json()["access_token"]


async def test_a_recovery_code_finishes_it_too(
    client: AsyncClient, session: AsyncSession
):
    _user, _secret, codes = await _enrol(client, session, "recover@example.com")
    challenge = (await _sign_in(client, "recover@example.com")).json()["challenge"]

    response = await client.post(
        "/api/v1/auth/token/totp",
        json={"challenge": challenge, "recovery_code": codes[0]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["access_token"]


async def test_a_wrong_code_leaves_the_challenge_standing(
    client: AsyncClient, session: AsyncSession
):
    _user, secret, _codes = await _enrol(client, session, "wrong@example.com")
    challenge = (await _sign_in(client, "wrong@example.com")).json()["challenge"]

    refused = await client.post(
        "/api/v1/auth/token/totp", json={"challenge": challenge, "code": "000000"}
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == "TOTP_INVALID"

    accepted = await client.post(
        "/api/v1/auth/token/totp",
        json={"challenge": challenge, "code": _next_code(secret)},
    )
    assert accepted.status_code == 200, accepted.text


async def test_a_challenge_is_spent_by_the_session_it_bought(
    client: AsyncClient, session: AsyncSession
):
    _user, secret, _codes = await _enrol(client, session, "spent@example.com")
    challenge = (await _sign_in(client, "spent@example.com")).json()["challenge"]
    code = _next_code(secret)

    first = await client.post(
        "/api/v1/auth/token/totp", json={"challenge": challenge, "code": code}
    )
    assert first.status_code == 200

    again = await client.post(
        "/api/v1/auth/token/totp", json={"challenge": challenge, "code": code}
    )
    assert again.status_code == 400
    assert again.json()["detail"] == "TOTP_CHALLENGE_INVALID"


async def test_a_challenge_nobody_issued_is_refused(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/token/totp",
        json={"challenge": "not-a-challenge", "code": "000000"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "TOTP_CHALLENGE_INVALID"


async def test_removing_it_asks_for_the_password_and_the_factor(
    client: AsyncClient, session: AsyncSession
):
    user, secret, _codes = await _enrol(client, session, "remove@example.com")
    headers = get_auth_headers(user)

    no_factor = await client.post(
        "/api/v1/auth/totp/disable",
        json={"current_password": PASSWORD, "code": "000000"},
        headers=headers,
    )
    assert no_factor.status_code == 400
    assert no_factor.json()["detail"] == "TOTP_INVALID"

    removed = await client.post(
        "/api/v1/auth/totp/disable",
        json={"current_password": PASSWORD, "code": _next_code(secret)},
        headers=headers,
    )
    assert removed.status_code == 204

    # And the sign-in stops asking.
    response = await _sign_in(client, "remove@example.com")
    assert response.status_code == 200


async def test_regenerating_retires_the_previous_codes(
    client: AsyncClient, session: AsyncSession
):
    user, _secret, codes = await _enrol(client, session, "regen@example.com")
    headers = get_auth_headers(user)

    fresh = await client.post(
        "/api/v1/auth/recovery-codes/regenerate",
        json={"current_password": PASSWORD},
        headers=headers,
    )
    assert fresh.status_code == 200
    assert set(fresh.json()["codes"]).isdisjoint(codes)

    challenge = (await _sign_in(client, "regen@example.com")).json()["challenge"]
    stale = await client.post(
        "/api/v1/auth/token/totp",
        json={"challenge": challenge, "recovery_code": codes[0]},
    )
    assert stale.status_code == 400
    assert stale.json()["detail"] == "RECOVERY_CODE_INVALID"


async def test_an_account_without_a_factor_signs_in_unchanged(
    client: AsyncClient, session: AsyncSession
):
    await _account(session, "plain@example.com")
    response = await _sign_in(client, "plain@example.com")
    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_support_can_clear_a_lost_factor(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The lost-phone path: somebody with the run of platform accounts takes
    the factor off, and the account signs in with its password again."""
    user, _secret, _codes = await _enrol(client, session, "lostphone@example.com")
    staff = await acting_user("moderator")

    response = await client.delete(
        f"/api/v1/admin/users/{user.id}/second-factor", headers=staff.headers
    )
    assert response.status_code == 204, response.text

    signed_in = await _sign_in(client, "lostphone@example.com")
    assert signed_in.status_code == 200
    assert signed_in.json()["access_token"]


async def test_clearing_a_factor_is_not_for_everybody(
    client: AsyncClient, session: AsyncSession, acting_user
):
    user, _secret, _codes = await _enrol(client, session, "notyours@example.com")
    bystander = await acting_user("support")

    response = await client.delete(
        f"/api/v1/admin/users/{user.id}/second-factor", headers=bystander.headers
    )
    assert response.status_code == 403

    # And the factor is still being asked for.
    assert (await _sign_in(client, "notyours@example.com")).status_code == 401
