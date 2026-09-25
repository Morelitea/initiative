"""a device signs its keys

Every key a device publishes is signed by that device's Ed25519 key, so a
client can check the directory it is handed (``app.services.platform.
dm_transport``, the device and one-time-key byte strings).

- ``dm_devices.signature``: the device's signature over its own keys and the
  account they belong to. NULL for a device registered before signing, until
  it next opens and signs itself.
- ``dm_one_time_keys.signature``: the device's signature over the key.
- ``dm_claim_one_time_key`` also returns whether the key is the fallback and
  its signature. A new return type, so the function is dropped and made again
  with the owner and grants 0225 gave it.
- The request path updates only ``dm_devices``' ``last_seen_at``,
  ``device_token_id`` and ``signature``.

Revision ID: 20260925_0397
Revises: 20260925_0396
Create Date: 2026-09-25
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260925_0397"
down_revision = "20260925_0396"
branch_labels = None
depends_on = None

READER = "app_dm_reader"
_WRITABLE_DEVICE_COLUMNS = "last_seen_at, device_token_id, signature"


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


_CLAIM_FUNCTION = """
CREATE OR REPLACE FUNCTION public.dm_claim_one_time_key(target_device uuid)
RETURNS TABLE (key_id text, public_key bytea, fallback boolean, signature bytea)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  owner_id int;
BEGIN
  SELECT d.user_id INTO owner_id FROM public.dm_devices d WHERE d.id = target_device;
  IF owner_id IS NULL THEN
    RETURN;
  END IF;
  IF owner_id <> NULLIF(current_setting('app.current_user_id', true), '')::int
     AND public.dm_apparent_permission(owner_id) <> 'open' THEN
    RETURN;
  END IF;

  -- An account that has stopped hearing from the caller does not spend a key on
  -- them. The reusable fallback answers instead, so the pool is untouched and
  -- the caller is told exactly what anybody else would be.
  IF EXISTS (
    SELECT 1 FROM public.user_ignores i
    WHERE i.user_id = owner_id
      AND i.ignored_user_id = NULLIF(current_setting('app.current_user_id', true), '')::int
  ) THEN
    RETURN QUERY
    SELECT k.key_id, k.public_key, k.fallback, k.signature FROM public.dm_one_time_keys k
    WHERE k.device_id = target_device AND k.fallback IS TRUE
    LIMIT 1;
    RETURN;
  END IF;

  -- One key, spent atomically: two callers racing take different rows rather
  -- than the same one, and the fallback is never consumed.
  RETURN QUERY
  DELETE FROM public.dm_one_time_keys k
  WHERE k.id = (
    SELECT inner_key.id FROM public.dm_one_time_keys inner_key
    WHERE inner_key.device_id = target_device AND inner_key.fallback IS FALSE
    ORDER BY inner_key.created_at
    FOR UPDATE SKIP LOCKED
    LIMIT 1
  )
  RETURNING k.key_id, k.public_key, k.fallback, k.signature;
  IF FOUND THEN
    RETURN;
  END IF;

  -- The pool is empty, so the reusable last-resort key answers instead of the
  -- device becoming unreachable.
  RETURN QUERY
  SELECT k.key_id, k.public_key, k.fallback, k.signature FROM public.dm_one_time_keys k
  WHERE k.device_id = target_device AND k.fallback IS TRUE
  LIMIT 1;
END;
$fn$
"""

#: 0225's function, restored by the downgrade.
_CLAIM_FUNCTION_0225 = """
CREATE OR REPLACE FUNCTION public.dm_claim_one_time_key(target_device uuid)
RETURNS TABLE (key_id text, public_key bytea)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  owner_id int;
BEGIN
  SELECT d.user_id INTO owner_id FROM public.dm_devices d WHERE d.id = target_device;
  IF owner_id IS NULL THEN
    RETURN;
  END IF;
  IF owner_id <> NULLIF(current_setting('app.current_user_id', true), '')::int
     AND public.dm_apparent_permission(owner_id) <> 'open' THEN
    RETURN;
  END IF;

  -- An account that has stopped hearing from the caller does not spend a key on
  -- them. The reusable fallback answers instead, so the pool is untouched and
  -- the caller is told exactly what anybody else would be.
  IF EXISTS (
    SELECT 1 FROM public.user_ignores i
    WHERE i.user_id = owner_id
      AND i.ignored_user_id = NULLIF(current_setting('app.current_user_id', true), '')::int
  ) THEN
    RETURN QUERY
    SELECT k.key_id, k.public_key FROM public.dm_one_time_keys k
    WHERE k.device_id = target_device AND k.fallback IS TRUE
    LIMIT 1;
    RETURN;
  END IF;

  -- One key, spent atomically: two callers racing take different rows rather
  -- than the same one, and the fallback is never consumed.
  RETURN QUERY
  DELETE FROM public.dm_one_time_keys k
  WHERE k.id = (
    SELECT inner_key.id FROM public.dm_one_time_keys inner_key
    WHERE inner_key.device_id = target_device AND inner_key.fallback IS FALSE
    ORDER BY inner_key.created_at
    FOR UPDATE SKIP LOCKED
    LIMIT 1
  )
  RETURNING k.key_id, k.public_key;
  IF FOUND THEN
    RETURN;
  END IF;

  -- The pool is empty, so the reusable last-resort key answers instead of the
  -- device becoming unreachable.
  RETURN QUERY
  SELECT k.key_id, k.public_key FROM public.dm_one_time_keys k
  WHERE k.device_id = target_device AND k.fallback IS TRUE
  LIMIT 1;
END;
$fn$
"""


def _claim_function(body: str) -> list[str]:
    return [
        "DROP FUNCTION IF EXISTS public.dm_claim_one_time_key(uuid)",
        body,
        f'GRANT CREATE ON SCHEMA public TO "{READER}"',
        f'ALTER FUNCTION public.dm_claim_one_time_key(uuid) OWNER TO "{READER}"',
        "REVOKE ALL ON FUNCTION public.dm_claim_one_time_key(uuid) FROM PUBLIC",
        f'REVOKE CREATE ON SCHEMA public FROM "{READER}"',
        "GRANT EXECUTE ON FUNCTION public.dm_claim_one_time_key(uuid) "
        f'TO "{_platform_base()}"',
    ]


def upgrade() -> None:
    op.add_column("dm_devices", sa.Column("signature", sa.LargeBinary(), nullable=True))
    op.add_column(
        "dm_one_time_keys", sa.Column("signature", sa.LargeBinary(), nullable=True)
    )
    base = _platform_base()
    for statement in [
        *_claim_function(_CLAIM_FUNCTION),
        f'REVOKE UPDATE ON TABLE public.dm_devices FROM "{base}"',
        f'GRANT UPDATE ({_WRITABLE_DEVICE_COLUMNS}) ON TABLE public.dm_devices TO "{base}"',
    ]:
        op.execute(statement)


def downgrade() -> None:
    base = _platform_base()
    for statement in [
        f'REVOKE UPDATE ({_WRITABLE_DEVICE_COLUMNS}) ON TABLE public.dm_devices FROM "{base}"',
        f'GRANT UPDATE ON TABLE public.dm_devices TO "{base}"',
        *_claim_function(_CLAIM_FUNCTION_0225),
    ]:
        op.execute(statement)
    op.drop_column("dm_one_time_keys", "signature")
    op.drop_column("dm_devices", "signature")
