"""Integration tests for the billing write boundary.

Exercises the security properties of ``POST /api/v1/billing/*``:

* the double envelope — HMAC over METHOD/PATH/TIMESTAMP/sha256(body) inside
  a replay window, plus an RS256 service JWT with one-shot jti — with
  negative tests for every layer (unconfigured, missing headers, stale or
  tampered signatures, wrong key/aud/iss, replayed jti);
* exactly-once application via the ``billing_event_log`` claim (a retried
  event id is a no-op; a 404'd attempt does NOT consume its event id);
* omit-vs-null sentinel semantics on the writable fields;
* the support_manual source restriction (storage cap only, actor required);
* the audit row recorded for every applied write.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_lib
import json
import secrets
import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import config as config_module
from app.models.platform.billing import BillingEventLog, BillingJti
from app.services.platform.billing_jti_janitor import purge_expired_billing_jtis
from app.testing import create_guild, create_guild_membership, create_user

pytestmark = pytest.mark.integration

_keypair = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _keypair.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
_PUBLIC_PEM = (
    _keypair.public_key()
    .public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode()
)
_OTHER_KEYPAIR = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_PRIVATE_PEM = _OTHER_KEYPAIR.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()

_HMAC_SECRET = "test-billing-hmac-secret"


@pytest.fixture(autouse=True)
def _configure_billing(monkeypatch):
    monkeypatch.setattr(config_module.settings, "BILLING_PUBLIC_KEY_PEM", _PUBLIC_PEM)
    monkeypatch.setattr(config_module.settings, "BILLING_HMAC_SECRET", _HMAC_SECRET)


def _mint_token(
    *,
    jti: str | None = None,
    aud: str = "initiative:billing",
    iss: str = "initiative-billing",
    private_pem: str = _PRIVATE_PEM,
    expires_in: int = 300,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "jti": jti or secrets.token_hex(8),
        "sub": "initiative-billing",
        "aud": aud,
        "iss": iss,
        "iat": int(now.timestamp()),
        "exp": now + timedelta(seconds=expires_in),
    }
    return jwt.encode(payload, private_pem, algorithm="RS256")


def _signed_headers(
    path: str,
    body: bytes,
    *,
    token: str | None = None,
    secret: str = _HMAC_SECRET,
    timestamp: str | None = None,
    method: str = "POST",
) -> dict[str, str]:
    ts = timestamp if timestamp is not None else str(int(time.time()))
    message = "\n".join([method, path, ts, hashlib.sha256(body).hexdigest()]).encode()
    signature = hmac_lib.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return {
        "Authorization": f"Bearer {token or _mint_token()}",
        "X-Billing-Timestamp": ts,
        "X-Billing-Signature": signature,
        "Content-Type": "application/json",
    }


async def _post(client: AsyncClient, endpoint: str, payload: dict, **overrides):
    path = f"/api/v1/billing/{endpoint}"
    body = json.dumps(payload).encode()
    headers = _signed_headers(path, body, **overrides)
    return await client.post(path, content=body, headers=headers)


def _tier_payload(guild_id: int, **fields) -> dict:
    return {
        "guild_id": guild_id,
        "event_id": fields.pop("event_id", f"evt-{secrets.token_hex(6)}"),
        "source": fields.pop("source", "paddle_webhook"),
        **fields,
    }


# --- Envelope verification ---------------------------------------------------


async def test_unconfigured_boundary_refuses_everything(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    monkeypatch.setattr(config_module.settings, "BILLING_PUBLIC_KEY_PEM", None)
    guild = await create_guild(session)
    response = await _post(client, "guild-tier", _tier_payload(guild.id))
    # 503, not 403: billing absent is the self-host default, not a caller
    # fault (see billing_foss_test.py for the full unconfigured surface).
    assert response.status_code == 503
    assert response.json()["detail"] == "BILLING_NOT_CONFIGURED"


async def test_missing_envelope_headers_rejected(
    client: AsyncClient, session: AsyncSession
):
    guild = await create_guild(session)
    body = json.dumps(_tier_payload(guild.id)).encode()
    response = await client.post(
        "/api/v1/billing/guild-tier",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "BILLING_MISSING_SIGNATURE"


async def test_stale_timestamp_rejected(client: AsyncClient, session: AsyncSession):
    guild = await create_guild(session)
    stale = str(int(time.time()) - 3600)
    response = await _post(
        client, "guild-tier", _tier_payload(guild.id), timestamp=stale
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "BILLING_STALE_TIMESTAMP"


async def test_wrong_hmac_secret_rejected(client: AsyncClient, session: AsyncSession):
    guild = await create_guild(session)
    response = await _post(
        client, "guild-tier", _tier_payload(guild.id), secret="wrong-secret"
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "BILLING_INVALID_SIGNATURE"


async def test_tampered_body_rejected(client: AsyncClient, session: AsyncSession):
    """A signature minted for one body must not authorize a different one."""
    guild = await create_guild(session)
    path = "/api/v1/billing/guild-tier"
    signed_body = json.dumps(_tier_payload(guild.id, tier_name="silver")).encode()
    headers = _signed_headers(path, signed_body)
    tampered = json.dumps(_tier_payload(guild.id, tier_name="platinum")).encode()
    response = await client.post(path, content=tampered, headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "BILLING_INVALID_SIGNATURE"


async def test_wrong_jwt_key_rejected(client: AsyncClient, session: AsyncSession):
    guild = await create_guild(session)
    token = _mint_token(private_pem=_OTHER_PRIVATE_PEM)
    response = await _post(client, "guild-tier", _tier_payload(guild.id), token=token)
    assert response.status_code == 403
    assert response.json()["detail"] == "BILLING_INVALID_TOKEN"


@pytest.mark.parametrize(
    "claim_overrides",
    [{"aud": "initiative:auto-delegation"}, {"iss": "someone-else"}],
)
async def test_wrong_audience_or_issuer_rejected(
    client: AsyncClient, session: AsyncSession, claim_overrides: dict
):
    guild = await create_guild(session)
    token = _mint_token(**claim_overrides)
    response = await _post(client, "guild-tier", _tier_payload(guild.id), token=token)
    assert response.status_code == 403
    assert response.json()["detail"] == "BILLING_INVALID_TOKEN"


async def test_jti_is_one_shot(client: AsyncClient, session: AsyncSession):
    """The same service JWT must not authorize two calls, even with distinct
    event ids and fresh signatures."""
    guild = await create_guild(session)
    token = _mint_token(jti="billing-replay-001")

    first = await _post(client, "guild-tier", _tier_payload(guild.id), token=token)
    assert first.status_code == 200, first.text

    second = await _post(client, "guild-tier", _tier_payload(guild.id), token=token)
    assert second.status_code == 403
    assert second.json()["detail"] == "BILLING_REPLAYED_TOKEN"


async def test_oversized_jti_rejected(client: AsyncClient, session: AsyncSession):
    """A jti longer than the blocklist column must be refused at
    verification, not surface as a database error at redemption."""
    guild = await create_guild(session)
    token = _mint_token(jti="x" * 65)
    response = await _post(client, "guild-tier", _tier_payload(guild.id), token=token)
    assert response.status_code == 403
    assert response.json()["detail"] == "BILLING_INVALID_TOKEN"


async def test_purged_jti_still_unreplayable(
    client: AsyncClient, session: AsyncSession
):
    """The janitor prunes a redeemed jti only after its JWT ``exp`` — at
    which point the JWT layer rejects any replay of that token anyway, so
    purging never re-opens a replay window."""
    guild = await create_guild(session)
    jti = "billing-purged-jti"
    token = _mint_token(jti=jti, expires_in=-30)  # exp already in the past

    # Simulate the long-ago redemption whose row the janitor prunes.
    now = datetime.now(timezone.utc)
    session.add(
        BillingJti(
            jti=jti,
            redeemed_at=now - timedelta(minutes=10),
            expires_at=now - timedelta(seconds=30),
        )
    )
    await session.commit()

    assert await purge_expired_billing_jtis(session) >= 1
    remaining = (
        await session.exec(select(BillingJti).where(BillingJti.jti == jti))
    ).one_or_none()
    assert remaining is None

    # Fresh HMAC, purged blocklist row — the token's own exp still refuses it.
    response = await _post(client, "guild-tier", _tier_payload(guild.id), token=token)
    assert response.status_code == 403
    assert response.json()["detail"] == "BILLING_INVALID_TOKEN"


# --- guild-tier ----------------------------------------------------------------


async def test_apply_guild_tier_happy_path(client: AsyncClient, session: AsyncSession):
    guild = await create_guild(session)
    response = await _post(
        client,
        "guild-tier",
        _tier_payload(
            guild.id,
            event_id="evt-happy-1",
            tier_name="gold",
            max_storage_bytes=50 * 1024**3,
            max_users=25,
        ),
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["applied"] is True
    assert data["tier_name"] == "gold"
    assert data["max_storage_bytes"] == 50 * 1024**3
    assert data["max_users"] == 25
    assert data["status"] == "active"
    assert data["member_count"] == 0  # the factory creates no membership rows

    await session.refresh(guild)
    assert guild.tier_name == "gold"
    assert guild.max_storage_bytes == 50 * 1024**3
    assert guild.max_users == 25

    event = (
        await session.exec(
            select(BillingEventLog).where(BillingEventLog.event_id == "evt-happy-1")
        )
    ).one()
    assert event.guild_id == guild.id
    assert event.op == "guild_tier"
    assert event.source == "paddle_webhook"
    assert event.actor is None


async def test_replayed_event_id_is_noop(client: AsyncClient, session: AsyncSession):
    """Same event id, fresh token: claimed once, second delivery changes
    nothing even though it carries different values."""
    guild = await create_guild(session)
    first = await _post(
        client,
        "guild-tier",
        _tier_payload(guild.id, event_id="evt-dup", tier_name="gold"),
    )
    assert first.status_code == 200 and first.json()["applied"] is True

    second = await _post(
        client,
        "guild-tier",
        _tier_payload(guild.id, event_id="evt-dup", tier_name="platinum"),
    )
    assert second.status_code == 200
    data = second.json()
    assert data["applied"] is False
    assert data["tier_name"] == "gold"  # untouched by the replay

    await session.refresh(guild)
    assert guild.tier_name == "gold"


async def test_sentinel_semantics_omit_vs_null(
    client: AsyncClient, session: AsyncSession
):
    guild = await create_guild(session)
    setup = await _post(
        client,
        "guild-tier",
        _tier_payload(guild.id, tier_name="gold", max_storage_bytes=1024, max_users=10),
    )
    assert setup.status_code == 200

    # Omitted fields stay; null resets to unlimited.
    response = await _post(
        client,
        "guild-tier",
        _tier_payload(guild.id, max_storage_bytes=None),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["tier_name"] == "gold"  # omitted -> untouched
    assert data["max_users"] == 10  # omitted -> untouched
    assert data["max_storage_bytes"] is None  # null -> unlimited


async def test_status_change_stamps_status_changed_at(
    client: AsyncClient, session: AsyncSession
):
    guild = await create_guild(session)
    assert guild.status_changed_at is None
    response = await _post(
        client, "guild-tier", _tier_payload(guild.id, status="read_only")
    )
    assert response.status_code == 200
    assert response.json()["status"] == "read_only"

    await session.refresh(guild)
    assert guild.status == "read_only"
    assert guild.status_changed_at is not None


async def test_support_source_may_only_raise_storage(
    client: AsyncClient, session: AsyncSession
):
    # Start from a finite cap: support can only RAISE, and a fresh guild is
    # NULL = unlimited (nothing to raise — see the cannot-lower test below).
    guild = await create_guild(session, max_storage_bytes=1024)

    allowed = await _post(
        client,
        "guild-tier",
        _tier_payload(
            guild.id,
            source="support_manual",
            actor="support:42",
            max_storage_bytes=2048,
        ),
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["max_storage_bytes"] == 2048

    tier_change = await _post(
        client,
        "guild-tier",
        _tier_payload(
            guild.id, source="support_manual", actor="support:42", tier_name="gold"
        ),
    )
    assert tier_change.status_code == 422
    assert tier_change.json()["detail"] == "BILLING_SUPPORT_SOURCE_RESTRICTED"

    anonymous = await _post(
        client,
        "guild-tier",
        _tier_payload(guild.id, source="support_manual", max_storage_bytes=4096),
    )
    assert anonymous.status_code == 422
    assert anonymous.json()["detail"] == "BILLING_ACTOR_REQUIRED"


async def test_support_source_cannot_lower_storage(
    client: AsyncClient, session: AsyncSession
):
    """support_manual may only RAISE the storage cap: lowering a finite cap,
    or capping an unlimited (NULL) guild, is refused — and the refused write
    consumes neither its event id nor its jti (a corrected retry works)."""
    guild = await create_guild(session)

    # Guild starts unlimited (NULL): any finite support cap is a lowering.
    cap_unlimited = await _post(
        client,
        "guild-tier",
        _tier_payload(
            guild.id,
            source="support_manual",
            actor="support:42",
            max_storage_bytes=10_000,
        ),
    )
    assert cap_unlimited.status_code == 422
    assert cap_unlimited.json()["detail"] == "BILLING_SUPPORT_CANNOT_LOWER"

    # Give the guild a finite cap via the automated path.
    setup = await _post(
        client, "guild-tier", _tier_payload(guild.id, max_storage_bytes=4096)
    )
    assert setup.status_code == 200

    lowered = await _post(
        client,
        "guild-tier",
        _tier_payload(
            guild.id,
            source="support_manual",
            actor="support:42",
            event_id="evt-support-lower",
            max_storage_bytes=1024,
        ),
    )
    assert lowered.status_code == 422
    assert lowered.json()["detail"] == "BILLING_SUPPORT_CANNOT_LOWER"

    await session.refresh(guild)
    assert guild.max_storage_bytes == 4096  # untouched

    # Equal-to-current is an idempotent re-apply, and the refused event id
    # above was NOT consumed — reusing it now succeeds.
    equal = await _post(
        client,
        "guild-tier",
        _tier_payload(
            guild.id,
            source="support_manual",
            actor="support:42",
            event_id="evt-support-lower",
            max_storage_bytes=4096,
        ),
    )
    assert equal.status_code == 200, equal.text
    assert equal.json()["applied"] is True

    # paddle_webhook (the automated recompute path) may lower freely.
    automated = await _post(
        client, "guild-tier", _tier_payload(guild.id, max_storage_bytes=512)
    )
    assert automated.status_code == 200
    assert automated.json()["max_storage_bytes"] == 512


async def test_unknown_guild_404_does_not_consume_event_id(
    client: AsyncClient, session: AsyncSession
):
    guild = await create_guild(session)
    missing = await _post(
        client,
        "guild-tier",
        _tier_payload(999_999_999, event_id="evt-preserved", tier_name="gold"),
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == "BILLING_GUILD_NOT_FOUND"

    retry = await _post(
        client,
        "guild-tier",
        _tier_payload(guild.id, event_id="evt-preserved", tier_name="gold"),
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["applied"] is True


async def test_malformed_payload_rejected_after_verification(
    client: AsyncClient, session: AsyncSession
):
    path = "/api/v1/billing/guild-tier"
    body = b'{"guild_id": "not-a-number"}'
    headers = _signed_headers(path, body)
    response = await client.post(path, content=body, headers=headers)
    assert response.status_code == 422
    assert response.json()["detail"] == "BILLING_INVALID_PAYLOAD"


# --- headcount ------------------------------------------------------------------


async def test_headcount(client: AsyncClient, session: AsyncSession):
    guild = await create_guild(session)
    for i in range(2):
        member = await create_user(session, email=f"member{i}@example.com")
        await create_guild_membership(session, user=member, guild=guild)

    response = await _post(client, "headcount", {"guild_id": guild.id})
    assert response.status_code == 200, response.text
    assert response.json() == {"guild_id": guild.id, "member_count": 2}


async def test_headcount_unknown_guild_404(client: AsyncClient, session: AsyncSession):
    response = await _post(client, "headcount", {"guild_id": 999_999_999})
    assert response.status_code == 404
    assert response.json()["detail"] == "BILLING_GUILD_NOT_FOUND"


async def test_headcount_burns_jti(client: AsyncClient, session: AsyncSession):
    """Reads redeem their token too — a captured headcount request must not
    be replayable inside the window."""
    guild = await create_guild(session)
    token = _mint_token(jti="billing-read-replay")
    first = await _post(client, "headcount", {"guild_id": guild.id}, token=token)
    assert first.status_code == 200
    second = await _post(client, "headcount", {"guild_id": guild.id}, token=token)
    assert second.status_code == 403
    assert second.json()["detail"] == "BILLING_REPLAYED_TOKEN"
