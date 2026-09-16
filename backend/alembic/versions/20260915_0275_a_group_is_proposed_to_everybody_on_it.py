"""A roster can be proposed, and answered.

Three things a group needs that a pair never did.

**``dm_roster_unreachable_pair``** is the all-pairs reachability rule as one
entry point. Everybody on a roster must be able to reach everybody else --
``dm_mutual_ask`` for every pair -- because a group conversation is one where
everybody can actually talk to everybody. It answers with the first pair that
cannot, lowest ids first so the answer is stable, and null when the roster is
fine. A third entry point beside the two 0223 shipped, for the same reason
those two exist: the rule underneath stays uncallable from the request path.

**``dm_on_roster``** widens what a *pending* invitee may read. Membership means
an answered invitation (``dm_in_conversation``), and somebody still deciding is
not a member -- but they have to see the conversation and the whole roster to
decide, because seeing who is on it is what makes accepting consent rather than
notification. So the two reading policies defer to "named on this roster" while
the queue keeps deferring to "on it".

**An invitee may answer.** ``accepted_at`` is the one column a member ever
writes, and the grant is on that column alone. Declining is the ordinary leave,
which already deletes the row.

Revision ID: 20260915_0275
Revises: 20260915_0274
Create Date: 2026-09-15
"""

from alembic import op

from app.core.config import settings


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


revision = "20260915_0275"
down_revision = "20260915_0274"
branch_labels = None
depends_on = None

READER = "app_dm_reader"

_UNREACHABLE_PAIR = """
CREATE OR REPLACE FUNCTION public.dm_roster_unreachable_pair(ids int[])
RETURNS int[]
LANGUAGE sql STABLE PARALLEL SAFE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $fn$
  SELECT ARRAY[a.id, b.id]
    FROM unnest(ids) AS a(id)
    JOIN unnest(ids) AS b(id) ON a.id < b.id
   WHERE NOT public.dm_mutual_ask(a.id, b.id)
   ORDER BY a.id, b.id
   LIMIT 1
$fn$
"""

_ON_ROSTER = """
CREATE OR REPLACE FUNCTION public.dm_on_roster(conversation uuid)
RETURNS boolean
LANGUAGE sql STABLE PARALLEL SAFE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $fn$
  SELECT EXISTS (
    SELECT 1 FROM public.dm_conversation_members m
    WHERE m.conversation_id = conversation
      AND m.user_id = NULLIF(current_setting('app.current_user_id', true), '')::int
  )
$fn$
"""


def upgrade() -> None:
    base = _platform_base()

    # Owned by the reader, like the rest of the rule, so the request path gets
    # exactly the entry points it is granted and nothing underneath them.
    op.execute(f'GRANT CREATE ON SCHEMA public TO "{READER}"')
    op.execute(_UNREACHABLE_PAIR)
    op.execute(
        f'ALTER FUNCTION public.dm_roster_unreachable_pair(int[]) OWNER TO "{READER}"'
    )
    op.execute(
        "REVOKE ALL ON FUNCTION public.dm_roster_unreachable_pair(int[]) FROM PUBLIC"
    )
    op.execute(f'REVOKE CREATE ON SCHEMA public FROM "{READER}"')
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.dm_roster_unreachable_pair(int[]) "
        f'TO "{base}"'
    )

    op.execute(_ON_ROSTER)
    op.execute("REVOKE ALL ON FUNCTION public.dm_on_roster(uuid) FROM PUBLIC")
    op.execute(f'GRANT EXECUTE ON FUNCTION public.dm_on_roster(uuid) TO "{base}"')

    # Somebody deciding has to see what they are deciding about.
    for table, column in (
        ("dm_conversations", "id"),
        ("dm_conversation_members", "conversation_id"),
    ):
        policy = f"{table}_self_select"
        op.execute(f"DROP POLICY IF EXISTS {policy} ON public.{table}")
        op.execute(
            f"CREATE POLICY {policy} ON public.{table} "
            f'AS PERMISSIVE FOR SELECT TO "{base}" '
            f"USING (public.dm_on_roster({column}))"
        )

    # Answering an invitation is the one write a member makes to their own row.
    op.execute(
        f'GRANT UPDATE (accepted_at) ON TABLE public.dm_conversation_members TO "{base}"'
    )
    op.execute(
        "DROP POLICY IF EXISTS dm_conversation_members_self_update "
        "ON public.dm_conversation_members"
    )
    op.execute(
        "CREATE POLICY dm_conversation_members_self_update "
        "ON public.dm_conversation_members "
        f'AS PERMISSIVE FOR UPDATE TO "{base}" '
        "USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::int) "
        "WITH CHECK (user_id = NULLIF(current_setting('app.current_user_id', true), '')::int)"
    )


def downgrade() -> None:
    base = _platform_base()

    op.execute(
        "DROP POLICY IF EXISTS dm_conversation_members_self_update "
        "ON public.dm_conversation_members"
    )
    op.execute(
        "REVOKE UPDATE (accepted_at) ON TABLE public.dm_conversation_members "
        f'FROM "{base}"'
    )
    for table, column in (
        ("dm_conversations", "id"),
        ("dm_conversation_members", "conversation_id"),
    ):
        policy = f"{table}_self_select"
        op.execute(f"DROP POLICY IF EXISTS {policy} ON public.{table}")
        op.execute(
            f"CREATE POLICY {policy} ON public.{table} "
            f'AS PERMISSIVE FOR SELECT TO "{base}" '
            f"USING (public.dm_in_conversation({column}))"
        )
    op.execute("DROP FUNCTION IF EXISTS public.dm_on_roster(uuid)")
    op.execute("DROP FUNCTION IF EXISTS public.dm_roster_unreachable_pair(int[])")
