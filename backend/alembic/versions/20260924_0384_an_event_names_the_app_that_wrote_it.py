"""an event names the app that wrote it

``event_outbox.actor_install_id``: the installed app whose request wrote the
change, beside ``actor_user_id``. ``public.capture_change`` reads it from
``app.current_install_id``, the same request context the gates read an install
from, and each actor is read on its own: an app acting as its community names
no person, and a table whose events name no actor names neither.

Nullable and without a foreign key, like ``actor_user_id``: the log outlives
what it describes, and every existing row was written by a person or by the
system. Nothing is backfilled.

The column is added in every guild schema before the function that writes it
is replaced, and the function is put back before the column is dropped. Both
bodies are stated here in full, so this revision reads the same whatever the
module says later.

Revision ID: 20260924_0384
Revises: 20260924_0383
Create Date: 2026-09-24
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260924_0384"
down_revision = "20260924_0383"
branch_labels = None
depends_on = None

#: ``public.capture_change`` before this revision.
CAPTURE_BEFORE = """
CREATE OR REPLACE FUNCTION public.capture_change() RETURNS trigger
    LANGUAGE plpgsql AS $capture$
DECLARE
    v_row        record;
    v_initiative integer;
    v_action     text;
    v_changed    text[] := '{}';
    v_resource   integer;
    v_type       text := TG_ARGV[1];
    v_actor      integer;
    v_new        jsonb;
    v_old        jsonb;
    v_facet      text := TG_ARGV[3];
    v_parents    jsonb := '[]'::jsonb;
    v_was_quiet  boolean := false;
    v_is_quiet   boolean := false;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_row := OLD;
    ELSE
        v_row := NEW;
    END IF;

    -- Some content exists before it is anybody else's business. While a row is
    -- quiet it says nothing at all, and crossing out of that is what gets
    -- reported — as a create, so a consumer never has to know the convention.
    -- Asked first, so a row nobody is to hear about pays for no lookup either.
    IF TG_ARGV[8] <> '' THEN
        IF TG_OP <> 'INSERT' THEN
            EXECUTE 'SELECT ' || TG_ARGV[8] INTO v_was_quiet USING OLD;
        END IF;
        IF TG_OP <> 'DELETE' THEN
            EXECUTE 'SELECT ' || TG_ARGV[8] INTO v_is_quiet USING NEW;
        END IF;
        IF (TG_OP = 'INSERT' AND v_is_quiet)
           OR (TG_OP = 'DELETE' AND v_was_quiet)
           OR (TG_OP = 'UPDATE' AND v_was_quiet AND v_is_quiet) THEN
            RETURN NULL;
        END IF;
    END IF;

    -- Which initiative this row belongs to, per its registry entry. A NULL is
    -- expected for a guild-wide table and means exactly that; anywhere else it
    -- means the initiative no longer resolves — an orphaned child during a
    -- parent cascade, whose parent emits its own delete — so the row is skipped
    -- rather than broadcast without a scope.
    EXECUTE 'SELECT ' || TG_ARGV[0] INTO v_initiative USING v_row;
    IF v_initiative IS NULL AND TG_ARGV[5] <> 'guild' THEN
        RETURN NULL;
    END IF;

    EXECUTE 'SELECT ' || TG_ARGV[2] INTO v_resource USING v_row;
    IF v_resource IS NULL THEN
        RETURN NULL;
    END IF;

    -- A polymorphic facet names its parent's type per row (a grant reports
    -- against whichever tool it shares). An unrecognized value resolves to NULL
    -- and the row is skipped, so what a subscription may name and what can be
    -- emitted stay the same set.
    IF TG_ARGV[6] <> '' THEN
        EXECUTE 'SELECT ' || TG_ARGV[6] INTO v_type USING v_row;
        IF v_type IS NULL THEN
            RETURN NULL;
        END IF;
    END IF;

    IF TG_OP = 'INSERT' THEN
        v_action := 'created';
    ELSIF TG_OP = 'DELETE' THEN
        -- On a table with the trash lifecycle, deleting is soft: the row moves
        -- to the trash, which is the event a subscriber acts on, and this hard
        -- delete is retention clearing it out afterwards. Never surface that —
        -- it is a repeat of an announced delete, and by now nothing can resolve
        -- the id anyway, not even a read-back asking for trashed rows.
        --
        -- Carrying no deleted_at means the table has no other kind of delete,
        -- so that one IS the event: a junction row going away is how a task
        -- loses a tag.
        --
        -- Tested for through jsonb rather than as OLD.deleted_at, because most
        -- evented tables have no such column and naming one that is absent
        -- raises at runtime.
        IF to_jsonb(OLD) ? 'deleted_at' THEN
            RETURN NULL;
        END IF;
        v_action := 'deleted';
    ELSE
        v_new := to_jsonb(NEW);
        v_old := to_jsonb(OLD);

        -- Coming out of quiet is the row arriving, whatever else moved with it.
        IF v_was_quiet AND NOT v_is_quiet THEN
            v_action := 'created';
        ELSIF NOT v_was_quiet AND v_is_quiet THEN
            v_action := 'deleted';
        -- Soft delete and restore are reported as what they are, so a consumer
        -- never has to know the deleted_at convention to see a row come or go.
        ELSIF v_new ? 'deleted_at'
           AND v_old ->> 'deleted_at' IS NULL
           AND v_new ->> 'deleted_at' IS NOT NULL THEN
            v_action := 'deleted';
        ELSIF v_new ? 'deleted_at'
           AND v_old ->> 'deleted_at' IS NOT NULL
           AND v_new ->> 'deleted_at' IS NULL THEN
            v_action := 'created';
        ELSE
            v_action := 'updated';
            SELECT coalesce(array_agg(key ORDER BY key), '{}')
              INTO v_changed
              FROM jsonb_each(v_new) AS e(key, value)
             WHERE value IS DISTINCT FROM (v_old -> e.key)
               AND NOT (key = ANY (TG_ARGV[4]::text[]));

            -- Nothing a subscriber can act on changed.
            IF cardinality(v_changed) = 0 THEN
                RETURN NULL;
            END IF;
        END IF;
    END IF;

    -- A facet whose label the row decides. Resolved here rather than passed as
    -- a literal, for a table whose rows are facets of different things.
    IF COALESCE(TG_ARGV[10], '') <> '' THEN
        EXECUTE 'SELECT ' || TG_ARGV[10] INTO v_facet USING v_row;
        v_facet := COALESCE(v_facet, '');
    END IF;

    -- A facet has no columns of its own worth naming; report the change as the
    -- owning resource being updated in one respect.
    IF v_facet <> '' THEN
        v_changed := ARRAY[v_facet];
        IF v_action <> 'updated' THEN
            v_action := 'updated';
        END IF;
    END IF;

    -- The addressable resources between this row and its initiative. Resolved
    -- last, so a row that turned out not to be worth reporting never paid for
    -- the lookup, and skipped entirely where the resource has no parents.
    IF TG_ARGV[7] <> '' THEN
        EXECUTE 'SELECT ' || TG_ARGV[7] INTO v_parents USING v_row;
        v_parents := COALESCE(v_parents, '[]'::jsonb);
    END IF;

    IF TG_ARGV[9] <> 'anonymous' THEN
        v_actor := NULLIF(current_setting('app.current_user_id', true), '')::integer;
    END IF;

    -- Write to the outbox of the schema the CHANGED ROW lives in, named from
    -- TG_TABLE_SCHEMA rather than resolved through the caller's search_path.
    -- The row's own schema is the authoritative answer to which guild this
    -- event belongs to, and it is what the trigger is attached to.
    EXECUTE format(
        'INSERT INTO %I.event_outbox ('
        '  txn_id, occurred_at, actor_user_id, initiative_id,'
        '  resource_type, resource_id, action, changed, parents'
        ') VALUES (txid_current(), now(), $1, $2, $3, $4, $5, $6, $7)',
        TG_TABLE_SCHEMA
    ) USING v_actor, v_initiative, v_type, v_resource, v_action, v_changed, v_parents;

    -- Wake whoever is holding sockets for this guild. A hint, not the message:
    -- the row above is the truth, and one that reaches nobody costs a listener
    -- the sweep's latency rather than the update itself. Delivered at COMMIT,
    -- so the rows it points at are visible by the time anyone looks.
    PERFORM pg_notify('event_outbox', TG_TABLE_SCHEMA || ':' || txid_current());

    RETURN NULL;
