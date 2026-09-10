"""Fast contract tests for the billing envelope's rotation overlap."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core import config as config_module
from app.core.messages import BillingMessages
from app.services.platform.billing import (
    BillingEnvelopeError,
    verify_billing_envelope,
)

NOW = 2_000_000_000
METHOD = "POST"
PATH = "/api/v1/billing/guild-tier"
BODY = b'{"guild_id":1}'
PREVIOUS_SIGNATURE = "20c9eb333669a3bccbce217bd922d8701c14cb0122914e856e45f2c8be8b2fa9"


@pytest.fixture
def envelope(monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, str], str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    monkeypatch.setattr(config_module.settings, "BILLING_PUBLIC_KEY_PEM", public_pem)
    monkeypatch.setattr(config_module.settings, "BILLING_HMAC_SECRET", "current-secret-value")
    monkeypatch.setattr(
        config_module.settings,
        "BILLING_HMAC_SECRET_PREVIOUS",
        "previous-secret-value",
    )
    monkeypatch.setattr("app.services.platform.billing.time.time", lambda: NOW)

    real_now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "jti": "rotation-contract",
            "aud": "initiative:billing",
            "iss": "initiative-billing",
            "iat": real_now,
            "exp": real_now + timedelta(minutes=5),
        },
        private_pem,
        algorithm="RS256",
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Billing-Timestamp": str(NOW),
        "X-Billing-Signature": PREVIOUS_SIGNATURE,
    }
    return headers, token


def test_previous_hmac_secret_verifies_during_rotation(envelope) -> None:
    headers, _ = envelope
    claims = verify_billing_envelope(
        method=METHOD,
        path=PATH,
        headers=headers,
        body=BODY,
    )
    assert claims.jti == "rotation-contract"


def test_previous_hmac_secret_is_rejected_after_overlap(envelope, monkeypatch) -> None:
    headers, _ = envelope
    monkeypatch.setattr(config_module.settings, "BILLING_HMAC_SECRET_PREVIOUS", None)
    with pytest.raises(BillingEnvelopeError) as exc_info:
        verify_billing_envelope(
            method=METHOD,
            path=PATH,
            headers=headers,
            body=BODY,
        )
    assert exc_info.value.code == BillingMessages.INVALID_SIGNATURE
