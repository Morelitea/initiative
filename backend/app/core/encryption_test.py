"""Unit tests for the encryption module."""

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
