"""Fast contract tests for the billing envelope's rotation overlap."""

import logging
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
CURRENT_SIGNATURE = "4fedc9943a673e2f49696595ff0d6dfb666afeb5f1bd8ae0470aab3a501d4857"
PREVIOUS_SIGNATURE = "20c9eb333669a3bccbce217bd922d8701c14cb0122914e856e45f2c8be8b2fa9"


@pytest.fixture
def envelope(monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, str], str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    monkeypatch.setattr(config_module.settings, "BILLING_PUBLIC_KEY_PEM", public_pem)
    monkeypatch.setattr(
        config_module.settings, "BILLING_HMAC_SECRET", "current-secret-value"
    )
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


def test_previous_hmac_secret_verifies_during_rotation(envelope, caplog) -> None:
    """The overlap verifies, and says so.

    The rotation procedure tells an operator to wait for
    `billing.envelope_verified_with_previous_secret` to stop appearing before
    retiring the old key. That signal is the only thing distinguishing "the far
    side has cut over" from "nothing has been sent recently", so a rename or a
    removal must fail a test rather than quietly leave the operator without it.
    """
    headers, _ = envelope
    with caplog.at_level(logging.WARNING):
        claims = verify_billing_envelope(
            method=METHOD,
            path=PATH,
            headers=headers,
            body=BODY,
        )
    assert claims.jti == "rotation-contract"
    assert any(
        "billing.envelope_verified_with_previous_secret" in record.getMessage()
        for record in caplog.records
    ), "traffic on the retiring key produced no cutover signal"


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


def test_duplicate_current_value_does_not_log_old_key_traffic(
    envelope, monkeypatch, caplog
) -> None:
    headers, _ = envelope
    headers["X-Billing-Signature"] = CURRENT_SIGNATURE
    monkeypatch.setattr(
        config_module.settings,
        "BILLING_HMAC_SECRET_PREVIOUS",
        "current-secret-value",
    )
    verify_billing_envelope(method=METHOD, path=PATH, headers=headers, body=BODY)
    assert not any(
        "verified_with_previous_secret" in record.getMessage()
        for record in caplog.records
    )
