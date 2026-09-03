"""How full one account's mailbox is, asked by whoever is writing to it.

The send path refuses a message that would push the recipient past their
ceiling, which means the *sender's* session has to learn a number about the
*recipient's* queue — rows its own policies rightly hide. So it asks a function
instead, on the ``app_dm_reader`` pattern the rest of the DM rules use: a
``SECURITY DEFINER`` reader that returns a total and never a row.

Refusing a message is the honest failure. Accepting one and dropping it later
is not, which is why nothing on the server side expires a queued message and
this exists instead.

Revision ID: 20260905_0226
Revises: 20260905_0225
Create Date: 2026-09-05
"""

from alembic import op

from app.core.config import settings

revision = "20260905_0226"
down_revision = "20260905_0225"
branch_labels = None
depends_on = None

READER = "app_dm_reader"

_FUNCTION = """
CREATE OR REPLACE FUNCTION public.dm_queue_bytes(account_id int)
RETURNS bigint
LANGUAGE sql STABLE PARALLEL SAFE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $fn$
  SELECT COALESCE(SUM(octet_length(q.payload)), 0)::bigint
  FROM public.dm_queue q
  JOIN public.dm_devices d ON d.id = q.recipient_device_id
  WHERE d.user_id = account_id
$fn$
"""


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def upgrade() -> None:
    base = _platform_base()
    statements = [
        f'GRANT "{READER}" TO CURRENT_USER WITH INHERIT TRUE, SET TRUE',
        "GRANT SELECT (id, payload, recipient_device_id) "
        f'ON TABLE public.dm_queue TO "{READER}"',
        "DROP POLICY IF EXISTS dm_reader_read ON public.dm_queue",
        "CREATE POLICY dm_reader_read ON public.dm_queue "
        f'AS PERMISSIVE FOR SELECT TO "{READER}" USING (true)',
        _FUNCTION,
        f'GRANT CREATE ON SCHEMA public TO "{READER}"',
        f'ALTER FUNCTION public.dm_queue_bytes(int) OWNER TO "{READER}"',
        "REVOKE ALL ON FUNCTION public.dm_queue_bytes(int) FROM PUBLIC",
        f'REVOKE CREATE ON SCHEMA public FROM "{READER}"',
        f'GRANT EXECUTE ON FUNCTION public.dm_queue_bytes(int) TO "{base}"',
    ]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    statements = [
        "DROP FUNCTION IF EXISTS public.dm_queue_bytes(int)",
        "DROP POLICY IF EXISTS dm_reader_read ON public.dm_queue",
        f'REVOKE ALL ON TABLE public.dm_queue FROM "{READER}"',
    ]
    for statement in statements:
        op.execute(statement)
