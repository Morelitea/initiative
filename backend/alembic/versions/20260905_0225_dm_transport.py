"""The direct-message transport: devices, prekeys, conversations and the queue.

Five tables in ``public``, all per-account and cross-guild, carrying nothing a
reader could open. What the server holds is a key directory of *public* keys, a
roster of who is talking to whom, and ciphertext waiting to be collected.

Access shape, the same as the four tables 0223 added: **the account holder's own
rows, and nothing else on the request path.** No platform-tier policy, no
guild-admin leg, no PAM leg, and ``app_guild_base`` is granted nothing at all.

Two exceptions to "own rows", both deliberate and both gated by the rule 0223
already shipped:

* **The directory.** Another account may read a device's public keys, and claim
  one prekey, where ``public.dm_apparent_permission`` already says ``open`` —
  that is, where an accepted message grant exists between the two.
* **The roster.** Knowing who the other party is means reading a row that is not
  yours, so ``public.dm_in_conversation`` answers it as a boolean instead, on
  the ``SECURITY DEFINER`` pattern 0223 established with ``app_dm_reader``.

``UPDATE`` is granted on ``dm_devices`` alone, where a collection moves
``last_seen_at``. A claimed prekey is deleted rather than marked, and a
collected message is deleted rather than flagged, so neither table has a state
column to disagree with itself.

Revision ID: 20260905_0225
Revises: 20260904_0224
Create Date: 2026-09-05
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260905_0225"
down_revision = "20260904_0224"
branch_labels = None
depends_on = None

#: The reader role 0223 created. Reused rather than duplicated: the rules here
#: read the same accounts, and a second reader would be a second thing to keep
#: in step.
#: The reader role 0223 created, reused here. Claiming a prekey is a delete, so
#: this role gains write on ``dm_one_time_keys`` alone -- narrower than a second
#: cluster-global role, which a database that already had one could not re-grant.
READER = "app_dm_reader"

_TABLES = (
    "dm_devices",
    "dm_one_time_keys",
    "dm_conversations",
    "dm_conversation_members",
    "dm_queue",
)

# NULLIF-guarded: an unset context leaves the value empty, and a bare ''::int
# would raise and fault the whole query rather than fail the policy.
_USER_ID = "NULLIF(current_setting('app.current_user_id', true), '')::int"

#: A device whose owner the caller may message today, or the caller's own.
_OWN_OR_OPEN_DEVICE = (
    f"(user_id = {_USER_ID} OR ({_USER_ID} IS NOT NULL "
    f"AND public.dm_apparent_permission(user_id) = 'open'))"
)

#: A prekey row belonging to one of the caller's own devices. Another account
#: never reads or deletes these directly -- it calls ``dm_claim_one_time_key``,
#: which spends exactly one.
_OWN_DEVICE_KEY = (
    "EXISTS (SELECT 1 FROM public.dm_devices d WHERE d.id = device_id "
    f"AND d.user_id = {_USER_ID})"
)

#: The caller's own devices, for reading and acknowledging their own mail.
_OWN_DEVICE_QUEUE = (
    "recipient_device_id IN (SELECT id FROM public.dm_devices "
    f"WHERE user_id = {_USER_ID})"
)

_FUNCTIONS = [
    """
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
    """,
    """
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
    """,
    """
    CREATE OR REPLACE FUNCTION public.dm_deliverable(target_id int)
    RETURNS boolean
    LANGUAGE plpgsql STABLE PARALLEL SAFE SECURITY DEFINER
    SET search_path = pg_catalog, public
    AS $fn$
    DECLARE
      actor_id int := NULLIF(current_setting('app.current_user_id', true), '')::int;
    BEGIN
      IF actor_id IS NULL THEN
        RAISE EXCEPTION 'dm_deliverable requires app.current_user_id';
      END IF;
      IF public.dm_apparent_permission(target_id) <> 'open' THEN
        RETURN false;
      END IF;
      RETURN NOT EXISTS (
        SELECT 1 FROM public.user_ignores i
        WHERE i.user_id = target_id AND i.ignored_user_id = actor_id
      );
    END;
    $fn$
    """,
]

#: What the reader needs beyond the grants 0223 gave it.
_CLAIM_FUNCTION = """
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

_READER_GRANTS = [
    "GRANT SELECT ON TABLE public.dm_conversation_members TO {r}",
    "GRANT SELECT (id, user_id) ON TABLE public.dm_devices TO {r}",
]

#: All rows of each, for the reader only.
_READER_POLICIES = [
    ("dm_conversation_members", "dm_reader_read"),
    ("dm_devices", "dm_reader_read"),
]

_NEW_FUNCTIONS = (
    ("dm_in_conversation", "uuid"),
    ("dm_device_in_conversation", "uuid, uuid"),
    ("dm_deliverable", "int"),
)


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def _run(statements: list[str]) -> None:
    for statement in statements:
        op.execute(statement)


