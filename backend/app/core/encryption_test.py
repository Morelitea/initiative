"""Unit tests for the encryption module."""

import pytest

from app.core.encryption import (
    SALT_EMAIL,
    decrypt_field,
    encrypt_field,
    hash_email,
)


def test_hash_email_is_deterministic() -> None:
    """Same input always produces same hash."""
    h1 = hash_email("alice@example.com")
    h2 = hash_email("alice@example.com")
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex digest


def test_hash_email_normalizes_case() -> None:
    """Upper/mixed case emails hash the same as lowercase."""
    assert hash_email("User@Example.COM") == hash_email("user@example.com")
    assert hash_email("ALICE@EXAMPLE.COM") == hash_email("alice@example.com")


def test_hash_email_normalizes_whitespace() -> None:
    """Leading/trailing whitespace is stripped before hashing."""
    assert hash_email("  alice@example.com  ") == hash_email("alice@example.com")


def test_hash_email_differs_for_different_inputs() -> None:
    """Different email addresses produce different hashes."""
    h1 = hash_email("alice@example.com")
    h2 = hash_email("bob@example.com")
    assert h1 != h2


def test_encrypt_decrypt_roundtrip_email() -> None:
    """encrypt_field → decrypt_field round-trip with SALT_EMAIL."""
    plaintext = "alice@example.com"
    ciphertext = encrypt_field(plaintext, SALT_EMAIL)
    assert ciphertext != plaintext
    recovered = decrypt_field(ciphertext, SALT_EMAIL)
    assert recovered == plaintext


def test_encrypt_is_nondeterministic() -> None:
    """Fernet encryption is randomised — two encryptions differ."""
    ct1 = encrypt_field("alice@example.com", SALT_EMAIL)
    ct2 = encrypt_field("alice@example.com", SALT_EMAIL)
    assert ct1 != ct2


def test_hash_email_salt_isolation() -> None:
    """hash_email result is different from a generic HMAC with a different salt."""
    from app.core.encryption import SALT_AI_API_KEY

    # Using the wrong salt produces a different ciphertext — salt isolation holds
    ct_email = encrypt_field("secret", SALT_EMAIL)
    ct_ai = encrypt_field("secret", SALT_AI_API_KEY)
    assert ct_email != ct_ai
    assert decrypt_field(ct_email, SALT_EMAIL) == "secret"
    assert decrypt_field(ct_ai, SALT_AI_API_KEY) == "secret"


# ──────────────────────────────────────────────────────────────────────────
# Explicit-key support (used by the SECRET_KEY rotation sweep to decrypt under
# the old key and re-encrypt under the new one without mutating global settings).
# ──────────────────────────────────────────────────────────────────────────

# Two distinct test-only keys (each ≥32 chars). Not secrets.
_KEY_A = "a" * 48
_KEY_B = "b" * 48


def test_encrypt_decrypt_roundtrip_with_explicit_key() -> None:
    """A value encrypted under an explicit key round-trips with that same key."""
    ct = encrypt_field("hunter2", SALT_EMAIL, secret_key=_KEY_A)
    assert decrypt_field(ct, SALT_EMAIL, secret_key=_KEY_A) == "hunter2"


def test_ciphertext_from_one_key_fails_under_another() -> None:
    """Ciphertext from key A must NOT decrypt under key B — this is what lets the
    rotation sweep tell rotated rows from un-rotated ones."""
    from cryptography.fernet import InvalidToken

    ct = encrypt_field("hunter2", SALT_EMAIL, secret_key=_KEY_A)
    with pytest.raises(InvalidToken):
        decrypt_field(ct, SALT_EMAIL, secret_key=_KEY_B)


def test_explicit_old_to_new_reencrypt() -> None:
    """The rotation primitive: decrypt under old key, re-encrypt under new key."""
    old_ct = encrypt_field("smtp-pw", SALT_EMAIL, secret_key=_KEY_A)
    plain = decrypt_field(old_ct, SALT_EMAIL, secret_key=_KEY_A)
    new_ct = encrypt_field(plain, SALT_EMAIL, secret_key=_KEY_B)
    assert decrypt_field(new_ct, SALT_EMAIL, secret_key=_KEY_B) == "smtp-pw"


def test_hash_email_explicit_key_differs_per_key() -> None:
    """The email HMAC under different keys differs — so a rotation must recompute it,
    and lookups must use candidates matching the active key."""
    h_a = hash_email("alice@example.com", secret_key=_KEY_A)
    h_b = hash_email("alice@example.com", secret_key=_KEY_B)
    assert h_a != h_b
    assert len(h_a) == len(h_b) == 64
    # Explicit key matching the live default is consistent with the no-arg form.
    from app.core.config import settings

    assert hash_email(
        "alice@example.com", secret_key=settings.SECRET_KEY
    ) == hash_email("alice@example.com")
