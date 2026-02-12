import base64

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

from app.core.config import settings


def _derive_fernet_key() -> bytes:
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"oidc-refresh-token",
        info=b"fernet-key",
    )
    raw = hkdf.derive(settings.SECRET_KEY.encode())
    return base64.urlsafe_b64encode(raw)


_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_derive_fernet_key())
    return _fernet


def encrypt_token(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()