def _create_tables() -> None:
    op.create_table(
        "dm_devices",
        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("identity_key", sa.LargeBinary(), nullable=False),
        sa.Column("fingerprint_key", sa.LargeBinary(), nullable=False),
        sa.Column("device_token_id", sa.Integer(), nullable=True),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["device_token_id"], ["user_tokens.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dm_devices_user", "dm_devices", ["user_id"])

    op.create_table(
        "dm_one_time_keys",
        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("key_id", sa.Text(), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column(
            "fallback", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["dm_devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "device_id", "key_id", name="uq_dm_one_time_keys_device_key"
        ),
    )
    op.create_index(
        "ix_dm_one_time_keys_device_fallback",
        "dm_one_time_keys",
        ["device_id", "fallback"],
    )

    op.create_table(
        "dm_conversations",
        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "dm_conversation_members",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        # Which side of the pair this row is. Two slots, unique per
        # conversation: a third member is rejected by the index rather than by
        # a count somebody else could be reading at the same moment.
        sa.Column("slot", sa.SmallInteger(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["dm_conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("conversation_id", "user_id"),
        sa.CheckConstraint("slot IN (0, 1)", name="ck_dm_conversation_members_slot"),
        sa.UniqueConstraint(
            "conversation_id", "slot", name="uq_dm_conversation_members_slot"
        ),
    )
    op.create_index(
        "ix_dm_conversation_members_user", "dm_conversation_members", ["user_id"]
    )

    op.create_table(
        "dm_queue",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_device_id", sa.Uuid(), nullable=False),
        sa.Column("message_type", sa.SmallInteger(), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["dm_conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["recipient_device_id"], ["dm_devices.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dm_queue_device_id", "dm_queue", ["recipient_device_id", "id"])


def upgrade() -> None:
    base = _platform_base()
    request_roles = f'app_guild_base, "{base}", app_user'

    _create_tables()

    statements: list[str] = []
    for table in _TABLES:
        qualified = f"public.{table}"
        statements += [
            f"ALTER TABLE {qualified} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {qualified} FORCE ROW LEVEL SECURITY",
            # The schema's default privileges hand every new public table to the
            # routed base roles, so they are wound back before anything is given.
            f"REVOKE ALL ON TABLE {qualified} FROM {request_roles}",
            f'GRANT SELECT, INSERT, DELETE ON TABLE {qualified} TO "{base}"',
        ]
    # A collection moves ``last_seen_at``; nothing else here is ever edited.
    statements.append(f'GRANT UPDATE ON TABLE public.dm_devices TO "{base}"')
    # The sequence behind ``dm_queue.id`` — INSERT on the table is not enough.
    statements.append(
        f'GRANT USAGE, SELECT ON SEQUENCE public.dm_queue_id_seq TO "{base}"'
    )

    # The reader, and the three rules it owns. This runs before the policies
    # below, because a policy naming a function cannot be created until the
    # function exists.
    statements += [
        f'GRANT "{READER}" TO CURRENT_USER WITH INHERIT TRUE, SET TRUE',
    ]
    statements += [grant.format(r=f'"{READER}"') for grant in _READER_GRANTS]
    for table, policy in _READER_POLICIES:
        statements += [
            f"DROP POLICY IF EXISTS {policy} ON public.{table}",
            f"CREATE POLICY {policy} ON public.{table} "
            f'AS PERMISSIVE FOR SELECT TO "{READER}" USING (true)',
        ]
    statements += _FUNCTIONS
    # Ownership can only be handed to a role that may create in the schema.
    # Given for the assignment and taken straight back.
    statements.append(f'GRANT CREATE ON SCHEMA public TO "{READER}"')
    for function, signature in _NEW_FUNCTIONS:
        statements += [
            f'ALTER FUNCTION public.{function}({signature}) OWNER TO "{READER}"',
            f"REVOKE ALL ON FUNCTION public.{function}({signature}) FROM PUBLIC",
        ]
    statements.append(f'REVOKE CREATE ON SCHEMA public FROM "{READER}"')

    # Claiming, which is the one write any of these rules performs. The request
    # path holds DELETE on its own pool only; another account spends exactly one
    # key, through this.
    statements += [
        f'GRANT SELECT, UPDATE, DELETE ON TABLE public.dm_one_time_keys TO "{READER}"',
        "DROP POLICY IF EXISTS dm_reader_keys ON public.dm_one_time_keys",
        "CREATE POLICY dm_reader_keys ON public.dm_one_time_keys "
        f'AS PERMISSIVE FOR ALL TO "{READER}" USING (true) WITH CHECK (true)',
        _CLAIM_FUNCTION,
        f'GRANT CREATE ON SCHEMA public TO "{READER}"',
        f'ALTER FUNCTION public.dm_claim_one_time_key(uuid) OWNER TO "{READER}"',
        "REVOKE ALL ON FUNCTION public.dm_claim_one_time_key(uuid) FROM PUBLIC",
        f'REVOKE CREATE ON SCHEMA public FROM "{READER}"',
        f'GRANT EXECUTE ON FUNCTION public.dm_claim_one_time_key(uuid) TO "{base}"',
    ]
    # ``dm_deliverable`` is asked by the send path about the other party, and
    # its answer is never returned to the caller.
    for function, signature in _NEW_FUNCTIONS:
        statements.append(
            f'GRANT EXECUTE ON FUNCTION public.{function}({signature}) TO "{base}"'
        )

    policies: list[tuple[str, str, str]] = [
        # (table, command, predicate)
        ("dm_devices", "SELECT", _OWN_OR_OPEN_DEVICE),
        ("dm_devices", "INSERT", f"user_id = {_USER_ID}"),
        ("dm_devices", "UPDATE", f"user_id = {_USER_ID}"),
        ("dm_devices", "DELETE", f"user_id = {_USER_ID}"),
        ("dm_one_time_keys", "SELECT", _OWN_DEVICE_KEY),
        ("dm_one_time_keys", "INSERT", _OWN_DEVICE_KEY),
        # Own pool only. Another account spends a key through
        # ``dm_claim_one_time_key``, which takes exactly one.
        ("dm_one_time_keys", "DELETE", _OWN_DEVICE_KEY),
        ("dm_conversations", "SELECT", "public.dm_in_conversation(id)"),
        # The row is created before its members exist, so there is no membership
        # to test yet. An empty conversation reaches nobody and holds nothing.
        ("dm_conversations", "INSERT", f"{_USER_ID} IS NOT NULL"),
        ("dm_conversations", "DELETE", "public.dm_in_conversation(id)"),
        (
            "dm_conversation_members",
            "SELECT",
            "public.dm_in_conversation(conversation_id)",
        ),
        (
            "dm_conversation_members",
            "INSERT",
            f"(user_id = {_USER_ID} OR ({_USER_ID} IS NOT NULL "
            "AND public.dm_apparent_permission(user_id) = 'open'))",
        ),
        ("dm_conversation_members", "DELETE", f"user_id = {_USER_ID}"),
        ("dm_queue", "SELECT", _OWN_DEVICE_QUEUE),
        (
            "dm_queue",
            "INSERT",
            "public.dm_in_conversation(conversation_id) AND "
            "public.dm_device_in_conversation(recipient_device_id, conversation_id)",
        ),
        ("dm_queue", "DELETE", _OWN_DEVICE_QUEUE),
    ]
    for table, command, predicate in policies:
        qualified = f"public.{table}"
        name = f"{table}_self_{command.lower()}"
        if command == "INSERT":
            body = f"WITH CHECK ({predicate})"
        elif command == "UPDATE":
            body = f"USING ({predicate}) WITH CHECK ({predicate})"
        else:
            body = f"USING ({predicate})"
        statements += [
            f"DROP POLICY IF EXISTS {name} ON {qualified}",
            f"CREATE POLICY {name} ON {qualified} "
            f'AS PERMISSIVE FOR {command} TO "{base}" {body}',
        ]

    # The system engine: erasure, and the stale-device sweep. No INSERT and no
    # UPDATE — nothing about a direct message is ever written by anything but
    # the account's own session.
    for table in _TABLES:
        statements.append(f"GRANT SELECT, DELETE ON TABLE public.{table} TO app_admin")

    _run(statements)


def downgrade() -> None:
    # Policies first, functions after: a policy that names a function is a
    # dependency on it, and Postgres refuses to drop the function while one
    # stands.
    statements = []
    for table in _TABLES:
        qualified = f"public.{table}"
        for command in ("select", "insert", "update", "delete"):
            statements.append(
                f"DROP POLICY IF EXISTS {table}_self_{command} ON {qualified}"
            )
        statements.append(f"ALTER TABLE {qualified} DISABLE ROW LEVEL SECURITY")
    for table, policy in _READER_POLICIES:
        statements.append(f"DROP POLICY IF EXISTS {policy} ON public.{table}")
    statements += [
        "DROP POLICY IF EXISTS dm_reader_keys ON public.dm_one_time_keys",
        "DROP FUNCTION IF EXISTS public.dm_claim_one_time_key(uuid)",
    ]
    for function, signature in reversed(_NEW_FUNCTIONS):
        statements.append(f"DROP FUNCTION IF EXISTS public.{function}({signature})")
    statements += [
        f'REVOKE ALL ON TABLE public.dm_conversation_members FROM "{READER}"',
        f'REVOKE ALL ON TABLE public.dm_devices FROM "{READER}"',
        f'REVOKE ALL ON TABLE public.dm_one_time_keys FROM "{READER}"',
    ]
    _run(statements)

    op.drop_index("ix_dm_queue_device_id", table_name="dm_queue")
    op.drop_table("dm_queue")
    op.drop_index(
        "ix_dm_conversation_members_user", table_name="dm_conversation_members"
    )
    op.drop_table("dm_conversation_members")
    op.drop_table("dm_conversations")
    op.drop_index("ix_dm_one_time_keys_device_fallback", table_name="dm_one_time_keys")
    op.drop_table("dm_one_time_keys")
    op.drop_index("ix_dm_devices_user", table_name="dm_devices")
    op.drop_table("dm_devices")
