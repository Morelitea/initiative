"""A conversation is identified by who is on it, not by being a pair.

``dm_conversation_members`` held exactly two rows, and a unique ``slot`` index
was what held it there. Lifting that is most of this migration; the rest is
giving a conversation the two things it needs once a roster can be any size.

**``roster_key``** is the sorted member ids as text -- ``"7,19,44"`` -- written
once from the roster the conversation was made with and never updated. It is
what makes "one thread per set of people" a property of the table rather than a
lookup somebody could be reading while somebody else inserts. Plain rather than
hashed: the roster it encodes is already sitting in ``dm_conversation_members``
one row at a time, so hashing would hide nothing and make the row unreadable in
a shell. Its unique index is composite with ``kind`` so a pair's ``direct``
thread can never contend for a key with a group.

It is **nullable**, and only for two tails. A conversation everybody has left
keeps its row and has no roster left to build a key out of; and where a pair
raced and opened two channels before there was an index to stop them, the older
thread takes the key and the younger keeps a null rather than have one of two
real histories thrown away. Postgres treats nulls as distinct in a unique index,
so neither tail collides or reserves a key a live roster could want. Every
conversation made from here on has one.

**``accepted_at``** is null while somebody has been asked and has not answered.
Nothing can ask yet -- the invitation surface is a later change -- so every row
this migration writes is accepted, and what lands here is the column and the
leg in ``dm_in_conversation`` that reads it, so membership means "on it" rather
than "named on it" before anything can tell the difference.

Revision ID: 20260915_0273
Revises: 20260915_0272
Create Date: 2026-09-15
"""

import sqlalchemy as sa
from alembic import op

revision = "20260915_0273"
down_revision = "20260915_0272"
branch_labels = None
depends_on = None


#: Membership now means an answered invitation. The function is the only place
#: that says so, and every policy defers to it.
_IN_CONVERSATION = """
CREATE OR REPLACE FUNCTION public.dm_in_conversation(conversation uuid)
RETURNS boolean
LANGUAGE sql STABLE PARALLEL SAFE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $fn$
  SELECT EXISTS (
    SELECT 1 FROM public.dm_conversation_members m
    WHERE m.conversation_id = conversation
      AND m.user_id = NULLIF(current_setting('app.current_user_id', true), '')::int
      AND m.accepted_at IS NOT NULL
  )
$fn$
"""

_IN_CONVERSATION_BEFORE = """
CREATE OR REPLACE FUNCTION public.dm_in_conversation(conversation uuid)
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

#: A device belongs to somebody who is actually on the conversation, not to
#: somebody who has only been asked.
_DEVICE_IN_CONVERSATION = """
CREATE OR REPLACE FUNCTION public.dm_device_in_conversation(
  device uuid, conversation uuid
)
RETURNS boolean
LANGUAGE sql STABLE PARALLEL SAFE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $fn$
  SELECT EXISTS (
    SELECT 1
    FROM public.dm_devices d
    JOIN public.dm_conversation_members m ON m.user_id = d.user_id
    WHERE d.id = device
      AND m.conversation_id = conversation
      AND m.accepted_at IS NOT NULL
  )
$fn$
"""

_DEVICE_IN_CONVERSATION_BEFORE = """
CREATE OR REPLACE FUNCTION public.dm_device_in_conversation(
  device uuid, conversation uuid
)
RETURNS boolean
LANGUAGE sql STABLE PARALLEL SAFE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $fn$
  SELECT EXISTS (
    SELECT 1
    FROM public.dm_devices d
    JOIN public.dm_conversation_members m ON m.user_id = d.user_id
    WHERE d.id = device AND m.conversation_id = conversation
  )
$fn$
"""

#: Both tables force row-level security, so a migration's own writes are
#: policy-bound and the policies key on request settings a migration has none
#: of. Lifted for the backfill and restored in the same transaction.
#:
#: **Only the oldest conversation of each roster is keyed.** Opening a channel
#: has always been idempotent, but it was idempotent by looking first, so two
#: requests arriving together could both look, both find nothing, and both
#: insert -- which is the race the index being added here is what finally
#: settles. Any pair that won it twice has two threads with real history on
#: somebody's device, and merging them would invent a conversation that never
#: happened. So the older one takes the key and the younger keeps a null: still
#: reachable by everybody on it, no longer what a roster lookup finds.
_ROSTER_KEY_BACKFILL = """
WITH rosters AS (
  SELECT m.conversation_id,
         string_agg(m.user_id::text, ',' ORDER BY m.user_id) AS key
    FROM public.dm_conversation_members m
   GROUP BY m.conversation_id
), ranked AS (
  SELECT r.conversation_id,
         r.key,
         row_number() OVER (
           PARTITION BY c.kind, r.key ORDER BY c.created_at, c.id
         ) AS rn
    FROM rosters r
    JOIN public.dm_conversations c ON c.id = r.conversation_id
)
UPDATE public.dm_conversations c
   SET roster_key = ranked.key
  FROM ranked
 WHERE ranked.conversation_id = c.id AND ranked.rn = 1
