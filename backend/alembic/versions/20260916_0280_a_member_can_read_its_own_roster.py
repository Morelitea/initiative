"""Naming the people on a conversation you are on.

``list_conversations`` answers a group's roster as handles, because a group
needs no accepted grant between every pair and a client can therefore be in a
conversation with somebody it has no way to look up.

It could not read those accounts directly. ``public.users`` is own-row for the
request path below moderator, so the query behind the list found nothing and
every handle came back empty -- and only for ordinary accounts, which is what
made it pass unnoticed.

So the roster is answered the way the rest of this rule answers questions about
somebody else: one ``SECURITY DEFINER`` entry point owned by ``app_dm_reader``,
narrow enough to say exactly what it is for. It answers only for a conversation
the caller is named on -- the same test the reading policies use -- and returns
only the two fields a handle is made of, which the bell line and the push
already name for the same people.

The reader's own reach on ``public.users`` grows by exactly those two columns.
It held ``id``, ``status`` and ``age_confirmed_at`` -- what the permission rule
asks about somebody else -- and naming the people on your own conversation is
now one of the questions this rule answers, so ``username`` and
``discriminator`` join them. Both are the public handle; nothing else on that
table moves.

Revision ID: 20260916_0280
Revises: 20260916_0279
Create Date: 2026-09-16
"""

from alembic import op

from app.core.config import settings


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


revision = "20260916_0280"
down_revision = "20260916_0279"
branch_labels = None
depends_on = None

READER = "app_dm_reader"

#: Takes the conversations rather than one, because the list asks about all of
#: them at once and a query each is a round trip each on a list nothing bounds.
#: The guard is still per conversation, so one the caller is not named on
#: contributes nothing rather than spoiling the answer.
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
    # The guard runs as the reader, because that is who the function runs as.
    op.execute(f'GRANT EXECUTE ON FUNCTION public.dm_on_roster(uuid) TO "{READER}"')


def downgrade() -> None:
    op.execute(f'REVOKE EXECUTE ON FUNCTION public.dm_on_roster(uuid) FROM "{READER}"')
    op.execute("DROP FUNCTION IF EXISTS public.dm_roster_handles(uuid[])")
    op.execute(
        f'REVOKE SELECT (username, discriminator) ON TABLE public.users FROM "{READER}"'
    )
