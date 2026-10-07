"""The owner row names the plug-in

``20261005_0457`` renamed ``resource_grants.app_install_id`` to
``plugin_install_id`` but left ``public.fn_install_owns_what_it_creates``
writing the old column, so a plug-in creating a tool's resource failed. This
restates the function with the column's new name; the body is
``app.db.plugin_rls.INSTALL_OWNS_WHAT_IT_CREATES`` as it stands at this
revision, and the downgrade puts back the one ``20260927_0407`` set.

Revision ID: 20261005_0458
Revises: 20261005_0457
Create Date: 2026-10-05
"""

from alembic import op

revision = "20261005_0458"
down_revision = "20261005_0457"
branch_labels = None
depends_on = None

OWNS_FUNCTION_BEFORE = """
CREATE OR REPLACE FUNCTION public.fn_install_owns_what_it_creates() RETURNS trigger
    LANGUAGE plpgsql AS $owns$
DECLARE
    v_install integer := NULLIF(current_setting('app.current_install_id'::text, true), ''::text)::integer;
    v_member integer := NULLIF(current_setting('app.current_user_id'::text, true), ''::text)::integer;
BEGIN
    IF NEW.initiative_id IS NULL OR (v_install IS NULL AND v_member IS NULL) THEN
        RETURN NULL;
    END IF;
    IF v_member IS NULL THEN
        EXECUTE format(
            'INSERT INTO %I.resource_grants '
            '(resource_type, resource_id, initiative_id, app_install_id, level, '
            'all_initiative_members, created_at) '
            'VALUES ($1, $2, $3, $4, ''owner'', false, now())',
            TG_TABLE_SCHEMA
        ) USING TG_ARGV[0], NEW.id, NEW.initiative_id, v_install;
    ELSE
        EXECUTE format(
            'INSERT INTO %I.resource_grants '
            '(resource_type, resource_id, initiative_id, user_id, level, '
            'all_initiative_members, created_at) '
            'VALUES ($1, $2, $3, $4, ''owner'', false, now())',
            TG_TABLE_SCHEMA
        ) USING TG_ARGV[0], NEW.id, NEW.initiative_id, v_member;
    END IF;
    RETURN NULL;
END;
$owns$;
"""

OWNS_FUNCTION_AFTER = """
CREATE OR REPLACE FUNCTION public.fn_install_owns_what_it_creates() RETURNS trigger
    LANGUAGE plpgsql AS $owns$
DECLARE
    v_install integer := NULLIF(current_setting('app.current_install_id'::text, true), ''::text)::integer;
    v_member integer := NULLIF(current_setting('app.current_user_id'::text, true), ''::text)::integer;
BEGIN
    IF NEW.initiative_id IS NULL OR (v_install IS NULL AND v_member IS NULL) THEN
        RETURN NULL;
    END IF;
    IF v_member IS NULL THEN
        EXECUTE format(
            'INSERT INTO %I.resource_grants '
            '(resource_type, resource_id, initiative_id, plugin_install_id, level, '
            'all_initiative_members, created_at) '
            'VALUES ($1, $2, $3, $4, ''owner'', false, now())',
            TG_TABLE_SCHEMA
        ) USING TG_ARGV[0], NEW.id, NEW.initiative_id, v_install;
    ELSE
        EXECUTE format(
            'INSERT INTO %I.resource_grants '
            '(resource_type, resource_id, initiative_id, user_id, level, '
            'all_initiative_members, created_at) '
            'VALUES ($1, $2, $3, $4, ''owner'', false, now())',
            TG_TABLE_SCHEMA
        ) USING TG_ARGV[0], NEW.id, NEW.initiative_id, v_member;
    END IF;
    RETURN NULL;
END;
$owns$;
"""


def upgrade() -> None:
    op.execute(OWNS_FUNCTION_AFTER)


def downgrade() -> None:
    op.execute(OWNS_FUNCTION_BEFORE)
