"""DM consent is held by the database

The row policies on ``dm_conversation_members`` and ``contact_grants``
(``app.db.public_rls``) state who may write a membership or an answer. They
read three facts about rows the writer may not be able to see yet, so each is
one ``SECURITY DEFINER`` entry point owned by ``app_dm_reader``, as the rest of
the DM rule is:

- ``dm_roster_answered(conversation)``: somebody on the conversation has
  accepted. A member's own row is written only before anybody has.
- ``dm_roster_names(conversation, members)``: the conversation's roster names
  every one of them. A membership is written only on a roster naming both the
  writer and the member.
- ``dm_conversation_direct(conversation)``: the conversation is a pair. Only a
  pair's other member is written already accepted.
- ``dm_pair_connected(low, high)``: the pair has an accepted connection, asked
  only by one of the two. A message grant is written already accepted only for
  a connected pair.

The reader reads ``dm_conversations``' ``id``, ``kind`` and ``roster_key`` for
the second and third.

The request path updates only ``contact_grants``' ``state`` and
``responded_at``: an answer changes those and nothing else about the row. A
member's update to ``dm_conversations`` only releases the roster's name.

Revision ID: 20260928_0411
Revises: 20260927_0410
Create Date: 2026-09-28
"""

from alembic import op

from app.core.config import settings

revision = "20260928_0411"
down_revision = "20260927_0410"
branch_labels = None
depends_on = None

READER = "app_dm_reader"
_WRITABLE_GRANT_COLUMNS = "state, responded_at"

_ROSTER_ANSWERED = """
CREATE OR REPLACE FUNCTION public.dm_roster_answered(conversation uuid)
RETURNS boolean
LANGUAGE sql STABLE PARALLEL SAFE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $fn$
  SELECT EXISTS (
    SELECT 1 FROM public.dm_conversation_members m
    WHERE m.conversation_id = conversation AND m.accepted_at IS NOT NULL
  )
$fn$
"""

_ROSTER_NAMES = """
CREATE OR REPLACE FUNCTION public.dm_roster_names(conversation uuid, members int[])
RETURNS boolean
LANGUAGE sql STABLE PARALLEL SAFE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $fn$
  SELECT EXISTS (
    SELECT 1 FROM public.dm_conversations c
    WHERE c.id = conversation
      AND string_to_array(c.roster_key, ',')::int[] @> members
  )
$fn$
"""

_CONVERSATION_DIRECT = """
CREATE OR REPLACE FUNCTION public.dm_conversation_direct(conversation uuid)
RETURNS boolean
LANGUAGE sql STABLE PARALLEL SAFE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $fn$
  SELECT EXISTS (
    SELECT 1 FROM public.dm_conversations c
    WHERE c.id = conversation AND c.kind = 'direct'
  )
$fn$
"""

_PAIR_CONNECTED = """
CREATE OR REPLACE FUNCTION public.dm_pair_connected(low int, high int)
RETURNS boolean
LANGUAGE sql STABLE PARALLEL SAFE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $fn$
  SELECT NULLIF(current_setting('app.current_user_id', true), '')::int IN (low, high)
     AND EXISTS (
       SELECT 1 FROM public.contact_grants g
       WHERE g.user_id_low = low AND g.user_id_high = high
         AND g.kind = 'connection' AND g.state = 'accepted'
     )
$fn$
"""

_FUNCTIONS = (
    ("dm_roster_answered", "uuid", _ROSTER_ANSWERED),
    ("dm_roster_names", "uuid, int[]", _ROSTER_NAMES),
    ("dm_conversation_direct", "uuid", _CONVERSATION_DIRECT),
    ("dm_pair_connected", "int, int", _PAIR_CONNECTED),
)


#: (policy, table) the registry renders at boot from this revision on that
#: read the functions above, or that the revision this reverts to does not
#: name. A downgrade removes them; that revision's registry renders its own
#: at the next boot.
RENDERED_POLICIES: tuple[tuple[str, str], ...] = (
    ("dm_conversation_members_self_insert", "dm_conversation_members"),
    ("dm_conversations_self_update", "dm_conversations"),
    ("contact_grants_self_insert", "contact_grants"),
    ("contact_grants_self_update", "contact_grants"),
    ("dm_reader_read", "dm_conversations"),
)


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def upgrade() -> None:
    base = _platform_base()
    statements = [
        f'GRANT SELECT (id, kind, roster_key) ON TABLE public.dm_conversations TO "{READER}"',
        # Ownership can only be handed to a role that may create in the schema.
        f'GRANT CREATE ON SCHEMA public TO "{READER}"',
    ]
    for name, signature, body in _FUNCTIONS:
        statements += [
            body,
            f'ALTER FUNCTION public.{name}({signature}) OWNER TO "{READER}"',
            f"REVOKE ALL ON FUNCTION public.{name}({signature}) FROM PUBLIC",
            f'GRANT EXECUTE ON FUNCTION public.{name}({signature}) TO "{base}"',
        ]
    statements += [
        f'REVOKE CREATE ON SCHEMA public FROM "{READER}"',
        f'REVOKE UPDATE ON TABLE public.contact_grants FROM "{base}"',
        f"GRANT UPDATE ({_WRITABLE_GRANT_COLUMNS}) ON TABLE public.contact_grants "
        f'TO "{base}"',
    ]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    base = _platform_base()
    statements = [
        f"DROP POLICY IF EXISTS {policy} ON public.{table}"
        for policy, table in RENDERED_POLICIES
    ]
    statements += [
        f"REVOKE UPDATE ({_WRITABLE_GRANT_COLUMNS}) ON TABLE public.contact_grants "
        f'FROM "{base}"',
        f'GRANT UPDATE ON TABLE public.contact_grants TO "{base}"',
    ]
    statements += [
        f"DROP FUNCTION IF EXISTS public.{name}({signature})"
        for name, signature, _ in _FUNCTIONS
    ]
    statements.append(
        f'REVOKE SELECT (id, kind, roster_key) ON TABLE public.dm_conversations FROM "{READER}"'
    )
    for statement in statements:
        op.execute(statement)
