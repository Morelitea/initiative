from typing import Optional

from sqlalchemy import Boolean, Column, Integer, String
from sqlmodel import Field, SQLModel
from pydantic import ConfigDict

# Login posture (platform vs guild) is a deploy-time setting, read from
# ``settings.AUTH_SCOPE`` — see ``app.core.config.AuthScope``. Platform OIDC
# config lives on the provider registry row (``auth_providers`` slug ``oidc``);
# neither is stored here.


class AppSetting(SQLModel, table=True):
    __tablename__ = "app_settings"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: int = Field(default=1, primary_key=True)

    light_accent_color: str = Field(
        default="#2563eb",
        sa_column=Column(String(20), nullable=False, server_default="#2563eb"),
    )
    dark_accent_color: str = Field(
        default="#60a5fa",
        sa_column=Column(String(20), nullable=False, server_default="#60a5fa"),
    )

    # What this deployment is running, and what it was running before that.
    # A notice that only matters to somebody upgrading past a given release has
    # no way to know that from a publication date — a fresh install of 0.70 was
    # never on 0.64. The pair is rolled forward at boot: when the running
    # version differs from ``last_seen_version``, the old value becomes
    # ``previous_version``. Both are NULL on a fresh install, which is exactly
    # what "never upgraded from anything" looks like.
    last_seen_version: Optional[str] = Field(
        default=None, sa_column=Column(String(32), nullable=True)
    )
    previous_version: Optional[str] = Field(
        default=None, sa_column=Column(String(32), nullable=True)
    )

    smtp_host: Optional[str] = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    smtp_port: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    smtp_secure: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    smtp_reject_unauthorized: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    smtp_username: Optional[str] = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    smtp_password_encrypted: Optional[str] = Field(
        default=None, sa_column=Column(String(2000), nullable=True)
    )
    smtp_from_address: Optional[str] = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    smtp_test_recipient: Optional[str] = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )

    # Whether this deployment runs a community directory at all: the browsable
    # list of guilds that have opted in, and the invite-free join that goes with
    # it. Off until an owner turns it on, so a deployment that never wanted a
    # public front door does not grow one on upgrade.
    community_directory_enabled: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )

    # Whether an account must say it is 13 or older before it belongs to a
    # guild listed in that directory. On by default, and only a platform owner
    # turns it off — doing so is that owner asserting that every account on the
    # deployment already belongs to an adult, which is a thing an enterprise
    # rollout knows and a public one does not. Independent of the directory
    # switch above so the assertion survives the directory being toggled.
    community_age_gate_enabled: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )

    # AI config ownership mode: "platform" (the operator's connections apply to
    # every guild), "guild" (each guild admin configures its own), or "disabled".
    # Provider config itself lives in platform_ai_connections /
    # guild_ai_connections; only the global mode lives here. Whether members may
    # attach their own key is a per-connection setting (allow_member_keys on the
    # connection), not a global toggle.
    ai_config_mode: str = Field(
        default="disabled",
        sa_column=Column(String(20), nullable=False, server_default="disabled"),
    )
    # Monotonic counter bumped on every operator AI-config write (mode or
    # platform connection). Read on the request's own (guild) session as the
    # cross-worker cache-freshness signal, so a change is picked up by every
    # replica at once instead of after a per-process TTL.
    ai_config_version: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )

    # Object storage (blob backend). "local" = filesystem under UPLOADS_DIR;
    # "s3" = any S3-compatible store. Seeded from the STORAGE_BACKEND / S3_* env
    # vars on first creation, then DB-authoritative (see app_settings service).
    storage_backend: str = Field(
        default="local",
        sa_column=Column(String(20), nullable=False, server_default="local"),
    )
    s3_bucket: Optional[str] = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    s3_region: str = Field(
        default="us-east-1",
        sa_column=Column(String(64), nullable=False, server_default="us-east-1"),
    )
    s3_endpoint_url: Optional[str] = Field(
        default=None, sa_column=Column(String(1000), nullable=True)
    )
    s3_access_key_id: Optional[str] = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    s3_secret_access_key_encrypted: Optional[str] = Field(
        default=None, sa_column=Column(String(2000), nullable=True)
    )
    s3_use_path_style: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    s3_kms_key_id: Optional[str] = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )
    s3_local_fallback: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
