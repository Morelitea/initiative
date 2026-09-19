"""Being on a group together is the accepted ask.

``dm_apparent_permission`` answered ``open`` only where an accepted **message**
grant existed between the pair. Two people who agreed to the same group have no
such grant -- nobody asked anybody one-to-one -- so the rule left them at
``may_request``, which is not enough to read each other's device keys or to be
sent anything. A group of people who had never messaged one-to-one could be
made and then could not be used.

Agreeing to a roster is the ask and the answer in one: everybody on it saw who
else was on it and said yes. So an accepted membership of the same conversation
now satisfies the same leg an accepted message grant does.

It sits **after** ``dm_mutual_ask``, alongside the grant it joins rather than
ahead of it, so the rest of the rule is unchanged: somebody who narrows who may
message them still narrows it, on a group exactly as on a pair.

A membership that has not been answered carries nothing, which is what keeps an
invitation an invitation.

The other half is naming somebody in the first place. Writing their row asked
for ``open`` between the two of you, which nobody has at the moment a roster is
proposed -- so a group of people who had never messaged one-to-one could not be
made at all. Naming somebody now asks only that you **may ask** them, which is
the same standing a message request needs, because that is what proposing a
roster is. A pair still needs the accepted ask: ``create_conversation`` requires
it before it writes anything.

``dm_roster_unreachable_pair`` is rewritten in ``plpgsql``. It was the only
granted entry point written in ``sql`` that calls one of the rule's inner
functions, and the reader's rights did not survive to that call -- the two
entry points 0223 granted are both ``plpgsql`` for the same reason. The body is
otherwise unchanged.

Revision ID: 20260916_0282
Revises: 20260916_0281
Create Date: 2026-09-16
"""

from alembic import op

from app.core.config import settings


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


#: Naming somebody on a roster. ``may_request`` is enough, because proposing a
#: roster *is* the request; ``denied`` is not.
_MAY_ASK = (
    "(user_id = NULLIF(current_setting('app.current_user_id', true), '')::int "
    "OR (NULLIF(current_setting('app.current_user_id', true), '')::int IS NOT NULL "
    "AND public.dm_apparent_permission(user_id) <> 'denied'))"
)

#: What it was: an accepted ask between the two of you, one-to-one.
_ALREADY_OPEN = (
    "(user_id = NULLIF(current_setting('app.current_user_id', true), '')::int "
    "OR (NULLIF(current_setting('app.current_user_id', true), '')::int IS NOT NULL "
    "AND public.dm_apparent_permission(user_id) = 'open'))"
)

_ROSTER_PAIR_PLPGSQL = """
CREATE OR REPLACE FUNCTION public.dm_roster_unreachable_pair(ids int[])
RETURNS int[]
LANGUAGE plpgsql STABLE PARALLEL SAFE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  found int[];
BEGIN
  SELECT ARRAY[a.id, b.id] INTO found
    FROM unnest(ids) AS a(id)
    JOIN unnest(ids) AS b(id) ON a.id < b.id
   WHERE NOT public.dm_mutual_ask(a.id, b.id)
   ORDER BY a.id, b.id
   LIMIT 1;
  RETURN found;
END;
$fn$
"""

_ROSTER_PAIR_SQL = """
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

revision = "20260916_0282"
down_revision = "20260916_0281"
branch_labels = None
depends_on = None

_WITH_GROUPS = """
CREATE OR REPLACE FUNCTION public.dm_apparent_permission(target_id int)
RETURNS text
LANGUAGE plpgsql STABLE PARALLEL SAFE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  actor_id int := NULLIF(current_setting('app.current_user_id', true), '')::int;
BEGIN
  IF actor_id IS NULL THEN
    RAISE EXCEPTION 'dm_apparent_permission requires app.current_user_id';
  END IF;
  IF NOT public.dm_mutual_ask(actor_id, target_id) THEN
    RETURN 'denied';
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.contact_grants g
    WHERE g.user_id_low = LEAST(actor_id, target_id)
      AND g.user_id_high = GREATEST(actor_id, target_id)
      AND g.kind = 'message'
      AND g.state = 'accepted'
  ) THEN
    RETURN 'open';
  END IF;
  IF EXISTS (
    SELECT 1
    FROM public.dm_conversation_members mine
    JOIN public.dm_conversation_members theirs
      ON theirs.conversation_id = mine.conversation_id
    WHERE mine.user_id = actor_id
      AND mine.accepted_at IS NOT NULL
      AND theirs.user_id = target_id
      AND theirs.accepted_at IS NOT NULL
  ) THEN
    RETURN 'open';
  END IF;
  RETURN 'may_request';
END;
$fn$
"""

_WITHOUT_GROUPS = """
CREATE OR REPLACE FUNCTION public.dm_apparent_permission(target_id int)
RETURNS text
LANGUAGE plpgsql STABLE PARALLEL SAFE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  actor_id int := NULLIF(current_setting('app.current_user_id', true), '')::int;
BEGIN
  IF actor_id IS NULL THEN
    RAISE EXCEPTION 'dm_apparent_permission requires app.current_user_id';
  END IF;
  IF NOT public.dm_mutual_ask(actor_id, target_id) THEN
    RETURN 'denied';
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.contact_grants g
    WHERE g.user_id_low = LEAST(actor_id, target_id)
      AND g.user_id_high = GREATEST(actor_id, target_id)
      AND g.kind = 'message'
      AND g.state = 'accepted'
  ) THEN
    RETURN 'open';
  END IF;
  RETURN 'may_request';
END;
$fn$
"""


def _insert_policy(predicate: str) -> None:
    base = _platform_base()
    op.execute(
        "DROP POLICY IF EXISTS dm_conversation_members_self_insert "
        "ON public.dm_conversation_members"
    )
    op.execute(
        "CREATE POLICY dm_conversation_members_self_insert "
        "ON public.dm_conversation_members "
        f'AS PERMISSIVE FOR INSERT TO "{base}" WITH CHECK ({predicate})'
    )


def upgrade() -> None:
    op.execute(_WITH_GROUPS)
    op.execute(_ROSTER_PAIR_PLPGSQL)
    _insert_policy(_MAY_ASK)


def downgrade() -> None:
    _insert_policy(_ALREADY_OPEN)
    op.execute(_ROSTER_PAIR_SQL)
    op.execute(_WITHOUT_GROUPS)
