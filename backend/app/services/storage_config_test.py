"""Tests for the resolved storage-config cache.

Covers the precedence rules that make the Storage settings tab safe: the env
fallback before the DB is loaded, and DB values overriding env after a refresh.
"""

from __future__ import annotations

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings as app_config
from app.services import storage_config
from app.services.platform import app_settings as app_settings_service


@pytest.fixture(autouse=True)
def _reset_cache():
    storage_config.reset_for_tests()
    yield
    storage_config.reset_for_tests()


@pytest.mark.unit
def test_current_config_falls_back_to_env_before_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no snapshot loaded, the resolver reads env settings — identical to the
    original env-only behavior (so CLI/scripts and boot-before-refresh work)."""
    monkeypatch.setattr(app_config, "STORAGE_BACKEND", "local", raising=False)
    monkeypatch.setattr(app_config, "S3_BUCKET", "env-bucket", raising=False)

    cfg = storage_config.current_storage_config()
    assert cfg.backend == "local"
    assert cfg.bucket == "env-bucket"


@pytest.mark.integration
async def test_refresh_loads_db_over_env(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After a refresh, the snapshot reflects the DB row — and its backend/bucket
    win over whatever the env vars say."""
    monkeypatch.setattr(app_config, "STORAGE_BACKEND", "local", raising=False)

    await app_settings_service.update_storage_settings(
        session,
        backend="s3",
        s3_bucket="db-bucket",
        s3_region="ap-south-1",
        s3_endpoint_url="https://garage.example.com",
        s3_access_key_id="AKIADB",
        s3_secret_access_key="db-secret",
        secret_provided=True,
        s3_use_path_style=True,
        s3_kms_key_id=None,
        s3_local_fallback=False,
    )

    # update_storage_settings already refreshed the snapshot; assert it loaded.
    cfg = storage_config.current_storage_config()
    assert cfg.backend == "s3"
    assert cfg.bucket == "db-bucket"
    assert cfg.region == "ap-south-1"
    assert cfg.endpoint_url == "https://garage.example.com"
    assert cfg.secret_access_key == "db-secret"  # decrypted
    assert cfg.use_path_style is True


@pytest.mark.integration
async def test_test_connection_local_is_noop(session: AsyncSession) -> None:
    """A local backend has no remote to reach, so the connection test passes."""
    cfg = storage_config.ResolvedStorageConfig(
        backend="local",
        bucket=None,
        region="us-east-1",
        endpoint_url=None,
        access_key_id=None,
        secret_access_key=None,
        use_path_style=False,
        kms_key_id=None,
        local_fallback=False,
    )
    ok, _message = await storage_config.test_connection(cfg)
    assert ok is True


@pytest.mark.unit
def test_build_s3_client_disables_flexible_checksums() -> None:
    """Regression: botocore >=1.36's default flexible checksums break non-AWS
    S3 stores (signature/AccessDenied, classically on GetObject). The client must
    pin both checksum knobs to "when_required" for S3-compatible interop."""
    from app.services.storage import build_s3_client

    cfg = storage_config.ResolvedStorageConfig(
        backend="s3",
        bucket="b",
        region="garage",
        endpoint_url="http://localhost:3900",
        access_key_id="GK",
        secret_access_key="x",
        use_path_style=True,
        kms_key_id=None,
        local_fallback=False,
    )
    client = build_s3_client(cfg)
    assert client.meta.config.request_checksum_calculation == "when_required"
    assert client.meta.config.response_checksum_validation == "when_required"


@pytest.mark.integration
async def test_test_connection_s3_requires_bucket(session: AsyncSession) -> None:
    cfg = storage_config.ResolvedStorageConfig(
        backend="s3",
        bucket=None,
        region="us-east-1",
        endpoint_url=None,
        access_key_id=None,
        secret_access_key=None,
        use_path_style=False,
        kms_key_id=None,
        local_fallback=False,
    )
    ok, message = await storage_config.test_connection(cfg)
    assert ok is False
    assert "S3_BUCKET" in message
