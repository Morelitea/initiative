"""Registering, naming and removing a passkey.

The ceremony arithmetic belongs to the library and is stood in for here: what
these cover is the surface around it — the password re-check, the challenge
that stands for exactly one registration, whose account a credential lands on,
and what the account is told afterwards.
"""

import json
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
import webauthn
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from webauthn.helpers import bytes_to_base64url

from app.core.audit_events import AuditEventType
from app.core.security import get_password_hash
from app.models.platform.audit_event import AuditEvent
from app.models.platform.auth_challenge import AuthChallenge
from app.models.platform.user import User, UserStatus
from app.models.platform.user_passkey import UserPasskey
from app.services import email as email_service
from app.services.auth import passkeys as passkey_service
from app.testing import create_user, get_auth_headers

pytestmark = [pytest.mark.integration, pytest.mark.auth]

PASSWORD = "correct-horse-battery-staple"

BEGIN = "/api/v1/auth/passkeys/register/begin"
FINISH = "/api/v1/auth/passkeys/register/finish"


def _verifier(**kwargs):
    """Stand in for the library's registration check.

    It answers with what a real ceremony reports, keyed off the credential id
    the request carried so two registrations are two credentials.
    """
    credential = kwargs["credential"]
    assert kwargs["expected_rp_id"] == passkey_service.relying_party_id()
    assert kwargs["expected_origin"] == passkey_service.expected_origin()
    raw_id = credential.get("rawId") or credential.get("id") or ""
    return SimpleNamespace(
        credential_id=webauthn.base64url_to_bytes(raw_id),
        credential_public_key=b"public-key-bytes",
        sign_count=0,
        aaguid="00000000-0000-0000-0000-000000000000",
        user_verified=True,
        credential_backed_up=True,
    )


@pytest.fixture
def ceremony(monkeypatch):
    monkeypatch.setattr(
        passkey_service.webauthn, "verify_registration_response", _verifier
    )


def _credential(challenge: str, *, credential_id: str = "credential-one") -> dict:
    """What the browser hands back, with the challenge inside the client data
    it signed — which is where the server reads it from."""
    raw_id = bytes_to_base64url(credential_id.encode())
    client_data = json.dumps(
        {
            "type": "webauthn.create",
            "challenge": challenge,
            "origin": "http://localhost:5173",
        }
    ).encode()
    return {
        "id": raw_id,
        "rawId": raw_id,
        "type": "public-key",
        "response": {
            "clientDataJSON": bytes_to_base64url(client_data),
            "attestationObject": bytes_to_base64url(b"attestation"),
            "transports": ["internal", "hybrid"],
        },
    }


async def _account(session: AsyncSession, email: str) -> User:
    return await create_user(
        session,
        email=email,
        hashed_password=get_password_hash(PASSWORD),
        status=UserStatus.active,
        email_verified=True,
    )