END
$capture$;
"""

#: ``public.capture_change`` as of this revision.
CAPTURE_AFTER = """
CREATE OR REPLACE FUNCTION public.capture_change() RETURNS trigger
    LANGUAGE plpgsql AS $capture$
DECLARE
    v_row        record;
    v_initiative integer;
    v_action     text;
    v_changed    text[] := '{}';
    v_resource   integer;
    v_type       text := TG_ARGV[1];
    v_actor      integer;
    v_install    integer;
    v_new        jsonb;
    v_old        jsonb;
    v_facet      text := TG_ARGV[3];
    v_parents    jsonb := '[]'::jsonb;
    v_was_quiet  boolean := false;
    v_is_quiet   boolean := false;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_row := OLD;
    ELSE
        v_row := NEW;
    END IF;

    -- Some content exists before it is anybody else's business. While a row is
    -- quiet it says nothing at all, and crossing out of that is what gets
    -- reported — as a create, so a consumer never has to know the convention.
    -- Asked first, so a row nobody is to hear about pays for no lookup either.
    IF TG_ARGV[8] <> '' THEN
        IF TG_OP <> 'INSERT' THEN
            EXECUTE 'SELECT ' || TG_ARGV[8] INTO v_was_quiet USING OLD;
        END IF;
        IF TG_OP <> 'DELETE' THEN
            EXECUTE 'SELECT ' || TG_ARGV[8] INTO v_is_quiet USING NEW;
        END IF;
        IF (TG_OP = 'INSERT' AND v_is_quiet)
           OR (TG_OP = 'DELETE' AND v_was_quiet)
           OR (TG_OP = 'UPDATE' AND v_was_quiet AND v_is_quiet) THEN
            RETURN NULL;
        END IF;
    END IF;

    -- Which initiative this row belongs to, per its registry entry. A NULL is
    -- expected for a guild-wide table and means exactly that; anywhere else it
    -- means the initiative no longer resolves — an orphaned child during a
    -- parent cascade, whose parent emits its own delete — so the row is skipped
    -- rather than broadcast without a scope.
    EXECUTE 'SELECT ' || TG_ARGV[0] INTO v_initiative USING v_row;
    IF v_initiative IS NULL AND TG_ARGV[5] <> 'guild' THEN
        RETURN NULL;
    END IF;

    EXECUTE 'SELECT ' || TG_ARGV[2] INTO v_resource USING v_row;
    IF v_resource IS NULL THEN
        RETURN NULL;
    END IF;

    -- A polymorphic facet names its parent's type per row (a grant reports
    -- against whichever tool it shares). An unrecognized value resolves to NULL
    -- and the row is skipped, so what a subscription may name and what can be
    -- emitted stay the same set.
    IF TG_ARGV[6] <> '' THEN
        EXECUTE 'SELECT ' || TG_ARGV[6] INTO v_type USING v_row;
        IF v_type IS NULL THEN
            RETURN NULL;
        END IF;
    END IF;

    IF TG_OP = 'INSERT' THEN
        v_action := 'created';
    ELSIF TG_OP = 'DELETE' THEN
        -- On a table with the trash lifecycle, deleting is soft: the row moves
        -- to the trash, which is the event a subscriber acts on, and this hard
        -- delete is retention clearing it out afterwards. Never surface that —
        -- it is a repeat of an announced delete, and by now nothing can resolve
        -- the id anyway, not even a read-back asking for trashed rows.
        --
        -- Carrying no deleted_at means the table has no other kind of delete,
        -- so that one IS the event: a junction row going away is how a task
        -- loses a tag.
        --
        -- Tested for through jsonb rather than as OLD.deleted_at, because most
        -- evented tables have no such column and naming one that is absent
        -- raises at runtime.
        IF to_jsonb(OLD) ? 'deleted_at' THEN
            RETURN NULL;
        END IF;
        v_action := 'deleted';
    ELSE
        v_new := to_jsonb(NEW);
        v_old := to_jsonb(OLD);

        -- Coming out of quiet is the row arriving, whatever else moved with it.
        IF v_was_quiet AND NOT v_is_quiet THEN
            v_action := 'created';
        ELSIF NOT v_was_quiet AND v_is_quiet THEN
            v_action := 'deleted';
        -- Soft delete and restore are reported as what they are, so a consumer
        -- never has to know the deleted_at convention to see a row come or go.
        ELSIF v_new ? 'deleted_at'
           AND v_old ->> 'deleted_at' IS NULL
           AND v_new ->> 'deleted_at' IS NOT NULL THEN
            v_action := 'deleted';
        ELSIF v_new ? 'deleted_at'
           AND v_old ->> 'deleted_at' IS NOT NULL
           AND v_new ->> 'deleted_at' IS NULL THEN
            v_action := 'created';
        ELSE
            v_action := 'updated';
            SELECT coalesce(array_agg(key ORDER BY key), '{}')
              INTO v_changed
              FROM jsonb_each(v_new) AS e(key, value)
             WHERE value IS DISTINCT FROM (v_old -> e.key)
               AND NOT (key = ANY (TG_ARGV[4]::text[]));

            -- Nothing a subscriber can act on changed.
            IF cardinality(v_changed) = 0 THEN
                RETURN NULL;
            END IF;
        END IF;
    END IF;

    -- A facet whose label the row decides. Resolved here rather than passed as
    -- a literal, for a table whose rows are facets of different things.
    IF COALESCE(TG_ARGV[10], '') <> '' THEN
        EXECUTE 'SELECT ' || TG_ARGV[10] INTO v_facet USING v_row;
        v_facet := COALESCE(v_facet, '');
    END IF;

    -- A facet has no columns of its own worth naming; report the change as the
    -- owning resource being updated in one respect.
    IF v_facet <> '' THEN
        v_changed := ARRAY[v_facet];
        IF v_action <> 'updated' THEN
            v_action := 'updated';
        END IF;
    END IF;

    -- The addressable resources between this row and its initiative. Resolved
    -- last, so a row that turned out not to be worth reporting never paid for
    -- the lookup, and skipped entirely where the resource has no parents.
    IF TG_ARGV[7] <> '' THEN
        EXECUTE 'SELECT ' || TG_ARGV[7] INTO v_parents USING v_row;
        v_parents := COALESCE(v_parents, '[]'::jsonb);
    END IF;

    -- Who wrote it: the person, the installed app, or both when an app acts
    -- for a member. Each is read on its own from the request context, and an
    -- anonymous table names neither.
    IF TG_ARGV[9] <> 'anonymous' THEN
        v_actor := NULLIF(current_setting('app.current_user_id', true), '')::integer;
        v_install := NULLIF(current_setting('app.current_install_id', true), '')::integer;
    END IF;

    -- Write to the outbox of the schema the CHANGED ROW lives in, named from
    -- TG_TABLE_SCHEMA rather than resolved through the caller's search_path.
    -- The row's own schema is the authoritative answer to which guild this
    -- event belongs to, and it is what the trigger is attached to.
    EXECUTE format(
        'INSERT INTO %I.event_outbox ('
        '  txn_id, occurred_at, actor_user_id, actor_install_id, initiative_id,'
        '  resource_type, resource_id, action, changed, parents'
        ') VALUES (txid_current(), now(), $1, $2, $3, $4, $5, $6, $7, $8)',
        TG_TABLE_SCHEMA
    ) USING v_actor, v_install, v_initiative, v_type, v_resource, v_action,
            v_changed, v_parents;

    -- Wake whoever is holding sockets for this guild. A hint, not the message:
    -- the row above is the truth, and one that reaches nobody costs a listener
    -- the sweep's latency rather than the update itself. Delivered at COMMIT,
    -- so the rows it points at are visible by the time anyone looks.
    PERFORM pg_notify('event_outbox', TG_TABLE_SCHEMA || ':' || txid_current());

    RETURN NULL;
END
$capture$;
"""


def _replace_capture(body: str) -> None:
    # The body names guild-local tables that no schema on the migration-time
    # search_path holds; resolution is per call, through the routed search_path.
    op.execute("SET LOCAL check_function_bodies = false")
    op.execute(body)


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _add_column)
    _replace_capture(CAPTURE_AFTER)


def _add_column() -> None:
    with op.batch_alter_table("event_outbox", schema=None) as batch_op:
        batch_op.add_column(sa.Column("actor_install_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    _replace_capture(CAPTURE_BEFORE)
    run_for_each_guild_schema(op.get_bind(), _drop_column)


def _drop_column() -> None:
    with op.batch_alter_table("event_outbox", schema=None) as batch_op:
        batch_op.drop_column("actor_install_id")
