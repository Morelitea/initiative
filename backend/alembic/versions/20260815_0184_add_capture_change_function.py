"""Add public.capture_change(), the one change-capture trigger function

Created once in ``public`` and shared by every guild schema, exactly like
``public.initiative_access``. The body names content tables unqualified, so they
resolve through the caller's ``search_path`` — the routed ``guild_<id>`` — and
one function serves every guild rather than one per schema.

Per-table knowledge arrives as trigger arguments rendered from the registries
that already describe these tables (``app/db/event_capture.py``): how a row
resolves its initiative, which resource an event names, and which columns are
excluded from the reported change set. The triggers themselves are installed per
schema at provisioning time, not here.

The function writes identifiers, an action, and changed column NAMES. It never
writes a value: a consumer reads current state back through the REST API.

Revision ID: 20260815_0184
Revises: 20260815_0183
Create Date: 2026-08-15
"""

from __future__ import annotations

from alembic import op

revision = "20260815_0184"
down_revision = "20260815_0183"
branch_labels = None
depends_on = None


#: Spelled out as a literal, not imported from ``app.db.event_capture``:
#: a revision has to keep doing to a database exactly what it did when it
#: was written, and a registry that changes later would reach back and
#: change that. Provisioning re-renders the CURRENT definition on every
#: boot, so a later edit reaches existing guilds that way instead.
CAPTURE_FUNCTION = "public.capture_change"

CAPTURE_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION public.capture_change() RETURNS trigger
    LANGUAGE plpgsql AS $capture$
DECLARE
    v_row        record;
    v_initiative integer;
    v_action     text;
    v_changed    text[] := '{}';
    v_resource   integer;
    v_actor      integer;
    v_new        jsonb;
    v_old        jsonb;
    v_facet      text := TG_ARGV[3];
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_row := OLD;
    ELSE
        v_row := NEW;
    END IF;

    -- Which initiative this row belongs to, per its INITIATIVE_PATHS entry.
    -- A row whose initiative no longer resolves is skipped: that is an orphaned
    -- child during a parent cascade, and the parent emits its own delete.
    EXECUTE 'SELECT ' || TG_ARGV[0] INTO v_initiative USING v_row;
    IF v_initiative IS NULL THEN
        RETURN NULL;
    END IF;

    EXECUTE format('SELECT ($1).%I', TG_ARGV[2]) INTO v_resource USING v_row;
    IF v_resource IS NULL THEN
        RETURN NULL;
    END IF;

    IF TG_OP = 'INSERT' THEN
        v_action := 'created';
    ELSIF TG_OP = 'DELETE' THEN
        v_action := 'deleted';
    ELSE
        v_new := to_jsonb(NEW);
        v_old := to_jsonb(OLD);

        -- Soft delete and restore are reported as what they are, so a consumer
        -- never has to know the deleted_at convention to see a row come or go.
        IF v_new ? 'deleted_at'
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

    -- A junction has no columns of its own worth naming; report the change as
    -- the owning resource being updated in one respect.
    IF v_facet <> '' THEN
        v_changed := ARRAY[v_facet];
        IF v_action <> 'updated' THEN
            v_action := 'updated';
        END IF;
    END IF;

    v_actor := NULLIF(current_setting('app.current_user_id', true), '')::integer;

    -- Write to the outbox of the schema the CHANGED ROW lives in, named from
    -- TG_TABLE_SCHEMA rather than resolved through the caller's search_path.
    -- The row's own schema is the authoritative answer to which guild this
    -- event belongs to, and it is what the trigger is attached to.
    EXECUTE format(
        'INSERT INTO %I.event_outbox ('
        '  txn_id, occurred_at, actor_user_id, initiative_id,'
        '  resource_type, resource_id, action, changed'
        ') VALUES (txid_current(), now(), $1, $2, $3, $4, $5, $6)',
        TG_TABLE_SCHEMA
    ) USING v_actor, v_initiative, TG_ARGV[1], v_resource, v_action, v_changed;

    RETURN NULL;
END
$capture$;
"""


def upgrade() -> None:
    # The body names guild-local tables that no schema on the migration-time
    # search_path holds; resolution is per call, through the routed search_path.
    op.execute("SET LOCAL check_function_bodies = false")
    op.execute(CAPTURE_FUNCTION_SQL)


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {CAPTURE_FUNCTION}()")
