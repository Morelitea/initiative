"""A roster is read from the public profile, like every other list of people.

0280 gave the roster its own ``SECURITY DEFINER`` entry point, because the
query behind the conversation list was reading ``public.users`` -- which is
own-row for the request path below moderator, so it answered for nobody and
every handle came back empty.

Reading ``public.users`` was the mistake. ``public.user_profiles`` (0214) is
exactly the thing that was wanted: the public columns of any account, published
to every signed-in session through a view owned by ``app_profile_reader``. It
is what the contact list reads, and what every other surface that draws a
person reads. The roster now reads it too, so there is one projection of what
is public about an account rather than two.

It also carries the picture and the decorations, which a handle-only entry
point could not, so a group's roster draws its people the way a pair does.

``dm_roster_handles`` goes, and with it the two columns of ``public.users``
0280 gave ``app_dm_reader``. That reader is back to ``id``, ``status`` and
``age_confirmed_at`` -- what the permission rule asks about somebody else --
which is the whole of its reach again.

Revision ID: 20260916_0283
Revises: 20260916_0282
Create Date: 2026-09-16
"""

from alembic import op

from app.core.config import settings


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


revision = "20260916_0283"
down_revision = "20260916_0282"
branch_labels = None
depends_on = None

READER = "app_dm_reader"

#: 0280's function, restored verbatim by the downgrade.
_ROSTER_HANDLES = """
CREATE OR REPLACE FUNCTION public.dm_roster_handles(conversations uuid[])
RETURNS TABLE (member_id int, username text, discriminator int)
LANGUAGE sql STABLE PARALLEL SAFE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $fn$
  SELECT DISTINCT u.id, u.username, u.discriminator::int
    FROM public.dm_conversation_members m
    JOIN public.users u ON u.id = m.user_id
   WHERE m.conversation_id = ANY(conversations)
     AND public.dm_on_roster(m.conversation_id)
$fn$
"""


def upgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.dm_roster_handles(uuid[])")
    op.execute(f'REVOKE EXECUTE ON FUNCTION public.dm_on_roster(uuid) FROM "{READER}"')
    op.execute(
        f'REVOKE SELECT (username, discriminator) ON TABLE public.users FROM "{READER}"'
    )


def downgrade() -> None:
    base = _platform_base()
    op.execute(
        f'GRANT SELECT (username, discriminator) ON TABLE public.users TO "{READER}"'
    )
    op.execute(f'GRANT CREATE ON SCHEMA public TO "{READER}"')
    op.execute(_ROSTER_HANDLES)
    op.execute('ALTER FUNCTION public.dm_roster_handles(uuid[]) OWNER TO "%s"' % READER)
    op.execute("REVOKE ALL ON FUNCTION public.dm_roster_handles(uuid[]) FROM PUBLIC")
    op.execute(f'REVOKE CREATE ON SCHEMA public FROM "{READER}"')
    op.execute(
        f'GRANT EXECUTE ON FUNCTION public.dm_roster_handles(uuid[]) TO "{base}"'
    )
    op.execute(f'GRANT EXECUTE ON FUNCTION public.dm_on_roster(uuid) TO "{READER}"')
