"""Entry points for the two questions the request path actually asks.

``0223`` gave the request path ``dm_apparent_permission`` and
``dm_listable_in_guild``, both of which read the caller from
``app.current_user_id`` rather than taking one. The services built on top ask a
third question — *may I send this account a connection request* — which is
``may_connect``: both accounts active and age-confirmed, no policy consulted.

``dm_may_connect`` is that, in the same shape: caller from the request context,
so it answers about the caller and one other account and cannot be pointed at
two strangers.

The sweep that re-tests message grants is the other half. It works on pairs that
need not involve the caller — a community removal re-tests the grants of the
person who left — so it runs on the system engine, and ``dm_mutual_ask`` is
granted to ``app_admin`` alone for it. The request path still cannot reach it.

Revision ID: 20260904_0224
Revises: 20260904_0223
Create Date: 2026-09-04
"""

from alembic import op

from app.core.config import settings

revision = "20260904_0224"
down_revision = "20260904_0223"
branch_labels = None
depends_on = None

READER = "app_dm_reader"


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


_FUNCTION = """
CREATE OR REPLACE FUNCTION public.dm_may_connect(target_id int)
RETURNS boolean
LANGUAGE plpgsql STABLE PARALLEL SAFE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  actor_id int := NULLIF(current_setting('app.current_user_id', true), '')::int;
BEGIN
  IF actor_id IS NULL THEN
    RAISE EXCEPTION 'dm_may_connect requires app.current_user_id';
  END IF;
  IF actor_id = target_id THEN
    RETURN false;
  END IF;
  RETURN public.dm_reachable(actor_id) AND public.dm_reachable(target_id);
END;
$fn$
"""


def upgrade() -> None:
    base = _platform_base()
    statements = [
        _FUNCTION,
        f'GRANT "{READER}" TO CURRENT_USER WITH INHERIT TRUE, SET TRUE',
        f'GRANT CREATE ON SCHEMA public TO "{READER}"',
        f'ALTER FUNCTION public.dm_may_connect(int) OWNER TO "{READER}"',
        f'REVOKE CREATE ON SCHEMA public FROM "{READER}"',
        "REVOKE ALL ON FUNCTION public.dm_may_connect(int) FROM PUBLIC",
        f'GRANT EXECUTE ON FUNCTION public.dm_may_connect(int) TO "{base}"',
        # The sweep's pairwise test, for the system engine that runs it.
        "GRANT EXECUTE ON FUNCTION public.dm_mutual_ask(int, int) TO app_admin",
    ]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    statements = [
        "REVOKE ALL ON FUNCTION public.dm_mutual_ask(int, int) FROM app_admin",
        "DROP FUNCTION IF EXISTS public.dm_may_connect(int)",
    ]
    for statement in statements:
        op.execute(statement)