"""

#: How many distinct rosters exist -- which is how many rows the backfill should
#: key, duplicates excluded.
_DISTINCT_ROSTERS = """
SELECT count(*) FROM (
  SELECT c.kind, string_agg(m.user_id::text, ',' ORDER BY m.user_id)
    FROM public.dm_conversation_members m
    JOIN public.dm_conversations c ON c.id = m.conversation_id
   GROUP BY m.conversation_id, c.kind
) g
"""


def upgrade() -> None:
    bind = op.get_bind()

    op.add_column(
        "dm_conversations",
        sa.Column(
            "kind", sa.Text(), nullable=False, server_default=sa.text("'direct'")
        ),
    )
    op.add_column("dm_conversations", sa.Column("roster_key", sa.Text(), nullable=True))
    op.add_column(
        "dm_conversation_members",
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_dm_conversations_kind",
        "dm_conversations",
        "kind IN ('direct', 'group')",
    )

    # Every conversation that exists today is a pair whose members both agreed
    # to it before it was made -- an accepted request is what opened it.
    op.execute("ALTER TABLE public.dm_conversation_members NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.dm_conversations NO FORCE ROW LEVEL SECURITY")
    try:
        accepted = bind.execute(
            sa.text(
                "UPDATE public.dm_conversation_members "
                "SET accepted_at = joined_at WHERE accepted_at IS NULL"
            )
        ).rowcount
        members = bind.execute(
            sa.text("SELECT count(*) FROM public.dm_conversation_members")
        ).scalar_one()
        # A backfill that silently reached none of the rows is the failure this
        # asserts against: the count is read back rather than assumed.
        assert accepted == members, (
            f"accepted_at backfill touched {accepted} of {members} membership rows"
        )

        keyed = bind.execute(sa.text(_ROSTER_KEY_BACKFILL)).rowcount
        # Counted over conversations rather than distinct keys: two threads with
        # the same roster are two rows here and one key, and only one of them is
        # meant to get it.
        rosters = bind.execute(sa.text(_DISTINCT_ROSTERS)).scalar_one()
        distinct = bind.execute(
            sa.text(
                "SELECT count(*) FROM (SELECT DISTINCT c.kind, r.key FROM ("
                "  SELECT conversation_id, string_agg(user_id::text, ',' "
                "         ORDER BY user_id) AS key"
                "    FROM public.dm_conversation_members GROUP BY conversation_id"
                ") r JOIN public.dm_conversations c ON c.id = r.conversation_id) d"
            )
        ).scalar_one()
        assert keyed == distinct, (
            f"roster_key backfill keyed {keyed} of {distinct} distinct rosters"
        )
        if rosters != distinct:
            # Not fatal, and not silent: the younger duplicates keep a null key.
            print(
                f"  {rosters - distinct} duplicate roster(s) left unkeyed; "
                "the oldest thread of each roster holds the key"
            )
    finally:
        op.execute("ALTER TABLE public.dm_conversations FORCE ROW LEVEL SECURITY")
        op.execute(
            "ALTER TABLE public.dm_conversation_members FORCE ROW LEVEL SECURITY"
        )

    # The pair constraint, and the column that carried it.
    op.drop_constraint(
        "uq_dm_conversation_members_slot", "dm_conversation_members", type_="unique"
    )
    op.drop_constraint(
        "ck_dm_conversation_members_slot", "dm_conversation_members", type_="check"
    )
    op.drop_column("dm_conversation_members", "slot")

    op.create_index(
        "uq_dm_conversations_roster",
        "dm_conversations",
        ["kind", "roster_key"],
        unique=True,
    )

    op.execute(_IN_CONVERSATION)
    op.execute(_DEVICE_IN_CONVERSATION)


def downgrade() -> None:
    bind = op.get_bind()

    op.execute(_IN_CONVERSATION_BEFORE)
    op.execute(_DEVICE_IN_CONVERSATION_BEFORE)
    op.drop_index("uq_dm_conversations_roster", table_name="dm_conversations")

    # Anything with a roster that is not a pair cannot be expressed by the
    # shape being restored, and there is no honest way to pick two of them.
    oversized = bind.execute(
        sa.text(
            "SELECT count(*) FROM (SELECT conversation_id FROM "
            "public.dm_conversation_members GROUP BY conversation_id "
            "HAVING count(*) > 2) g"
        )
    ).scalar_one()
    if oversized:
        raise RuntimeError(
            f"{oversized} conversation(s) have more than two members; "
            "the two-slot shape cannot hold them"
        )

    op.add_column(
        "dm_conversation_members",
        sa.Column("slot", sa.SmallInteger(), nullable=True),
    )
    op.execute("ALTER TABLE public.dm_conversation_members NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(
            """
            UPDATE public.dm_conversation_members m
               SET slot = s.rn - 1
              FROM (
                SELECT conversation_id, user_id,
                       row_number() OVER (
                         PARTITION BY conversation_id ORDER BY joined_at, user_id
                       ) AS rn
                  FROM public.dm_conversation_members
              ) s
             WHERE s.conversation_id = m.conversation_id AND s.user_id = m.user_id
            """
        )
    finally:
        op.execute(
            "ALTER TABLE public.dm_conversation_members FORCE ROW LEVEL SECURITY"
        )
    op.alter_column("dm_conversation_members", "slot", nullable=False)
    op.create_check_constraint(
        "ck_dm_conversation_members_slot",
        "dm_conversation_members",
        "slot IN (0, 1)",
    )
    op.create_unique_constraint(
        "uq_dm_conversation_members_slot",
        "dm_conversation_members",
        ["conversation_id", "slot"],
    )

    op.drop_column("dm_conversation_members", "accepted_at")
    op.drop_constraint("ck_dm_conversations_kind", "dm_conversations", type_="check")
    op.drop_column("dm_conversations", "roster_key")
    op.drop_column("dm_conversations", "kind")
