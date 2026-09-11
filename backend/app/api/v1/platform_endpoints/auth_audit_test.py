"""Authentication reaches the audit log.

The pipeline already existed — a versioned envelope, a tier, a shipper-ready
index — and carried five moderation events and nothing from auth. These pin the
sign-in family to it: what is recorded, what is deliberately not, and that the
detail says which way somebody got in.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditCategory, AuditEventType, meta_for
from app.models.platform.audit_event import AuditEvent
from app.models.platform.user import UserStatus
from app.testing.factories import create_user, get_auth_headers

pytestmark = [pytest.mark.integration, pytest.mark.auth]

PASSWORD = "testpassword123"


async def _events(
    session: AsyncSession, event_type: AuditEventType
) -> list[AuditEvent]:
    session.expire_all()
    return list(
        (
            await session.exec(
                select(AuditEvent)
                .where(AuditEvent.event_type == event_type.value)
                .order_by(AuditEvent.id)
            )
        ).all()
    )


async def _sign_in(client: AsyncClient, email: str, password: str = PASSWORD):
    return await client.post(
        "/api/v1/auth/token", data={"username": email, "password": password}
    )


async def test_a_sign_in_is_recorded_with_its_method(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="signin-audit@example.com")
    user_id = user.id
    assert (await _sign_in(client, "signin-audit@example.com")).status_code == 200

    rows = await _events(session, AuditEventType.AUTH_SIGNED_IN)
    assert [r.actor_user_id for r in rows] == [user_id]
    assert rows[0].envelope["detail"] == {"method": "password"}
    assert rows[0].tier == meta_for(AuditEventType.AUTH_SIGNED_IN).tier


async def test_a_refused_sign_in_is_recorded_with_its_reason(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="badpass-audit@example.com")
    user_id = user.id
    response = await _sign_in(client, "badpass-audit@example.com", "not-the-password")
    assert response.status_code == 400

    rows = await _events(session, AuditEventType.AUTH_SIGN_IN_FAILED)
    assert [r.actor_user_id for r in rows] == [user_id]
    assert rows[0].envelope["detail"]["reason"] == "bad_password"
    # A refusal changed nothing, so it is not a write.
    assert rows[0].envelope["is_write"] is False


async def test_an_inactive_account_is_recorded_separately_from_a_wrong_password(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(
        session, email="inactive-audit@example.com", status=UserStatus.deactivated
    )
    user_id = user.id
    assert (await _sign_in(client, "inactive-audit@example.com")).status_code == 400

    rows = await _events(session, AuditEventType.AUTH_SIGN_IN_FAILED)
    assert [r.actor_user_id for r in rows] == [user_id]
    assert rows[0].envelope["detail"]["reason"] == "inactive"


async def test_an_address_nobody_holds_is_not_written_down(
    client: AsyncClient, session: AsyncSession
):
    """A refusal that resolved to no account is not an action on anybody, and
    recording it would put an unowned address in the log."""
    before = len(await _events(session, AuditEventType.AUTH_SIGN_IN_FAILED))
    response = await _sign_in(client, "nobody-at-all@example.com")
    assert response.status_code == 400

    assert len(await _events(session, AuditEventType.AUTH_SIGN_IN_FAILED)) == before


async def test_signing_out_is_recorded(client: AsyncClient, session: AsyncSession):
    user = await create_user(session, email="signout-audit@example.com")
    user_id = user.id
    response = await client.post("/api/v1/auth/logout", headers=get_auth_headers(user))
    assert response.status_code == 204

    rows = await _events(session, AuditEventType.AUTH_SIGNED_OUT)
    assert [r.actor_user_id for r in rows] == [user_id]


async def test_changing_a_password_is_recorded_with_how(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="pwchange-audit@example.com")
    user_id = user.id
    response = await client.patch(
        "/api/v1/users/me",
        headers=get_auth_headers(user),
        json={"current_password": PASSWORD, "password": "a-new-longer-secret-1"},
    )
    assert response.status_code == 200

    rows = await _events(session, AuditEventType.AUTH_PASSWORD_CHANGED)
    assert [r.actor_user_id for r in rows] == [user_id]
    assert rows[0].envelope["detail"] == {"via": "self_service"}


async def test_a_reset_is_recorded_as_a_reset(
    client: AsyncClient, session: AsyncSession
):
    from app.models.platform.user_token import UserTokenPurpose
    from app.services.platform import user_tokens

    user = await create_user(session, email="pwreset-audit@example.com")
    token = await user_tokens.create_token(
        session, user_id=user.id, purpose=UserTokenPurpose.password_reset
    )
    response = await client.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "password": "another-longer-secret-1"},
    )
    assert response.status_code == 200

    rows = await _events(session, AuditEventType.AUTH_PASSWORD_CHANGED)
    assert [r.envelope["detail"]["via"] for r in rows] == ["reset"]


async def test_every_auth_event_is_filed_under_authentication():
    """The board groups by category, so a new member filed under the wrong one
    disappears from the view it belongs to."""
    auth_events = [e for e in AuditEventType if e.value.startswith("auth.")]
    assert auth_events
    for event_type in auth_events:
        assert meta_for(event_type).category is AuditCategory.AUTHENTICATION