async def _begin(client: AsyncClient, user: User, *, name: str = "Laptop") -> str:
    """Begin a registration and hand back the challenge the options carry."""
    response = await client.post(
        BEGIN,
        json={"current_password": PASSWORD, "name": name},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 200, response.text
    return response.json()["options"]["challenge"]


async def _register(
    client: AsyncClient,
    user: User,
    *,
    name: str = "Laptop",
    credential_id: str = "credential-one",
) -> dict:
    challenge = await _begin(client, user, name=name)
    response = await client.post(
        FINISH,
        json={
            "credential": _credential(challenge, credential_id=credential_id),
            "name": name,
        },
        headers=get_auth_headers(user),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _seed(session: AsyncSession, user: User, count: int) -> None:
    for index in range(count):
        await passkey_service.store(
            session,
            user_id=user.id,
            registered=passkey_service.RegisteredCredential(
                credential_id=f"seeded-{user.id}-{index}".encode(),
                public_key=b"public-key-bytes",
                sign_count=0,
                aaguid=None,
                user_verified=True,
                backed_up=False,
                transports=["internal"],
            ),
            name=f"Key {index}",
        )
    await session.commit()


# ---------------------------------------------------------------------------
# What the account holds
# ---------------------------------------------------------------------------


async def test_an_account_with_none_is_told_what_it_would_take(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(session, "pk-empty@example.com")
    response = await client.get("/api/v1/auth/passkeys", headers=get_auth_headers(user))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["passkeys"] == []
    assert body["password_required"] is True
    assert body["limit"] == passkey_service.MAX_PASSKEYS_PER_USER
    assert body["site_supported"] is True


async def test_the_list_says_when_this_address_cannot_carry_one(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The deployment's own address decides this, so the server answers it
    rather than leaving the browser to."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", "http://intranet.local")
    user = await _account(session, "pk-unsupported@example.com")

    response = await client.get("/api/v1/auth/passkeys", headers=get_auth_headers(user))
    assert response.status_code == 200, response.text
    assert response.json()["site_supported"] is False


async def test_an_account_with_no_password_is_not_asked_for_one(
    client: AsyncClient, session: AsyncSession
):
    """Provisioned through an identity provider: there is no password to
    re-check, so the form does not ask for one."""
    user = await create_user(
        session,
        email="pk-nopassword@example.com",
        hashed_password=None,
        status=UserStatus.active,
    )
    response = await client.get("/api/v1/auth/passkeys", headers=get_auth_headers(user))
    assert response.status_code == 200, response.text
    assert response.json()["password_required"] is False


async def test_the_list_reads_oldest_first(
    client: AsyncClient, session: AsyncSession, ceremony
):
    user = await _account(session, "pk-order@example.com")
    await _register(client, user, name="First", credential_id="credential-one")
    await _register(client, user, name="Second", credential_id="credential-two")

    response = await client.get("/api/v1/auth/passkeys", headers=get_auth_headers(user))
    assert response.status_code == 200, response.text
    assert [row["name"] for row in response.json()["passkeys"]] == ["First", "Second"]


# ---------------------------------------------------------------------------
# Beginning
# ---------------------------------------------------------------------------


async def test_beginning_asks_for_the_password(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(session, "pk-nopw@example.com")
    response = await client.post(
        BEGIN, json={"name": "Laptop"}, headers=get_auth_headers(user)
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "USER_CURRENT_PASSWORD_REQUIRED"


async def test_beginning_refuses_the_wrong_password(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(session, "pk-wrongpw@example.com")
    response = await client.post(
        BEGIN,
        json={"current_password": "not-it", "name": "Laptop"},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "USER_CURRENT_PASSWORD_INCORRECT"


async def test_a_name_this_deployment_will_not_keep_is_refused_here(
    client: AsyncClient, session: AsyncSession
):
    """The same name rule the finish route holds, applied before a ceremony is
    begun — so nothing is issued for a name that will not be stored."""
    user = await _account(session, "pk-sigil@example.com")
    user_id = user.id

    response = await client.post(
        BEGIN,
        json={"current_password": PASSWORD, "name": "Laptop #1"},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 422, response.text
    assert "RESERVED_SIGIL_IN_NAME" in response.text

    session.expire_all()
    challenges = (
        await session.exec(
            select(AuthChallenge).where(AuthChallenge.user_id == user_id)
        )
    ).all()
    assert challenges == []


async def test_a_plain_name_begins_a_ceremony(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(session, "pk-plainname@example.com")
    user_id = user.id

    response = await client.post(
        BEGIN,
        json={"current_password": PASSWORD, "name": "Laptop"},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 200, response.text

    session.expire_all()
    challenges = (
        await session.exec(
            select(AuthChallenge).where(AuthChallenge.user_id == user_id)
        )
    ).all()
    assert len(challenges) == 1


async def test_the_options_name_this_deployment(
    client: AsyncClient, session: AsyncSession
):
    from app.core.config import settings

    user = await _account(session, "pk-options@example.com")
    response = await client.post(
        BEGIN,
        json={"current_password": PASSWORD, "name": "Laptop"},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 200, response.text
    options = response.json()["options"]
    assert options["rp"]["id"] == urlsplit(settings.APP_URL).hostname
    assert options["challenge"]


async def test_a_deployment_on_plain_http_cannot_begin_one(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """A credential is bound to a named host reached over https, so a
    deployment addressed otherwise says so instead of sending options the
    browser will not answer."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", "http://intranet.local")
    user = await _account(session, "pk-http@example.com")

    response = await client.post(
        BEGIN,
        json={"current_password": PASSWORD, "name": "Laptop"},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "PASSKEY_SITE_UNSUPPORTED"


async def test_an_account_at_the_limit_cannot_begin_another(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(session, "pk-limit@example.com")
    await _seed(session, user, passkey_service.MAX_PASSKEYS_PER_USER)

    response = await client.post(
        BEGIN,
        json={"current_password": PASSWORD, "name": "Laptop"},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "PASSKEY_LIMIT_REACHED"


# ---------------------------------------------------------------------------
# Finishing
# ---------------------------------------------------------------------------


async def test_a_challenge_nobody_issued_is_refused(
    client: AsyncClient, session: AsyncSession, ceremony
):
    user = await _account(session, "pk-unknown@example.com")
    response = await client.post(
        FINISH,
        json={"credential": _credential("never-issued"), "name": "Laptop"},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "PASSKEY_REGISTRATION_INVALID"


async def test_finishing_keeps_the_credential(
    client: AsyncClient, session: AsyncSession, ceremony
):
    user = await _account(session, "pk-keep@example.com")
    user_id = user.id
    body = await _register(client, user, name="Work laptop")

    assert body["name"] == "Work laptop"
    assert body["backed_up"] is True
    assert body["user_verified"] is True
    assert body["transports"] == ["internal", "hybrid"]

    session.expire_all()
    rows = (
        await session.exec(select(UserPasskey).where(UserPasskey.user_id == user_id))
    ).all()
    assert len(rows) == 1
    assert rows[0].rp_id == passkey_service.relying_party_id()
    assert rows[0].name == "Work laptop"


async def test_only_the_transports_webauthn_names_are_kept(
    client: AsyncClient, session: AsyncSession, ceremony
):
    """The list arrives from the client and is handed back to a browser later,
    so what is kept is what the specification names."""
    user = await _account(session, "pk-transports@example.com")
    challenge = await _begin(client, user)
    credential = _credential(challenge)
    credential["response"]["transports"] = ["usb", "nonsense", 123, "<b>x</b>"]

    response = await client.post(
        FINISH,
        json={"credential": credential, "name": "Key"},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 201, response.text
    assert response.json()["transports"] == ["usb"]


async def test_registering_is_recorded(
    client: AsyncClient, session: AsyncSession, ceremony
):
    user = await _account(session, "pk-audit@example.com")
    user_id = user.id
    body = await _register(client, user)

    session.expire_all()
    events = (
        await session.exec(
            select(AuditEvent).where(
                AuditEvent.actor_user_id == user_id,
                AuditEvent.event_type == AuditEventType.AUTH_PASSKEY_REGISTERED.value,
            )
        )
    ).all()
    assert len(events) == 1
    detail = events[0].envelope["detail"]
    assert detail["passkey_id"] == body["id"]
    assert detail["backed_up"] is True
    assert detail["user_verified"] is True
    # The credential and its key are never in the record.
    assert "credential_id" not in detail
    assert "public_key" not in detail


async def test_a_challenge_answers_one_registration(
    client: AsyncClient, session: AsyncSession, ceremony
):
    user = await _account(session, "pk-once@example.com")
    user_id = user.id
    challenge = await _begin(client, user)
    credential = _credential(challenge)

    first = await client.post(
        FINISH,
        json={"credential": credential, "name": "Laptop"},
        headers=get_auth_headers(user),
    )
    assert first.status_code == 201, first.text

    again = await client.post(
        FINISH,
        json={"credential": credential, "name": "Laptop again"},
        headers=get_auth_headers(user),
    )
    assert again.status_code == 400
    assert again.json()["detail"] == "PASSKEY_REGISTRATION_INVALID"

    session.expire_all()
    rows = (
        await session.exec(select(UserPasskey).where(UserPasskey.user_id == user_id))
    ).all()
    assert len(rows) == 1


async def test_a_challenge_belongs_to_the_account_that_began_it(
    client: AsyncClient, session: AsyncSession, ceremony
):
    """A credential lands on the account whose ceremony it answers, and on no
    other."""
    one = await _account(session, "pk-mine@example.com")
    two = await _account(session, "pk-theirs@example.com")
    challenge = await _begin(client, one)

    response = await client.post(
        FINISH,
        json={"credential": _credential(challenge), "name": "Laptop"},
        headers=get_auth_headers(two),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "PASSKEY_REGISTRATION_INVALID"

    session.expire_all()
    rows = (await session.exec(select(UserPasskey))).all()
    assert rows == []


async def test_a_ceremony_that_does_not_verify_is_refused(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    def refuse(**kwargs):
        raise ValueError("the ceremony did not verify")

    monkeypatch.setattr(
        passkey_service.webauthn, "verify_registration_response", refuse
    )
    user = await _account(session, "pk-unverified@example.com")
    challenge = await _begin(client, user)

    response = await client.post(
        FINISH,
        json={"credential": _credential(challenge), "name": "Laptop"},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "PASSKEY_REGISTRATION_INVALID"


# ---------------------------------------------------------------------------
# Naming and removing
# ---------------------------------------------------------------------------


async def test_renaming_changes_only_the_name(
    client: AsyncClient, session: AsyncSession, ceremony
):
    user = await _account(session, "pk-rename@example.com")
    body = await _register(client, user, name="Laptop")

    response = await client.patch(
        f"/api/v1/auth/passkeys/{body['id']}",
        json={"name": "Desk key"},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Desk key"
    assert response.json()["id"] == body["id"]


async def test_another_accounts_passkey_cannot_be_renamed(
    client: AsyncClient, session: AsyncSession, ceremony
):
    owner = await _account(session, "pk-owner@example.com")
    other = await _account(session, "pk-other@example.com")
    body = await _register(client, owner, name="Laptop")

    response = await client.patch(
        f"/api/v1/auth/passkeys/{body['id']}",
        json={"name": "Mine now"},
        headers=get_auth_headers(other),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "PASSKEY_NOT_FOUND"


async def test_a_standing_credential_cannot_rename_one(
    client: AsyncClient, session: AsyncSession, ceremony
):
    from app.services.platform import api_keys as api_keys_service

    user = await _account(session, "pk-renamekey@example.com")
    body = await _register(client, user, name="Laptop")
    secret, _row = await api_keys_service.create_api_key(
        session, user=user, name="script"
    )
    await session.commit()

    response = await client.patch(
        f"/api/v1/auth/passkeys/{body['id']}",
        json={"name": "Renamed"},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "SESSION_REQUIRED"


async def test_removing_asks_for_the_password(
    client: AsyncClient, session: AsyncSession, ceremony
):
    user = await _account(session, "pk-removepw@example.com")
    body = await _register(client, user)

    response = await client.post(
        f"/api/v1/auth/passkeys/{body['id']}/remove",
        json={},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "USER_CURRENT_PASSWORD_REQUIRED"


async def test_removing_forgets_the_credential(
    client: AsyncClient, session: AsyncSession, ceremony
):
    user = await _account(session, "pk-remove@example.com")
    user_id = user.id
    body = await _register(client, user)

    response = await client.post(
        f"/api/v1/auth/passkeys/{body['id']}/remove",
        json={"current_password": PASSWORD},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 204, response.text

    session.expire_all()
    rows = (
        await session.exec(select(UserPasskey).where(UserPasskey.user_id == user_id))
    ).all()
    assert rows == []
    events = (
        await session.exec(
            select(AuditEvent).where(
                AuditEvent.actor_user_id == user_id,
                AuditEvent.event_type == AuditEventType.AUTH_PASSKEY_REMOVED.value,
            )
        )
    ).all()
    assert len(events) == 1
    assert events[0].envelope["detail"]["passkey_id"] == body["id"]


async def test_another_accounts_passkey_cannot_be_removed(
    client: AsyncClient, session: AsyncSession, ceremony
):
    owner = await _account(session, "pk-keepmine@example.com")
    other = await _account(session, "pk-taker@example.com")
    body = await _register(client, owner)

    response = await client.post(
        f"/api/v1/auth/passkeys/{body['id']}/remove",
        json={"current_password": PASSWORD},
        headers=get_auth_headers(other),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "PASSKEY_NOT_FOUND"


# ---------------------------------------------------------------------------
# What the account is told, and who may ask
# ---------------------------------------------------------------------------


async def test_the_account_is_told_about_both_changes(
    client: AsyncClient, session: AsyncSession, ceremony, monkeypatch
):
    sent: list[dict] = []

    async def record(_session, user, *, added: bool, name: str) -> None:
        sent.append({"user_id": user.id, "added": added, "name": name})

    monkeypatch.setattr(email_service, "send_passkey_changed_email", record)

    user = await _account(session, "pk-letter@example.com")
    body = await _register(client, user, name="Phone")
    assert sent == [{"user_id": user.id, "added": True, "name": "Phone"}]

    response = await client.post(
        f"/api/v1/auth/passkeys/{body['id']}/remove",
        json={"current_password": PASSWORD},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 204, response.text
    assert sent[-1] == {"user_id": user.id, "added": False, "name": "Phone"}


async def test_a_letter_that_cannot_go_does_not_undo_the_change(
    client: AsyncClient, session: AsyncSession, ceremony, monkeypatch
):
    """A deployment with no mail configured still registered the credential."""

    async def fail(*args, **kwargs) -> None:
        raise RuntimeError("no mail")

    monkeypatch.setattr(email_service, "send_passkey_changed_email", fail)

    user = await _account(session, "pk-nomail@example.com")
    user_id = user.id
    body = await _register(client, user)

    session.expire_all()
    rows = (
        await session.exec(select(UserPasskey).where(UserPasskey.user_id == user_id))
    ).all()
    assert len(rows) == 1
    assert str(rows[0].id) == body["id"]


async def test_a_standing_credential_cannot_register_one(
    client: AsyncClient, session: AsyncSession
):
    """Adding a way in is done while the person is here, not through a
    credential running without them."""
    from app.services.platform import api_keys as api_keys_service

    user = await _account(session, "pk-apikey@example.com")
    secret, _row = await api_keys_service.create_api_key(
        session, user=user, name="script"
    )
    await session.commit()

    response = await client.post(
        BEGIN,
        json={"current_password": PASSWORD, "name": "Laptop"},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "SESSION_REQUIRED"
