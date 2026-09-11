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

from app.api.v1.platform_endpoints.auth_test import (
    _enable_platform_oidc,
    _run_oidc_flow,
    _wire_fake_idp,
)
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
    # The account is what the attempt was against, not who made it: the
    # request is unauthenticated, so there is no actor to name.
    assert [r.actor_user_id for r in rows] == [None]
    assert [r.target_user_id for r in rows] == [user_id]
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
    assert [r.actor_user_id for r in rows] == [None]
    assert [r.target_user_id for r in rows] == [user_id]
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


async def test_a_replayed_refresh_token_is_recorded_against_its_owner(
    client: AsyncClient, session: AsyncSession
):
    """The rejection kills the whole chain, so the record has to be able to say
    whose chain it was — there is no issued session to read it from, which is
    why ``RotationResult`` carries the id."""
    from app.core.security import REFRESH_COOKIE_NAME

    user = await create_user(session, email="replay-audit@example.com")
    user_id = user.id
    signed_in = await _sign_in(client, "replay-audit@example.com")
    assert signed_in.status_code == 200
    spent = client.cookies.get(REFRESH_COOKIE_NAME)
    assert spent

    # Spend it once — which rotates the cookie — then put the spent one back.
    assert (await client.post("/api/v1/auth/refresh")).status_code == 200
    client.cookies.set(REFRESH_COOKIE_NAME, spent)
    replayed = await client.post("/api/v1/auth/refresh")
    assert replayed.status_code == 401

    rows = await _events(session, AuditEventType.AUTH_REFRESH_REUSE_DETECTED)
    # The endpoint is authorised by the cookie alone and has just rejected it,
    # so the owner of the chain is the target, not the one who presented it.
    assert [r.actor_user_id for r in rows] == [None]
    assert [r.target_user_id for r in rows] == [user_id]


async def test_an_unauthenticated_event_reads_back_with_no_party(
    client: AsyncClient, session: AsyncSession
):
    """The board renders the actor column from this field, so an event nobody
    signed in caused has to survive the read as no party rather than a stray
    id."""
    from app.models.platform.user import UserRole
    from app.schemas.platform.audit import AuditEventRead

    await create_user(session, email="noparty-audit@example.com")
    assert (
        await _sign_in(client, "noparty-audit@example.com", "wrong")
    ).status_code == 400

    owner = await create_user(session, role=UserRole.owner)
    listing = await client.get(
        "/api/v1/admin/audit-events",
        headers=get_auth_headers(owner),
        params={"event_type": AuditEventType.AUTH_SIGN_IN_FAILED.value},
    )
    assert listing.status_code == 200
    items = [AuditEventRead(**item) for item in listing.json()["items"]]
    assert items
    assert items[0].actor is None
    assert items[0].target_user is not None


async def test_an_oidc_sign_in_records_its_provider_and_whether_it_stepped_up(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    from app.services.auth.platform_provider import PLATFORM_OIDC_SLUG
    from app.testing.oidc import FakeIdp

    await _enable_platform_oidc(session)
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    response = await _run_oidc_flow(
        client,
        idp,
        id_token_claims={
            "email": "oidc-audit@example.com",
            "username": "oidc-audit",
            "email_verified": True,
        },
    )
    assert response.status_code in (302, 307)

    rows = await _events(session, AuditEventType.AUTH_SIGNED_IN)
    assert [r.envelope["detail"] for r in rows] == [
        {"method": "oidc", "provider": PLATFORM_OIDC_SLUG, "step_up": False}
    ]
    assert rows[0].actor_user_id is not None


async def test_an_oidc_sign_in_records_what_the_idp_asserted_about_it(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The methods and context class the provider named ride the record, so a
    reviewer reading the log can tell a second factor was used and when."""
    from app.services.auth.platform_provider import PLATFORM_OIDC_SLUG
    from app.testing.oidc import FakeIdp

    await _enable_platform_oidc(session)
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    response = await _run_oidc_flow(
        client,
        idp,
        id_token_claims={
            "email": "oidc-amr@example.com",
            "username": "oidc-amr",
            "email_verified": True,
            "amr": ["pwd", "mfa"],
            "acr": "phr",
            "auth_time": 1757600000,
        },
    )
    assert response.status_code in (302, 307)

    rows = await _events(session, AuditEventType.AUTH_SIGNED_IN)
    assert [r.envelope["detail"] for r in rows] == [
        {
            "method": "oidc",
            "provider": PLATFORM_OIDC_SLUG,
            "step_up": False,
            "auth_time": 1757600000,
            "amr": ["pwd", "mfa"],
            "acr": "phr",
        }
    ]


async def test_claiming_an_existing_account_by_verified_email_is_recorded(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The link is what makes every later sign-in resolve by subject, so the
    moment an identity provider claims an existing account is worth a record."""
    from app.testing.oidc import FakeIdp

    await _enable_platform_oidc(session)
    existing = await create_user(session, email="claimed-audit@example.com")
    existing_id = existing.id
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    response = await _run_oidc_flow(
        client,
        idp,
        id_token_claims={
            "email": "claimed-audit@example.com",
            "username": "claimed-audit",
            "email_verified": True,
        },
    )
    assert response.status_code in (302, 307)

    rows = await _events(session, AuditEventType.AUTH_IDENTITY_LINKED)
    assert [r.actor_user_id for r in rows] == [existing_id]
    assert rows[0].envelope["detail"]["matched_by"] == "verified_email"
