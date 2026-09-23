from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, text
from sqlmodel import Field, SQLModel


class AppSettingSecret(SQLModel, table=True):
    """The deployment's stored credentials — kept OUT of ``app_settings``.

    A companion to the settings singleton, read and written only by the system
    engine. The settings row carries everything the settings pages show; this
    row carries the two credentials they only report as set or not set.

    1:1 with the singleton — ``id`` is the PK and an FK to ``app_settings.id``
    (``ON DELETE CASCADE``), so it is ``1`` like the row it belongs to. Each
    column is Fernet-encrypted at rest with its own salt (registered in the
    secret-key rotation registry) and ``NULL`` when no credential is stored.

    No row means none has been stored yet: readers are served the env-seeded
    values, as a settings row created on first boot would have carried them.
    """

    __tablename__ = "app_setting_secrets"

    id: int = Field(
        default=1,
        sa_column=Column(
            Integer,
            ForeignKey("app_settings.id", ondelete="CASCADE"),
            primary_key=True,
            autoincrement=False,
        ),
    )

    # The SMTP password (``SALT_SMTP_PASSWORD``).
    smtp_password_encrypted: Optional[str] = Field(
        default=None, sa_column=Column(String(2000), nullable=True)
    )

    # The S3 secret access key (``SALT_S3_SECRET_KEY``).
    s3_secret_access_key_encrypted: Optional[str] = Field(
        default=None, sa_column=Column(String(2000), nullable=True)
    )

    # The captcha provider's server-side verification secret
    # (``SALT_CAPTCHA_SECRET_KEY``).
    captcha_secret_key_encrypted: Optional[str] = Field(
        default=None, sa_column=Column(String(2000), nullable=True)
    )

    # The FCM service-account JSON (``SALT_FCM_SERVICE_ACCOUNT``).
    #
    # Wider than its neighbours because the plaintext is a whole JSON document
    # -- a Google service account is around 2.4 kB, which Fernet takes to
    # roughly 3.3 kB of base64, past the 2000 the columns above are sized for.
    # Storing it truncated would fail at `json.loads` on the next push, a long
    # way from the settings page that accepted it.
    fcm_service_account_json_encrypted: Optional[str] = Field(
        default=None, sa_column=Column(String(8000), nullable=True)
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=text("now()"),
            onupdate=lambda: datetime.now(timezone.utc),
        ),
    )
