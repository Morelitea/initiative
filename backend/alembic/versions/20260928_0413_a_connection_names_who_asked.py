"""a connection names who asked

``dm_connection_requester(low, high)`` answers who asked for the pair's
accepted connection, asked only by one of the two, and NULL otherwise. The
message grant a connection opens names that person, so a grant written already
accepted names either its writer or them. One ``SECURITY DEFINER`` entry point
owned by ``app_dm_reader``, as the rest of the DM rule is; the reader already
reads ``contact_grants``.

Revision ID: 20260928_0413
Revises: 20260928_0412
Create Date: 2026-09-28
"""

from alembic import op

from app.core.config import settings

revision = "20260928_0413"
down_revision = "20260928_0412"
branch_labels = None
depends_on = None

READER = "app_dm_reader"
_SIGNATURE = "dm_connection_requester(int, int)"

_CONNECTION_REQUESTER = """
CREATE OR REPLACE FUNCTION public.dm_connection_requester(low int, high int)
RETURNS int
LANGUAGE sql STABLE PARALLEL SAFE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $fn$
  SELECT g.requested_by FROM public.contact_grants g
   WHERE NULLIF(current_setting('app.current_user_id', true), '')::int IN (low, high)
     AND g.user_id_low = low AND g.user_id_high = high
     AND g.kind = 'connection' AND g.state = 'accepted'
$fn$
"""

#: (policy, table) the registry renders at boot from this revision on that
#: read the function above. A downgrade removes them; that revision's registry
#: renders its own at the next boot.
RENDERED_POLICIES: tuple[tuple[str, str], ...] = (
    ("contact_grants_self_insert", "contact_grants"),
)


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def upgrade() -> None:
    base = _platform_base()
    for statement in (
        # Ownership can only be handed to a role that may create in the schema.
        f'GRANT CREATE ON SCHEMA public TO "{READER}"',
        _CONNECTION_REQUESTER,
        f'ALTER FUNCTION public.{_SIGNATURE} OWNER TO "{READER}"',
        f"REVOKE ALL ON FUNCTION public.{_SIGNATURE} FROM PUBLIC",
        f'GRANT EXECUTE ON FUNCTION public.{_SIGNATURE} TO "{base}"',
        f'REVOKE CREATE ON SCHEMA public FROM "{READER}"',
    ):
        op.execute(statement)


def downgrade() -> None:
    for policy, table in RENDERED_POLICIES:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON public.{table}")
    op.execute(f"DROP FUNCTION IF EXISTS public.{_SIGNATURE}")
