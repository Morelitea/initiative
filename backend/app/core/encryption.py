import base64
import hmac as _hmac
import hashlib as _hashlib

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

from app.core.config import settings

# Each logical secret type gets its own HKDF salt so a compromised key
# for one field cannot decrypt another.  Never change an existing salt
# value — doing so changes the derived key and breaks decryption of all
# ciphertext produced with the old key.
#
# To add a new encrypted field: pick a descriptive salt string, add it
# here, and use encrypt_field / decrypt_field with that constant.
SALT_OIDC_REFRESH_TOKEN = b"oidc-refresh-token"  # legacy name, do not rename
SALT_OIDC_CLIENT_SECRET = b"oidc-client-secret"
SALT_SMTP_PASSWORD = b"smtp-password"
SALT_AI_API_KEY = b"ai-api-key"
SALT_EMAIL = b"email"
SALT_EVENT_PUBLISHER_PAYLOAD = b"event-publisher-payload"


def _resolve_secret_key(secret_key: str | None) -> str:
    """The explicit key when given, else the live SECRET_KEY. Lets the rotation
    sweep (app.db.secret_key_rotation) decrypt under the old key and re-encrypt
    under the new one without mutating global settings; default callers are
    unaffected."""
    return secret_key if secret_key is not None else settings.SECRET_KEY


def _derive_fernet_key(salt: bytes, secret_key: str) -> bytes:
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b"fernet-key",
    )
    raw = hkdf.derive(secret_key.encode())
    return base64.urlsafe_b64encode(raw)


# Cached per (secret_key, salt): rotation derives Fernets for two distinct keys, so
# the cache key must include the secret or the second key would collide with the first.
_fernets: dict[tuple[str, bytes], Fernet] = {}


def _get_fernet(salt: bytes, secret_key: str) -> Fernet:
    cache_key = (secret_key, salt)
    if cache_key not in _fernets:
        _fernets[cache_key] = Fernet(_derive_fernet_key(salt, secret_key))
    return _fernets[cache_key]


def hash_email(email: str, *, secret_key: str | None = None) -> str:
    """Deterministic HMAC-SHA256 of normalized email, keyed with SECRET_KEY.

    Used for equality lookups (WHERE email_hash = ?) and unique constraints. Pass
    ``secret_key`` to hash under a specific key (the rotation sweep recomputes hashes
    under the new key); default uses the live SECRET_KEY.
    """
    normalized = email.lower().strip()
    return _hmac.new(
        _resolve_secret_key(secret_key).encode(), normalized.encode(), _hashlib.sha256
    ).hexdigest()


def encrypt_field(plaintext: str, salt: bytes, *, secret_key: str | None = None) -> str:
    return (
        _get_fernet(salt, _resolve_secret_key(secret_key))
        .encrypt(plaintext.encode())
        .decode()
    )


def decrypt_field(
    ciphertext: str, salt: bytes, *, secret_key: str | None = None
) -> str:
    return (
        _get_fernet(salt, _resolve_secret_key(secret_key))
        .decrypt(ciphertext.encode())
        .decode()
    )


# Kept for backward compatibility — used by oidc_refresh.py and auth.py
# for the oidc_refresh_token_encrypted column which predates per-field keys.
def encrypt_token(plaintext: str) -> str:
    return encrypt_field(plaintext, SALT_OIDC_REFRESH_TOKEN)


def decrypt_token(ciphertext: str) -> str:
    return decrypt_field(ciphertext, SALT_OIDC_REFRESH_TOKEN)
