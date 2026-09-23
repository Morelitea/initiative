"""Migration 0368 carries the env credentials into a settings row that exists.

The chain test builds from empty, where there is no settings row and the
backfill returns before writing anything — so it never saw that both tables
are FORCE ROW LEVEL SECURITY, which binds the role that owns them and runs the
migration. These tests run the backfill as that owner, against a real row.

The suite migrates as a superuser, which bypasses RLS whatever FORCE says, so
each test hands both tables to a throwaway role inside one transaction and
rolls all of it back — ownership, role and rows.
"""

import importlib.util
import pathlib

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.encryption import SALT_CAPTCHA_SECRET_KEY, decrypt_field
from conftest import RUN_ID

pytestmark = [pytest.mark.integration, pytest.mark.database]

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260923_0368_captcha_and_push_credentials_move_into_settings.py"
)

_TABLES = ("app_settings", "app_setting_secrets")
_OWNER = f"test_{RUN_ID}_settings_owner"


def _migration():
    """The revision, loaded by path: a file that starts with a digit is not an
    importable module. Safe to import — it binds ``op`` and calls nothing."""
    spec = importlib.util.spec_from_file_location("migration_0368", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def env(monkeypatch):
    """A deployment that configured captcha and push through the environment."""
    values = {
        "CAPTCHA_PROVIDER": "turnstile",
        "CAPTCHA_SITE_KEY": "site-key",
        "CAPTCHA_SECRET_KEY": "captcha-secret",
        "FCM_ENABLED": True,
        "FCM_PROJECT_ID": "project",
        "FCM_APPLICATION_ID": "app",
        "FCM_API_KEY": "api-key",
        "FCM_SENDER_ID": "123",
        "FCM_SERVICE_ACCOUNT_JSON": '{"type": "service_account"}',
    }
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)
    return values


@pytest.fixture
async def as_owner(session: AsyncSession):
    """The upgrade's starting point, run as the tables' non-superuser owner:
    a settings row that has booted, the new columns still empty, no secrets
    row. Everything, the role included, is rolled back afterwards."""
    await session.exec(text(f'CREATE ROLE "{_OWNER}"'))
    await session.exec(text(f'GRANT USAGE ON SCHEMA public TO "{_OWNER}"'))
    await session.exec(
        text("INSERT INTO app_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
    )
    await session.exec(
        text(
            "UPDATE app_settings SET captcha_provider = NULL, captcha_site_key = NULL, "
            "fcm_project_id = NULL, fcm_application_id = NULL, fcm_api_key = NULL, "
            "fcm_sender_id = NULL, fcm_enabled = false WHERE id = 1"
        )
    )
    await session.exec(text("DELETE FROM app_setting_secrets"))
    for table in _TABLES:
        await session.exec(text(f'ALTER TABLE public.{table} OWNER TO "{_OWNER}"'))
        await session.exec(text(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY"))
    await session.exec(text(f'SET LOCAL ROLE "{_OWNER}"'))
    try:
        yield session
    finally:
        await session.rollback()


async def _as_superuser(session: AsyncSession, sql: str):
    await session.exec(text("RESET ROLE"))
    return (await session.exec(text(sql))).one()


async def test_the_owner_is_refused_while_force_is_on(as_owner, env):
    """What the first database with a settings row hit: FORCE binds the
    owner, and the secrets table has no policy to admit it."""
    migration = _migration()
    with pytest.raises(DBAPIError) as excinfo:
        await as_owner.run_sync(
            lambda sync: migration._write_env_values(sync.connection())
        )
    assert "row-level security" in str(excinfo.value)


async def test_the_env_values_land_in_the_settings_row(as_owner, env):
    migration = _migration()
    await as_owner.run_sync(lambda sync: migration._backfill(sync.connection()))

    row = await _as_superuser(
        as_owner,
        "SELECT captcha_provider, captcha_site_key, fcm_enabled, fcm_project_id, "
        "fcm_application_id, fcm_api_key, fcm_sender_id "
        "FROM app_settings WHERE id = 1",
    )
    assert tuple(row) == (
        "turnstile",
        "site-key",
        True,
        "project",
        "app",
        "api-key",
        "123",
    )

    secret, account = await _as_superuser(
        as_owner,
        "SELECT captcha_secret_key_encrypted, fcm_service_account_json_encrypted "
        "FROM app_setting_secrets WHERE id = 1",
    )
    assert decrypt_field(secret, SALT_CAPTCHA_SECRET_KEY) == "captcha-secret"
    assert account is not None


async def test_the_public_values_land_when_no_secret_is_set(as_owner, env, monkeypatch):
    """The quiet half: with no secret to write there is no INSERT to refuse,
    so under FORCE the upgrade succeeded while every UPDATE matched no row —
    and a captcha configured only by provider and site key stopped being
    enforced."""
    monkeypatch.setattr(settings, "CAPTCHA_SECRET_KEY", None)
    monkeypatch.setattr(settings, "FCM_SERVICE_ACCOUNT_JSON", None)
    migration = _migration()
    await as_owner.run_sync(lambda sync: migration._backfill(sync.connection()))

    provider, site_key = await _as_superuser(
        as_owner,
        "SELECT captcha_provider, captcha_site_key FROM app_settings WHERE id = 1",
    )
    assert (provider, site_key) == ("turnstile", "site-key")


async def test_a_value_somebody_already_set_is_kept(as_owner, env):
    await as_owner.exec(text("RESET ROLE"))
    await as_owner.exec(
        text("UPDATE app_settings SET captcha_site_key = 'chosen' WHERE id = 1")
    )
    await as_owner.exec(text(f'SET LOCAL ROLE "{_OWNER}"'))

    migration = _migration()
    await as_owner.run_sync(lambda sync: migration._backfill(sync.connection()))

    (site_key,) = await _as_superuser(
        as_owner, "SELECT captcha_site_key FROM app_settings WHERE id = 1"
    )
    assert site_key == "chosen"


async def test_both_tables_are_forced_again_when_it_is_done(as_owner, env):
    migration = _migration()
    await as_owner.run_sync(lambda sync: migration._backfill(sync.connection()))

    forced = (
        await as_owner.exec(
            text(
                "SELECT relname, relforcerowsecurity FROM pg_class "
                "WHERE relname IN ('app_settings', 'app_setting_secrets') "
                "AND relnamespace = 'public'::regnamespace ORDER BY relname"
            )
        )
    ).all()
    assert [tuple(row) for row in forced] == [
        ("app_setting_secrets", True),
        ("app_settings", True),
    ]
