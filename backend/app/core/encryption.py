import base64

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
SALT_OIDC_REFRESH_TOKEN = b"oidc-refresh-token"   # legacy name, do not rename
SALT_OIDC_CLIENT_SECRET = b"oidc-client-secret"
SALT_SMTP_PASSWORD      = b"smtp-password"
SALT_AI_API_KEY         = b"ai-api-key"


def _derive_fernet_key(salt: bytes) -> bytes:
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b"fernet-key",
    )
    raw = hkdf.derive(settings.SECRET_KEY.encode())
    return base64.urlsafe_b64encode(raw)


_fernets: dict[bytes, Fernet] = {}


def _get_fernet(salt: bytes) -> Fernet:
    if salt not in _fernets:
        _fernets[salt] = Fernet(_derive_fernet_key(salt))
    return _fernets[salt]


def encrypt_field(plaintext: str, salt: bytes) -> str:
    return _get_fernet(salt).encrypt(plaintext.encode()).decode()


def decrypt_field(ciphertext: str, salt: bytes) -> str:
    return _get_fernet(salt).decrypt(ciphertext.encode()).decode()


# Kept for backward compatibility — used by oidc_refresh.py and auth.py
# for the oidc_refresh_token_encrypted column which predates per-field keys.
def encrypt_token(plaintext: str) -> str:
    return encrypt_field(plaintext, SALT_OIDC_REFRESH_TOKEN)


def decrypt_token(ciphertext: str) -> str:
    return decrypt_field(ciphertext, SALT_OIDC_REFRESH_TOKEN)
