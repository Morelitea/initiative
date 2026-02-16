"""Baseline migration: v0.30.0 schema snapshot replacing 76 incremental migrations

Revision ID: 20260216_0053
Revises: (none -- this is the new root)
Create Date: 2026-02-16

For existing v0.30.0 databases the alembic_version row already reads
'20260216_0053', so upgrade() is a complete no-op.  For fresh databases
the function creates every table, sequence, enum, function, index,
trigger, constraint, RLS policy, and role from scratch.
"""

import os
from urllib.parse import urlparse

from alembic import op
from sqlalchemy import text

revision = "20260216_0053"
down_revision = None
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Helper utilities (reused from the former 20260207_0040 role migration)
# ---------------------------------------------------------------------------

def _role_exists(connection, rolname: str) -> bool:
    result = connection.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = :name"),
        {"name": rolname},
    )
    return result.fetchone() is not None


def _password_from_url(env_var: str) -> str | None:
    """Extract the password component from a DATABASE_URL env var.

    Checks os.environ first (Docker / exported vars), then falls back
    to the pydantic settings object which reads from .env files.
    """
    url = os.environ.get(env_var)
    if not url:
        try:
            from app.core.config import settings  # noqa: E402
            url = getattr(settings, env_var, None)
        except Exception:
            pass
    if not url:
        return None
    try:
        parsed = urlparse(url)
        return parsed.password
    except Exception:
        return None


def _exec_role_ddl(connection, ddl_template: str, password: str | None) -> None:
    """Execute a role DDL statement with an optional password.

    PostgreSQL DDL (CREATE/ALTER ROLE) doesn't support bind parameters,
    so we pass the password through set_config() and use format('%L')
    for safe literal quoting inside a DO block.
    """
    if password is not None:
        connection.execute(
            text("SELECT set_config('app._migration_pw', :pw, true)"),
            {"pw": password},
        )
        connection.execute(text(
            "DO $$ BEGIN "
            f"EXECUTE format('{ddl_template} PASSWORD %L', "
            "current_setting('app._migration_pw')); "
            "END $$"
        ))
        # Clear the temporary variable
        connection.execute(
            text("SELECT set_config('app._migration_pw', '', true)")
        )
    else:
        connection.execute(text(ddl_template))


def _table_exists(connection, table_name: str) -> bool:
    """Check whether a table already exists in the public schema."""
    result = connection.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :t"
        ),
        {"t": table_name},
    )
    return result.fetchone() is not None


# ---------------------------------------------------------------------------
# 1. Roles
# ---------------------------------------------------------------------------

def _create_roles(connection) -> None:
    """Create app_user and app_admin database roles."""

    # --- app_user: non-superuser for RLS-enforced queries ---
    app_user_pw = _password_from_url("DATABASE_URL_APP")

    if not _role_exists(connection, "app_user"):
        if app_user_pw:
            _exec_role_ddl(
                connection,
                "CREATE ROLE app_user WITH LOGIN NOINHERIT",
                app_user_pw,
            )
        else:
            print(
                "NOTE: app_user role does not exist and DATABASE_URL_APP is not set.\n"
                "RLS enforcement requires this role. Create it with:\n"
                "  CREATE ROLE app_user WITH LOGIN NOINHERIT PASSWORD 'your_password';\n"
                "The baseline migration handles this when DATABASE_URL_APP is set."
            )
    else:
        # Ensure correct attributes and sync password from env
        _exec_role_ddl(
            connection,
            "ALTER ROLE app_user WITH LOGIN NOINHERIT",
            app_user_pw,
        )

    # --- app_admin: BYPASSRLS for migrations and background jobs ---
    app_admin_pw = _password_from_url("DATABASE_URL_ADMIN")

    if not _role_exists(connection, "app_admin"):
        if app_admin_pw:
            _exec_role_ddl(
                connection,
                "CREATE ROLE app_admin WITH LOGIN BYPASSRLS",
                app_admin_pw,
            )
        else:
            print(
                "NOTE: app_admin role does not exist and DATABASE_URL_ADMIN is not set.\n"
                "Create it with:\n"
                "  CREATE ROLE app_admin WITH LOGIN BYPASSRLS PASSWORD 'your_password';\n"
                "The baseline migration handles this when DATABASE_URL_ADMIN is set."
            )
    else:
        _exec_role_ddl(
            connection,
            "ALTER ROLE app_admin WITH LOGIN BYPASSRLS",
            app_admin_pw,
        )


# ---------------------------------------------------------------------------
# 2. Schema: enums, functions, tables, sequences, defaults, constraints,
#    indexes, triggers, foreign keys, ENABLE/FORCE RLS
# ---------------------------------------------------------------------------

def _create_schema(connection) -> None:
    """Create all database objects (idempotent)."""

    # ===================================================================
    # ENUM TYPES
    # ===================================================================
    connection.execute(text("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'document_permission_level') THEN
            CREATE TYPE document_permission_level AS ENUM ('read', 'write', 'owner');
        END IF;
    END $$
    """))
    connection.execute(text("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'document_type') THEN
            CREATE TYPE document_type AS ENUM ('native', 'file');
        END IF;
    END $$
    """))
    connection.execute(text("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'guild_role') THEN
            CREATE TYPE guild_role AS ENUM ('admin', 'member');
        END IF;
    END $$
    """))
    connection.execute(text("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'project_permission_level') THEN
            CREATE TYPE project_permission_level AS ENUM ('owner', 'write', 'read');
        END IF;
    END $$
    """))
    connection.execute(text("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'task_priority') THEN
            CREATE TYPE task_priority AS ENUM ('low', 'medium', 'high', 'urgent');
        END IF;
    END $$
    """))
    connection.execute(text("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'task_status_category') THEN
            CREATE TYPE task_status_category AS ENUM ('backlog', 'todo', 'in_progress', 'done');
        END IF;
    END $$
    """))
    connection.execute(text("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_role') THEN
            CREATE TYPE user_role AS ENUM ('admin', 'member');
        END IF;
    END $$
    """))
    connection.execute(text("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_token_purpose') THEN
            CREATE TYPE user_token_purpose AS ENUM ('email_verification', 'password_reset', 'device_auth');
        END IF;
    END $$
    """))

    # ===================================================================
    # FUNCTIONS
    # ===================================================================
    connection.execute(text("""
    CREATE OR REPLACE FUNCTION fn_comments_set_guild_id() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR
               (TG_OP = 'UPDATE' AND (OLD.task_id IS DISTINCT FROM NEW.task_id OR OLD.document_id IS DISTINCT FROM NEW.document_id)) THEN
                IF NEW.task_id IS NOT NULL THEN
                    SELECT guild_id INTO NEW.guild_id FROM tasks WHERE id = NEW.task_id;
                ELSIF NEW.document_id IS NOT NULL THEN
                    SELECT guild_id INTO NEW.guild_id FROM documents WHERE id = NEW.document_id;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
    """))

    connection.execute(text("""
    CREATE OR REPLACE FUNCTION fn_document_permissions_set_guild_id() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.document_id IS DISTINCT FROM NEW.document_id) THEN
                SELECT guild_id INTO NEW.guild_id FROM documents WHERE id = NEW.document_id;
            END IF;
            RETURN NEW;
        END;
        $$
    """))

    connection.execute(text("""
    CREATE OR REPLACE FUNCTION fn_documents_set_guild_id() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.initiative_id IS DISTINCT FROM NEW.initiative_id) THEN
                SELECT guild_id INTO NEW.guild_id FROM initiatives WHERE id = NEW.initiative_id;
            END IF;
            RETURN NEW;
        END;
        $$
    """))

    connection.execute(text("""
    CREATE OR REPLACE FUNCTION fn_initiative_members_set_guild_id() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.initiative_id IS DISTINCT FROM NEW.initiative_id) THEN
                SELECT guild_id INTO NEW.guild_id FROM initiatives WHERE id = NEW.initiative_id;
            END IF;
            RETURN NEW;
        END;
        $$
    """))

    connection.execute(text("""
    CREATE OR REPLACE FUNCTION fn_project_documents_set_guild_id() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.project_id IS DISTINCT FROM NEW.project_id) THEN
                SELECT guild_id INTO NEW.guild_id FROM projects WHERE id = NEW.project_id;
            END IF;
            RETURN NEW;
        END;
        $$
    """))

    connection.execute(text("""
    CREATE OR REPLACE FUNCTION fn_project_favorites_set_guild_id() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.project_id IS DISTINCT FROM NEW.project_id) THEN
                SELECT guild_id INTO NEW.guild_id FROM projects WHERE id = NEW.project_id;
            END IF;
            RETURN NEW;
        END;
        $$
    """))

    connection.execute(text("""
    CREATE OR REPLACE FUNCTION fn_project_orders_set_guild_id() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.project_id IS DISTINCT FROM NEW.project_id) THEN
                SELECT guild_id INTO NEW.guild_id FROM projects WHERE id = NEW.project_id;
            END IF;
            RETURN NEW;
        END;
        $$
    """))

    connection.execute(text("""
    CREATE OR REPLACE FUNCTION fn_project_permissions_set_guild_id() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.project_id IS DISTINCT FROM NEW.project_id) THEN
                SELECT guild_id INTO NEW.guild_id FROM projects WHERE id = NEW.project_id;
            END IF;
            RETURN NEW;
        END;
        $$
    """))

    connection.execute(text("""
    CREATE OR REPLACE FUNCTION fn_projects_set_guild_id() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.initiative_id IS DISTINCT FROM NEW.initiative_id) THEN
                SELECT guild_id INTO NEW.guild_id FROM initiatives WHERE id = NEW.initiative_id;
            END IF;
            RETURN NEW;
        END;
        $$
    """))

    connection.execute(text("""
    CREATE OR REPLACE FUNCTION fn_recent_project_views_set_guild_id() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.project_id IS DISTINCT FROM NEW.project_id) THEN
                SELECT guild_id INTO NEW.guild_id FROM projects WHERE id = NEW.project_id;
            END IF;
            RETURN NEW;
        END;
        $$
    """))

    connection.execute(text("""
    CREATE OR REPLACE FUNCTION fn_subtasks_set_guild_id() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.task_id IS DISTINCT FROM NEW.task_id) THEN
                SELECT guild_id INTO NEW.guild_id FROM tasks WHERE id = NEW.task_id;
            END IF;
            RETURN NEW;
        END;
        $$
    """))

    connection.execute(text("""
    CREATE OR REPLACE FUNCTION fn_task_assignees_set_guild_id() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.task_id IS DISTINCT FROM NEW.task_id) THEN
                SELECT guild_id INTO NEW.guild_id FROM tasks WHERE id = NEW.task_id;
            END IF;
            RETURN NEW;
        END;
        $$
    """))

    connection.execute(text("""
    CREATE OR REPLACE FUNCTION fn_task_statuses_set_guild_id() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.project_id IS DISTINCT FROM NEW.project_id) THEN
                SELECT guild_id INTO NEW.guild_id FROM projects WHERE id = NEW.project_id;
            END IF;
            RETURN NEW;
        END;
        $$
    """))

    connection.execute(text("""
    CREATE OR REPLACE FUNCTION fn_tasks_set_guild_id() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.project_id IS DISTINCT FROM NEW.project_id) THEN
                SELECT guild_id INTO NEW.guild_id FROM projects WHERE id = NEW.project_id;
            END IF;
            RETURN NEW;
        END;
        $$
    """))

    # NOTE: is_initiative_member() is created after tables exist (see upgrade()).

    # ===================================================================
    # TABLES (order matters for FK references)
    # ===================================================================

    # -- users (no FK deps)
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS users (
        id integer NOT NULL,
        email character varying NOT NULL,
        full_name character varying,
        hashed_password character varying NOT NULL,
        role user_role DEFAULT 'member'::user_role NOT NULL,
        is_active boolean NOT NULL,
        created_at timestamp with time zone NOT NULL,
        updated_at timestamp with time zone NOT NULL,
        avatar_base64 text,
        avatar_url character varying(2048),
        email_verified boolean DEFAULT true NOT NULL,
        timezone character varying(64) DEFAULT 'UTC'::character varying NOT NULL,
        overdue_notification_time character varying(5) DEFAULT '21:00'::character varying NOT NULL,
        email_initiative_addition boolean DEFAULT true NOT NULL,
        email_task_assignment boolean DEFAULT true NOT NULL,
        email_project_added boolean DEFAULT true NOT NULL,
        email_overdue_tasks boolean DEFAULT true NOT NULL,
        last_overdue_notification_at timestamp with time zone,
        last_task_assignment_digest_at timestamp with time zone,
        week_starts_on integer DEFAULT 0 NOT NULL,
        email_mentions boolean DEFAULT true NOT NULL,
        ai_enabled boolean,
        ai_provider character varying(50),
        ai_api_key character varying(2000),
        ai_base_url character varying(1000),
        ai_model character varying(500),
        color_theme character varying(50) DEFAULT 'kobold'::character varying NOT NULL,
        push_initiative_addition boolean DEFAULT true NOT NULL,
        push_task_assignment boolean DEFAULT true NOT NULL,
        push_project_added boolean DEFAULT true NOT NULL,
        push_overdue_tasks boolean DEFAULT true NOT NULL,
        push_mentions boolean DEFAULT true NOT NULL,
        oidc_refresh_token_encrypted text,
        oidc_last_synced_at timestamp with time zone,
        oidc_sub character varying(255),
        locale character varying(10) DEFAULT 'en'::character varying NOT NULL
    )
    """))

    # -- guilds (FK to users)
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS guilds (
        id integer NOT NULL,
        name character varying NOT NULL,
        description text,
        icon_base64 text,
        created_by_user_id integer,
        created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
        updated_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL
    )
    """))

    # -- guild_memberships
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS guild_memberships (
        guild_id integer NOT NULL,
        user_id integer NOT NULL,
        role guild_role DEFAULT 'member'::guild_role NOT NULL,
        joined_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
        "position" integer DEFAULT 0 NOT NULL,
        oidc_managed boolean DEFAULT false NOT NULL
    )
    """))

    # -- guild_invites
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS guild_invites (
        id integer NOT NULL,
        code character varying(64) NOT NULL,
        guild_id integer NOT NULL,
        created_by_user_id integer,
        expires_at timestamp with time zone,
        max_uses integer,
        uses integer DEFAULT 0 NOT NULL,
        invitee_email character varying,
        created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL
    )
    """))

    # -- guild_settings
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS guild_settings (
        id integer NOT NULL,
        guild_id integer NOT NULL,
        created_at timestamp with time zone NOT NULL,
        updated_at timestamp with time zone NOT NULL,
        ai_enabled boolean,
        ai_provider character varying(50),
        ai_api_key character varying(2000),
        ai_base_url character varying(1000),
        ai_model character varying(500),
        ai_allow_user_override boolean
    )
    """))

    # -- app_settings
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS app_settings (
        id integer NOT NULL,
        oidc_enabled boolean DEFAULT false NOT NULL,
        oidc_issuer character varying,
        oidc_client_id character varying,
        oidc_client_secret character varying,
        oidc_provider_name character varying,
        oidc_scopes json DEFAULT '["openid", "profile", "email"]'::jsonb NOT NULL,
        light_accent_color character varying(20) DEFAULT '#2563eb'::character varying NOT NULL,
        dark_accent_color character varying(20) DEFAULT '#60a5fa'::character varying NOT NULL,
        role_labels json DEFAULT '{"admin": "Admin", "member": "Member", "project_manager": "Project manager"}'::jsonb NOT NULL,
        smtp_host character varying(255),
        smtp_port integer,
        smtp_secure boolean DEFAULT false NOT NULL,
        smtp_reject_unauthorized boolean DEFAULT true NOT NULL,
        smtp_username character varying(255),
        smtp_password character varying(255),
        smtp_from_address character varying(255),
        smtp_test_recipient character varying(255),
        ai_enabled boolean DEFAULT false NOT NULL,
        ai_provider character varying(50),
        ai_api_key character varying(2000),
        ai_base_url character varying(1000),
        ai_model character varying(500),
        ai_allow_guild_override boolean DEFAULT true NOT NULL,
        ai_allow_user_override boolean DEFAULT true NOT NULL,
        oidc_role_claim_path character varying(500)
    )
    """))

    # -- initiatives (formerly teams)
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS initiatives (
        id integer NOT NULL,
        name character varying NOT NULL,
        description character varying,
        created_at timestamp with time zone NOT NULL,
        updated_at timestamp with time zone NOT NULL,
        color character varying(32),
        is_default boolean NOT NULL,
        guild_id integer NOT NULL
    )
    """))

    # -- initiative_roles
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS initiative_roles (
        id integer NOT NULL,
        initiative_id integer NOT NULL,
        name character varying(100) NOT NULL,
        display_name character varying(100) NOT NULL,
        is_builtin boolean DEFAULT false NOT NULL,
        is_manager boolean DEFAULT false NOT NULL,
        "position" integer DEFAULT 0 NOT NULL
    )
    """))

    # -- initiative_role_permissions
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS initiative_role_permissions (
        initiative_role_id integer NOT NULL,
        permission_key character varying(50) NOT NULL,
        enabled boolean DEFAULT true NOT NULL
    )
    """))

    # -- initiative_members
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS initiative_members (
        initiative_id integer NOT NULL,
        user_id integer NOT NULL,
        joined_at timestamp with time zone NOT NULL,
        guild_id integer NOT NULL,
        role_id integer,
        oidc_managed boolean DEFAULT false NOT NULL
    )
    """))

    # -- oidc_claim_mappings
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS oidc_claim_mappings (
        id integer NOT NULL,
        claim_value character varying(500) NOT NULL,
        target_type character varying(20) NOT NULL,
        guild_id integer NOT NULL,
        guild_role character varying(20) DEFAULT 'member'::character varying NOT NULL,
        initiative_id integer,
        initiative_role_id integer,
        created_at timestamp with time zone DEFAULT now() NOT NULL,
        updated_at timestamp with time zone DEFAULT now() NOT NULL
    )
    """))

    # -- projects
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS projects (
        id integer NOT NULL,
        name character varying NOT NULL,
        icon character varying(8),
        description text,
        owner_id integer NOT NULL,
        initiative_id integer NOT NULL,
        created_at timestamp with time zone NOT NULL,
        updated_at timestamp with time zone NOT NULL,
        is_archived boolean NOT NULL,
        is_template boolean NOT NULL,
        archived_at timestamp with time zone,
        pinned_at timestamp with time zone,
        guild_id integer NOT NULL
    )
    """))

    # -- project_permissions
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS project_permissions (
        project_id integer NOT NULL,
        user_id integer NOT NULL,
        created_at timestamp with time zone NOT NULL,
        level project_permission_level NOT NULL,
        guild_id integer NOT NULL
    )
    """))

    # -- project_role_permissions
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS project_role_permissions (
        project_id integer NOT NULL,
        initiative_role_id integer NOT NULL,
        guild_id integer NOT NULL,
        level project_permission_level DEFAULT 'read'::project_permission_level NOT NULL,
        created_at timestamp with time zone DEFAULT now() NOT NULL
    )
    """))

    # -- project_favorites
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS project_favorites (
        user_id integer NOT NULL,
        project_id integer NOT NULL,
        created_at timestamp with time zone NOT NULL,
        guild_id integer NOT NULL
    )
    """))

    # -- project_orders
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS project_orders (
        user_id integer NOT NULL,
        project_id integer NOT NULL,
        sort_order double precision DEFAULT '0'::double precision NOT NULL,
        guild_id integer NOT NULL
    )
    """))

    # -- recent_project_views
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS recent_project_views (
        user_id integer NOT NULL,
        project_id integer NOT NULL,
        last_viewed_at timestamp with time zone NOT NULL,
        guild_id integer NOT NULL
    )
    """))

    # -- tags
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS tags (
        id integer NOT NULL,
        guild_id integer NOT NULL,
        name character varying(100) NOT NULL,
        color character varying(7) DEFAULT '''#6366F1'''::character varying NOT NULL,
        created_at timestamp with time zone NOT NULL,
        updated_at timestamp with time zone NOT NULL
    )
    """))

    # -- task_statuses
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS task_statuses (
        id integer NOT NULL,
        project_id integer NOT NULL,
        name character varying(100) NOT NULL,
        "position" integer DEFAULT 0 NOT NULL,
        category task_status_category NOT NULL,
        is_default boolean DEFAULT false NOT NULL,
        guild_id integer NOT NULL
    )
    """))

    # -- tasks
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS tasks (
        id integer NOT NULL,
        project_id integer NOT NULL,
        title character varying NOT NULL,
        description text,
        priority task_priority NOT NULL,
        due_date timestamp with time zone,
        sort_order double precision DEFAULT '0'::double precision NOT NULL,
        created_at timestamp with time zone NOT NULL,
        updated_at timestamp with time zone NOT NULL,
        recurrence json,
        recurrence_occurrence_count integer NOT NULL,
        start_date timestamp with time zone,
        task_status_id integer NOT NULL,
        recurrence_strategy character varying(20) NOT NULL,
        is_archived boolean DEFAULT false NOT NULL,
        guild_id integer NOT NULL
    )
    """))

    # -- task_assignees
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS task_assignees (
        task_id integer NOT NULL,
        user_id integer NOT NULL,
        guild_id integer NOT NULL
    )
    """))

    # -- task_tags
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS task_tags (
        task_id integer NOT NULL,
        tag_id integer NOT NULL,
        created_at timestamp with time zone NOT NULL
    )
    """))

    # -- project_tags
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS project_tags (
        project_id integer NOT NULL,
        tag_id integer NOT NULL,
        created_at timestamp with time zone NOT NULL
    )
    """))

    # -- subtasks
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS subtasks (
        id integer NOT NULL,
        task_id integer NOT NULL,
        content text NOT NULL,
        is_completed boolean DEFAULT false NOT NULL,
        "position" integer DEFAULT 0 NOT NULL,
        created_at timestamp with time zone NOT NULL,
        updated_at timestamp with time zone NOT NULL,
        guild_id integer NOT NULL
    )
    """))

    # -- documents
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS documents (
        id integer NOT NULL,
        initiative_id integer NOT NULL,
        title character varying(255) NOT NULL,
        content jsonb DEFAULT '{}'::jsonb NOT NULL,
        created_by_id integer NOT NULL,
        updated_by_id integer NOT NULL,
        created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
        updated_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
        featured_image_url character varying(512),
        is_template boolean NOT NULL,
        yjs_state bytea,
        yjs_updated_at timestamp with time zone,
        guild_id integer NOT NULL,
        document_type document_type DEFAULT 'native'::document_type NOT NULL,
        file_url character varying(512),
        file_content_type character varying(128),
        file_size bigint,
        original_filename character varying(255)
    )
    """))

    # -- document_permissions
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS document_permissions (
        document_id integer NOT NULL,
        user_id integer NOT NULL,
        level document_permission_level NOT NULL,
        created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
        guild_id integer NOT NULL
    )
    """))

    # -- document_role_permissions
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS document_role_permissions (
        document_id integer NOT NULL,
        initiative_role_id integer NOT NULL,
        guild_id integer NOT NULL,
        level document_permission_level DEFAULT 'read'::document_permission_level NOT NULL,
        created_at timestamp with time zone DEFAULT now() NOT NULL
    )
    """))

    # -- document_links
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS document_links (
        source_document_id integer NOT NULL,
        target_document_id integer NOT NULL,
        guild_id integer,
        created_at timestamp with time zone NOT NULL
    )
    """))

    # -- document_tags
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS document_tags (
        document_id integer NOT NULL,
        tag_id integer NOT NULL,
        created_at timestamp with time zone NOT NULL
    )
    """))

    # -- project_documents
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS project_documents (
        project_id integer NOT NULL,
        document_id integer NOT NULL,
        attached_by_id integer,
        attached_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
        guild_id integer NOT NULL
    )
    """))

    # -- comments
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS comments (
        id integer NOT NULL,
        content text NOT NULL,
        author_id integer NOT NULL,
        task_id integer,
        document_id integer,
        parent_comment_id integer,
        created_at timestamp with time zone NOT NULL,
        guild_id integer,
        updated_at timestamp with time zone,
        CONSTRAINT ck_comments_task_or_document CHECK (((task_id IS NULL) <> (document_id IS NULL)))
    )
    """))

    # -- notifications
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS notifications (
        id integer NOT NULL,
        user_id integer NOT NULL,
        type character varying(64) NOT NULL,
        data json DEFAULT '{}'::json NOT NULL,
        read_at timestamp with time zone,
        created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL
    )
    """))

    # -- user_tokens
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS user_tokens (
        id integer NOT NULL,
        user_id integer NOT NULL,
        token character varying(128) NOT NULL,
        purpose user_token_purpose NOT NULL,
        expires_at timestamp with time zone NOT NULL,
        created_at timestamp with time zone NOT NULL,
        consumed_at timestamp with time zone,
        device_name character varying(255)
    )
    """))

    # -- user_api_keys
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS user_api_keys (
        id integer NOT NULL,
        user_id integer NOT NULL,
        name character varying(100) NOT NULL,
        token_prefix character varying(16) NOT NULL,
        token_hash character varying(128) NOT NULL,
        is_active boolean DEFAULT true NOT NULL,
        created_at timestamp with time zone NOT NULL,
        last_used_at timestamp with time zone,
        expires_at timestamp with time zone
    )
    """))

    # -- push_tokens
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS push_tokens (
        id integer NOT NULL,
        user_id integer NOT NULL,
        device_token_id integer,
        push_token character varying(512) NOT NULL,
        platform character varying(32) NOT NULL,
        created_at timestamp with time zone DEFAULT now() NOT NULL,
        updated_at timestamp with time zone DEFAULT now() NOT NULL,
        last_used_at timestamp with time zone
    )
    """))

    # -- task_assignment_digest_items
    connection.execute(text("""
    CREATE TABLE IF NOT EXISTS task_assignment_digest_items (
        id integer NOT NULL,
        user_id integer NOT NULL,
        task_id integer NOT NULL,
        project_id integer NOT NULL,
        task_title character varying(255) NOT NULL,
        project_name character varying(255) NOT NULL,
        assigned_by_name character varying(255) NOT NULL,
        assigned_by_id integer,
        created_at timestamp with time zone NOT NULL,
        processed_at timestamp with time zone
    )
    """))

    # ===================================================================
    # SEQUENCES
    # ===================================================================
    _create_sequences(connection)

    # ===================================================================
    # COLUMN DEFAULTS (set after sequences exist)
    # ===================================================================
    _set_column_defaults(connection)

    # ===================================================================
    # PRIMARY KEY AND UNIQUE CONSTRAINTS
    # ===================================================================
    _create_constraints(connection)

    # ===================================================================
    # INDEXES
    # ===================================================================
    _create_indexes(connection)

    # ===================================================================
    # TRIGGERS
    # ===================================================================
    _create_triggers(connection)

    # ===================================================================
    # FOREIGN KEY CONSTRAINTS
    # ===================================================================
    _create_foreign_keys(connection)

    # ===================================================================
    # ENABLE / FORCE ROW LEVEL SECURITY
    # ===================================================================
    _enable_rls(connection)


def _create_sequences(connection) -> None:
    """Create all sequences (idempotent)."""
    sequences = [
        ("users_id_seq", "users", "id"),
        ("guilds_id_seq", "guilds", "id"),
        ("guild_invites_id_seq", "guild_invites", "id"),
        ("guild_settings_id_seq", "guild_settings", "id"),
        ("app_settings_id_seq", "app_settings", "id"),
        ("teams_id_seq", "initiatives", "id"),  # legacy name
        ("initiative_roles_id_seq", "initiative_roles", "id"),
        ("oidc_claim_mappings_id_seq", "oidc_claim_mappings", "id"),
        ("projects_id_seq", "projects", "id"),
        ("tags_id_seq", "tags", "id"),
        ("task_statuses_id_seq", "task_statuses", "id"),
        ("tasks_id_seq", "tasks", "id"),
        ("subtasks_id_seq", "subtasks", "id"),
        ("documents_id_seq", "documents", "id"),
        ("comments_id_seq", "comments", "id"),
        ("notifications_id_seq", "notifications", "id"),
        ("user_tokens_id_seq", "user_tokens", "id"),
        ("admin_api_keys_id_seq", "user_api_keys", "id"),  # legacy name
        ("push_tokens_id_seq", "push_tokens", "id"),
        ("task_assignment_digest_items_id_seq", "task_assignment_digest_items", "id"),
    ]

    for seq_name, table_name, col_name in sequences:
        connection.execute(text(f"""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_sequences WHERE schemaname = 'public' AND sequencename = '{seq_name}'
            ) THEN
                CREATE SEQUENCE {seq_name} AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
                ALTER SEQUENCE {seq_name} OWNED BY {table_name}.{col_name};
            END IF;
        END $$
        """))


def _set_column_defaults(connection) -> None:
    """Wire up nextval() defaults for serial-like columns."""
    defaults = [
        ("users", "id", "users_id_seq"),
        ("guilds", "id", "guilds_id_seq"),
        ("guild_invites", "id", "guild_invites_id_seq"),
        ("guild_settings", "id", "guild_settings_id_seq"),
        ("app_settings", "id", "app_settings_id_seq"),
        ("initiatives", "id", "teams_id_seq"),
        ("initiative_roles", "id", "initiative_roles_id_seq"),
        ("oidc_claim_mappings", "id", "oidc_claim_mappings_id_seq"),
        ("projects", "id", "projects_id_seq"),
        ("tags", "id", "tags_id_seq"),
        ("task_statuses", "id", "task_statuses_id_seq"),
        ("tasks", "id", "tasks_id_seq"),
        ("subtasks", "id", "subtasks_id_seq"),
        ("documents", "id", "documents_id_seq"),
        ("comments", "id", "comments_id_seq"),
        ("notifications", "id", "notifications_id_seq"),
        ("user_tokens", "id", "user_tokens_id_seq"),
        ("user_api_keys", "id", "admin_api_keys_id_seq"),
        ("push_tokens", "id", "push_tokens_id_seq"),
        ("task_assignment_digest_items", "id", "task_assignment_digest_items_id_seq"),
    ]

    for table_name, col_name, seq_name in defaults:
        connection.execute(text(f"""
        DO $$ BEGIN
            ALTER TABLE ONLY {table_name}
                ALTER COLUMN {col_name} SET DEFAULT nextval('{seq_name}'::regclass);
        EXCEPTION WHEN others THEN null;
        END $$
        """))


def _create_constraints(connection) -> None:
    """Add primary keys and unique constraints (idempotent via exception handling)."""
    constraints = [
        # Primary keys
        ("users", "users_pkey", "PRIMARY KEY (id)"),
        ("guilds", "guilds_pkey", "PRIMARY KEY (id)"),
        ("guild_memberships", "guild_memberships_pkey", "PRIMARY KEY (guild_id, user_id)"),
        ("guild_invites", "guild_invites_pkey", "PRIMARY KEY (id)"),
        ("guild_settings", "guild_settings_pkey", "PRIMARY KEY (id)"),
        ("app_settings", "app_settings_pkey", "PRIMARY KEY (id)"),
        ("initiatives", "teams_pkey", "PRIMARY KEY (id)"),
        ("initiative_roles", "initiative_roles_pkey", "PRIMARY KEY (id)"),
        ("initiative_role_permissions", "initiative_role_permissions_pkey", "PRIMARY KEY (initiative_role_id, permission_key)"),
        ("initiative_members", "team_members_pkey", "PRIMARY KEY (initiative_id, user_id)"),
        ("oidc_claim_mappings", "oidc_claim_mappings_pkey", "PRIMARY KEY (id)"),
        ("projects", "projects_pkey", "PRIMARY KEY (id)"),
        ("project_permissions", "project_members_pkey", "PRIMARY KEY (project_id, user_id)"),
        ("project_role_permissions", "project_role_permissions_pkey", "PRIMARY KEY (project_id, initiative_role_id)"),
        ("project_favorites", "project_favorites_pkey", "PRIMARY KEY (user_id, project_id)"),
        ("project_orders", "project_orders_pkey", "PRIMARY KEY (user_id, project_id)"),
        ("recent_project_views", "recent_project_views_pkey", "PRIMARY KEY (user_id, project_id)"),
        ("tags", "tags_pkey", "PRIMARY KEY (id)"),
        ("task_statuses", "task_statuses_pkey", "PRIMARY KEY (id)"),
        ("tasks", "tasks_pkey", "PRIMARY KEY (id)"),
        ("task_assignees", "task_assignees_pkey", "PRIMARY KEY (task_id, user_id)"),
        ("task_tags", "task_tags_pkey", "PRIMARY KEY (task_id, tag_id)"),
        ("project_tags", "project_tags_pkey", "PRIMARY KEY (project_id, tag_id)"),
        ("subtasks", "subtasks_pkey", "PRIMARY KEY (id)"),
        ("documents", "documents_pkey", "PRIMARY KEY (id)"),
        ("document_permissions", "document_permissions_pkey", "PRIMARY KEY (document_id, user_id)"),
        ("document_role_permissions", "document_role_permissions_pkey", "PRIMARY KEY (document_id, initiative_role_id)"),
        ("document_links", "document_links_pkey", "PRIMARY KEY (source_document_id, target_document_id)"),
        ("document_tags", "document_tags_pkey", "PRIMARY KEY (document_id, tag_id)"),
        ("project_documents", "project_documents_pkey", "PRIMARY KEY (project_id, document_id)"),
        ("comments", "comments_pkey", "PRIMARY KEY (id)"),
        ("notifications", "notifications_pkey", "PRIMARY KEY (id)"),
        ("user_tokens", "user_tokens_pkey", "PRIMARY KEY (id)"),
        ("user_api_keys", "admin_api_keys_pkey", "PRIMARY KEY (id)"),
        ("push_tokens", "push_tokens_pkey", "PRIMARY KEY (id)"),
        ("task_assignment_digest_items", "task_assignment_digest_items_pkey", "PRIMARY KEY (id)"),
        # Unique constraints
        ("users", "users_email_key", "UNIQUE (email)"),
        ("guild_settings", "guild_settings_guild_id_key", "UNIQUE (guild_id)"),
        ("user_api_keys", "admin_api_keys_token_hash_key", "UNIQUE (token_hash)"),
        ("initiative_roles", "uq_initiative_role_name", "UNIQUE (initiative_id, name)"),
    ]

    for table_name, constraint_name, definition in constraints:
        connection.execute(text(f"""
        DO $$ BEGIN
            ALTER TABLE ONLY {table_name} ADD CONSTRAINT {constraint_name} {definition};
        EXCEPTION WHEN duplicate_object THEN null;
                  WHEN duplicate_table THEN null;
        END $$
        """))


def _create_indexes(connection) -> None:
    """Create all indexes (idempotent with IF NOT EXISTS)."""

    # Regular indexes
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_documents_updated_at ON documents USING btree (updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_guild_memberships_user_guild ON guild_memberships USING btree (user_id, guild_id)",
        "CREATE INDEX IF NOT EXISTS idx_task_assignment_digest_items_unprocessed ON task_assignment_digest_items USING btree (processed_at) WHERE (processed_at IS NULL)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_due_date_status ON tasks USING btree (due_date, task_status_id) WHERE (due_date IS NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_project_archived ON tasks USING btree (project_id, is_archived)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_updated_at ON tasks USING btree (updated_at)",
        "CREATE INDEX IF NOT EXISTS ix_admin_api_keys_token_prefix ON user_api_keys USING btree (token_prefix)",
        "CREATE INDEX IF NOT EXISTS ix_admin_api_keys_user_id ON user_api_keys USING btree (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_comments_author_id ON comments USING btree (author_id)",
        "CREATE INDEX IF NOT EXISTS ix_comments_created_at ON comments USING btree (created_at)",
        "CREATE INDEX IF NOT EXISTS ix_comments_document_id ON comments USING btree (document_id)",
        "CREATE INDEX IF NOT EXISTS ix_comments_parent_comment_id ON comments USING btree (parent_comment_id)",
        "CREATE INDEX IF NOT EXISTS ix_comments_task_id ON comments USING btree (task_id)",
        "CREATE INDEX IF NOT EXISTS ix_document_links_target_document_id ON document_links USING btree (target_document_id)",
        "CREATE INDEX IF NOT EXISTS ix_document_permissions_guild_id ON document_permissions USING btree (guild_id)",
        "CREATE INDEX IF NOT EXISTS ix_document_tags_document_id ON document_tags USING btree (document_id)",
        "CREATE INDEX IF NOT EXISTS ix_document_tags_tag_id ON document_tags USING btree (tag_id)",
        "CREATE INDEX IF NOT EXISTS ix_documents_guild_id ON documents USING btree (guild_id)",
        "CREATE INDEX IF NOT EXISTS ix_documents_initiative_id ON documents USING btree (initiative_id)",
        "CREATE INDEX IF NOT EXISTS ix_documents_title ON documents USING btree (title)",
        "CREATE INDEX IF NOT EXISTS ix_initiative_members_guild_id ON initiative_members USING btree (guild_id)",
        "CREATE INDEX IF NOT EXISTS ix_initiative_members_role_id ON initiative_members USING btree (role_id)",
        "CREATE INDEX IF NOT EXISTS ix_initiative_roles_initiative_id ON initiative_roles USING btree (initiative_id)",
        "CREATE INDEX IF NOT EXISTS ix_initiatives_name ON initiatives USING btree (name)",
        "CREATE INDEX IF NOT EXISTS ix_notifications_user_read ON notifications USING btree (user_id, read_at)",
        "CREATE INDEX IF NOT EXISTS ix_project_documents_guild_id ON project_documents USING btree (guild_id)",
        "CREATE INDEX IF NOT EXISTS ix_project_documents_project_id ON project_documents USING btree (project_id)",
        "CREATE INDEX IF NOT EXISTS ix_project_favorites_guild_id ON project_favorites USING btree (guild_id)",
        "CREATE INDEX IF NOT EXISTS ix_project_favorites_project_id ON project_favorites USING btree (project_id)",
        "CREATE INDEX IF NOT EXISTS ix_project_favorites_user_id ON project_favorites USING btree (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_project_orders_guild_id ON project_orders USING btree (guild_id)",
        "CREATE INDEX IF NOT EXISTS ix_project_permissions_guild_id ON project_permissions USING btree (guild_id)",
        "CREATE INDEX IF NOT EXISTS ix_project_tags_project_id ON project_tags USING btree (project_id)",
        "CREATE INDEX IF NOT EXISTS ix_project_tags_tag_id ON project_tags USING btree (tag_id)",
        "CREATE INDEX IF NOT EXISTS ix_projects_guild_id ON projects USING btree (guild_id)",
        "CREATE INDEX IF NOT EXISTS ix_projects_name ON projects USING btree (name)",
        "CREATE INDEX IF NOT EXISTS ix_push_tokens_push_token ON push_tokens USING btree (push_token)",
        "CREATE INDEX IF NOT EXISTS ix_push_tokens_user_id ON push_tokens USING btree (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_recent_project_views_guild_id ON recent_project_views USING btree (guild_id)",
        "CREATE INDEX IF NOT EXISTS ix_recent_project_views_last_viewed_at ON recent_project_views USING btree (last_viewed_at)",
        "CREATE INDEX IF NOT EXISTS ix_recent_project_views_project_id ON recent_project_views USING btree (project_id)",
        "CREATE INDEX IF NOT EXISTS ix_recent_project_views_user_id ON recent_project_views USING btree (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_subtasks_guild_id ON subtasks USING btree (guild_id)",
        "CREATE INDEX IF NOT EXISTS ix_subtasks_task_id ON subtasks USING btree (task_id)",
        "CREATE INDEX IF NOT EXISTS ix_tags_guild_id ON tags USING btree (guild_id)",
        "CREATE INDEX IF NOT EXISTS ix_task_assignees_guild_id ON task_assignees USING btree (guild_id)",
        "CREATE INDEX IF NOT EXISTS ix_task_assignment_digest_items_user_id ON task_assignment_digest_items USING btree (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_task_statuses_guild_id ON task_statuses USING btree (guild_id)",
        "CREATE INDEX IF NOT EXISTS ix_task_statuses_project_position ON task_statuses USING btree (project_id, \"position\")",
        "CREATE INDEX IF NOT EXISTS ix_task_tags_tag_id ON task_tags USING btree (tag_id)",
        "CREATE INDEX IF NOT EXISTS ix_task_tags_task_id ON task_tags USING btree (task_id)",
        "CREATE INDEX IF NOT EXISTS ix_tasks_guild_id ON tasks USING btree (guild_id)",
        "CREATE INDEX IF NOT EXISTS ix_tasks_is_archived ON tasks USING btree (is_archived)",
        "CREATE INDEX IF NOT EXISTS ix_tasks_project_id_id ON tasks USING btree (project_id, id)",
        "CREATE INDEX IF NOT EXISTS ix_user_tokens_user_id ON user_tokens USING btree (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_users_email ON users USING btree (email)",
    ]
    for idx_sql in indexes:
        connection.execute(text(idx_sql))

    # Unique indexes
    unique_indexes = [
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_guild_invites_code ON guild_invites USING btree (code)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_tags_guild_name_unique ON tags USING btree (guild_id, lower((name)::text))",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_push_tokens_user_device_token ON push_tokens USING btree (user_id, push_token)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_user_tokens_token ON user_tokens USING btree (token)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_initiatives_guild_default ON initiatives USING btree (guild_id) WHERE is_default",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_initiatives_guild_name ON initiatives USING btree (guild_id, lower((name)::text))",
    ]
    for idx_sql in unique_indexes:
        connection.execute(text(idx_sql))


def _create_triggers(connection) -> None:
    """Create guild_id propagation triggers (idempotent: drop + create)."""
    triggers = [
        ("tr_comments_set_guild_id", "comments", "BEFORE INSERT OR UPDATE OF task_id, document_id", "fn_comments_set_guild_id"),
        ("tr_document_permissions_set_guild_id", "document_permissions", "BEFORE INSERT OR UPDATE OF document_id", "fn_document_permissions_set_guild_id"),
        ("tr_documents_set_guild_id", "documents", "BEFORE INSERT OR UPDATE OF initiative_id", "fn_documents_set_guild_id"),
        ("tr_initiative_members_set_guild_id", "initiative_members", "BEFORE INSERT OR UPDATE OF initiative_id", "fn_initiative_members_set_guild_id"),
        ("tr_project_documents_set_guild_id", "project_documents", "BEFORE INSERT OR UPDATE OF project_id", "fn_project_documents_set_guild_id"),
        ("tr_project_favorites_set_guild_id", "project_favorites", "BEFORE INSERT OR UPDATE OF project_id", "fn_project_favorites_set_guild_id"),
        ("tr_project_orders_set_guild_id", "project_orders", "BEFORE INSERT OR UPDATE OF project_id", "fn_project_orders_set_guild_id"),
        ("tr_project_permissions_set_guild_id", "project_permissions", "BEFORE INSERT OR UPDATE OF project_id", "fn_project_permissions_set_guild_id"),
        ("tr_projects_set_guild_id", "projects", "BEFORE INSERT OR UPDATE OF initiative_id", "fn_projects_set_guild_id"),
        ("tr_recent_project_views_set_guild_id", "recent_project_views", "BEFORE INSERT OR UPDATE OF project_id", "fn_recent_project_views_set_guild_id"),
        ("tr_subtasks_set_guild_id", "subtasks", "BEFORE INSERT OR UPDATE OF task_id", "fn_subtasks_set_guild_id"),
        ("tr_task_assignees_set_guild_id", "task_assignees", "BEFORE INSERT OR UPDATE OF task_id", "fn_task_assignees_set_guild_id"),
        ("tr_task_statuses_set_guild_id", "task_statuses", "BEFORE INSERT OR UPDATE OF project_id", "fn_task_statuses_set_guild_id"),
        ("tr_tasks_set_guild_id", "tasks", "BEFORE INSERT OR UPDATE OF project_id", "fn_tasks_set_guild_id"),
    ]

    for trigger_name, table_name, timing, func_name in triggers:
        connection.execute(text(f"DROP TRIGGER IF EXISTS {trigger_name} ON {table_name}"))
        connection.execute(text(
            f"CREATE TRIGGER {trigger_name} {timing} ON {table_name} "
            f"FOR EACH ROW EXECUTE FUNCTION {func_name}()"
        ))


def _create_foreign_keys(connection) -> None:
    """Add all foreign key constraints (idempotent via exception handling)."""
    fks = [
        # user_api_keys
        ("user_api_keys", "admin_api_keys_user_id_fkey", "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"),
        # comments
        ("comments", "comments_author_id_fkey", "FOREIGN KEY (author_id) REFERENCES users(id) ON DELETE CASCADE"),
        ("comments", "comments_document_id_fkey", "FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE"),
        ("comments", "comments_parent_comment_id_fkey", "FOREIGN KEY (parent_comment_id) REFERENCES comments(id) ON DELETE CASCADE"),
        ("comments", "comments_task_id_fkey", "FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE"),
        # document_links
        ("document_links", "document_links_guild_id_fkey", "FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE"),
        ("document_links", "document_links_source_document_id_fkey", "FOREIGN KEY (source_document_id) REFERENCES documents(id) ON DELETE CASCADE"),
        ("document_links", "document_links_target_document_id_fkey", "FOREIGN KEY (target_document_id) REFERENCES documents(id) ON DELETE CASCADE"),
        # document_permissions
        ("document_permissions", "document_permissions_document_id_fkey", "FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE"),
        ("document_permissions", "document_permissions_user_id_fkey", "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"),
        ("document_permissions", "fk_document_permissions_guild_id", "FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE"),
        # document_role_permissions
        ("document_role_permissions", "document_role_permissions_document_id_fkey", "FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE"),
        ("document_role_permissions", "document_role_permissions_guild_id_fkey", "FOREIGN KEY (guild_id) REFERENCES guilds(id)"),
        ("document_role_permissions", "document_role_permissions_initiative_role_id_fkey", "FOREIGN KEY (initiative_role_id) REFERENCES initiative_roles(id) ON DELETE CASCADE"),
        # document_tags
        ("document_tags", "document_tags_document_id_fkey", "FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE"),
        ("document_tags", "document_tags_tag_id_fkey", "FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE"),
        # documents
        ("documents", "documents_created_by_id_fkey", "FOREIGN KEY (created_by_id) REFERENCES users(id)"),
        ("documents", "documents_initiative_id_fkey", "FOREIGN KEY (initiative_id) REFERENCES initiatives(id) ON DELETE CASCADE"),
        ("documents", "documents_updated_by_id_fkey", "FOREIGN KEY (updated_by_id) REFERENCES users(id)"),
        ("documents", "fk_documents_guild_id", "FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE"),
        # guild_invites
        ("guild_invites", "guild_invites_created_by_user_id_fkey", "FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL"),
        ("guild_invites", "guild_invites_guild_id_fkey", "FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE"),
        # guild_memberships
        ("guild_memberships", "guild_memberships_guild_id_fkey", "FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE"),
        ("guild_memberships", "guild_memberships_user_id_fkey", "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"),
        # guild_settings
        ("guild_settings", "guild_settings_guild_id_fkey", "FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE"),
        # guilds
        ("guilds", "guilds_created_by_user_id_fkey", "FOREIGN KEY (created_by_user_id) REFERENCES users(id)"),
        # initiative_members
        ("initiative_members", "fk_initiative_members_guild_id", "FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE"),
        ("initiative_members", "initiative_members_role_id_fkey", "FOREIGN KEY (role_id) REFERENCES initiative_roles(id) ON DELETE SET NULL"),
        ("initiative_members", "team_members_team_id_fkey", "FOREIGN KEY (initiative_id) REFERENCES initiatives(id)"),
        ("initiative_members", "team_members_user_id_fkey", "FOREIGN KEY (user_id) REFERENCES users(id)"),
        # initiative_role_permissions
        ("initiative_role_permissions", "initiative_role_permissions_initiative_role_id_fkey", "FOREIGN KEY (initiative_role_id) REFERENCES initiative_roles(id) ON DELETE CASCADE"),
        # initiative_roles
        ("initiative_roles", "initiative_roles_initiative_id_fkey", "FOREIGN KEY (initiative_id) REFERENCES initiatives(id) ON DELETE CASCADE"),
        # initiatives
        ("initiatives", "fk_initiatives_guild_id", "FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE"),
        # notifications
        ("notifications", "notifications_user_id_fkey", "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"),
        # oidc_claim_mappings
        ("oidc_claim_mappings", "oidc_claim_mappings_guild_id_fkey", "FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE"),
        ("oidc_claim_mappings", "oidc_claim_mappings_initiative_id_fkey", "FOREIGN KEY (initiative_id) REFERENCES initiatives(id) ON DELETE CASCADE"),
        ("oidc_claim_mappings", "oidc_claim_mappings_initiative_role_id_fkey", "FOREIGN KEY (initiative_role_id) REFERENCES initiative_roles(id) ON DELETE SET NULL"),
        # project_documents
        ("project_documents", "fk_project_documents_guild_id", "FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE"),
        ("project_documents", "project_documents_attached_by_id_fkey", "FOREIGN KEY (attached_by_id) REFERENCES users(id) ON DELETE SET NULL"),
        ("project_documents", "project_documents_document_id_fkey", "FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE"),
        ("project_documents", "project_documents_project_id_fkey", "FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE"),
        # project_favorites
        ("project_favorites", "fk_project_favorites_guild_id", "FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE"),
        ("project_favorites", "project_favorites_project_id_fkey", "FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE"),
        ("project_favorites", "project_favorites_user_id_fkey", "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"),
        # project_orders
        ("project_orders", "fk_project_orders_guild_id", "FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE"),
        ("project_orders", "project_orders_project_id_fkey", "FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE"),
        ("project_orders", "project_orders_user_id_fkey", "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"),
        # project_permissions
        ("project_permissions", "fk_project_permissions_guild_id", "FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE"),
        ("project_permissions", "project_members_project_id_fkey", "FOREIGN KEY (project_id) REFERENCES projects(id)"),
        ("project_permissions", "project_members_user_id_fkey", "FOREIGN KEY (user_id) REFERENCES users(id)"),
        # project_role_permissions
        ("project_role_permissions", "project_role_permissions_guild_id_fkey", "FOREIGN KEY (guild_id) REFERENCES guilds(id)"),
        ("project_role_permissions", "project_role_permissions_initiative_role_id_fkey", "FOREIGN KEY (initiative_role_id) REFERENCES initiative_roles(id) ON DELETE CASCADE"),
        ("project_role_permissions", "project_role_permissions_project_id_fkey", "FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE"),
        # project_tags
        ("project_tags", "project_tags_project_id_fkey", "FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE"),
        ("project_tags", "project_tags_tag_id_fkey", "FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE"),
        # projects
        ("projects", "fk_projects_guild_id", "FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE"),
        ("projects", "projects_owner_id_fkey", "FOREIGN KEY (owner_id) REFERENCES users(id)"),
        ("projects", "projects_team_id_fkey", "FOREIGN KEY (initiative_id) REFERENCES initiatives(id)"),
        # push_tokens
        ("push_tokens", "push_tokens_device_token_id_fkey", "FOREIGN KEY (device_token_id) REFERENCES user_tokens(id) ON DELETE CASCADE"),
        ("push_tokens", "push_tokens_user_id_fkey", "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"),
        # recent_project_views
        ("recent_project_views", "fk_recent_project_views_guild_id", "FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE"),
        ("recent_project_views", "recent_project_views_project_id_fkey", "FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE"),
        ("recent_project_views", "recent_project_views_user_id_fkey", "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"),
        # subtasks
        ("subtasks", "fk_subtasks_guild_id", "FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE"),
        ("subtasks", "fk_subtasks_task_id", "FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE"),
        # tags
        ("tags", "tags_guild_id_fkey", "FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE"),
        # task_assignees
        ("task_assignees", "fk_task_assignees_guild_id", "FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE"),
        ("task_assignees", "task_assignees_task_id_fkey", "FOREIGN KEY (task_id) REFERENCES tasks(id)"),
        ("task_assignees", "task_assignees_user_id_fkey", "FOREIGN KEY (user_id) REFERENCES users(id)"),
        # task_assignment_digest_items
        ("task_assignment_digest_items", "task_assignment_digest_items_assigned_by_id_fkey", "FOREIGN KEY (assigned_by_id) REFERENCES users(id) ON DELETE SET NULL"),
        ("task_assignment_digest_items", "task_assignment_digest_items_project_id_fkey", "FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE"),
        ("task_assignment_digest_items", "task_assignment_digest_items_task_id_fkey", "FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE"),
        ("task_assignment_digest_items", "task_assignment_digest_items_user_id_fkey", "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"),
        # task_statuses
        ("task_statuses", "fk_task_statuses_guild_id", "FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE"),
        ("task_statuses", "task_statuses_project_id_fkey", "FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE"),
        # task_tags
        ("task_tags", "task_tags_tag_id_fkey", "FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE"),
        ("task_tags", "task_tags_task_id_fkey", "FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE"),
        # tasks
        ("tasks", "fk_tasks_guild_id", "FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE"),
        ("tasks", "fk_tasks_task_status_id", "FOREIGN KEY (task_status_id) REFERENCES task_statuses(id) ON DELETE RESTRICT"),
        ("tasks", "tasks_project_id_fkey", "FOREIGN KEY (project_id) REFERENCES projects(id)"),
        # user_tokens
        ("user_tokens", "user_tokens_user_id_fkey", "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"),
    ]

    for table_name, fk_name, definition in fks:
        connection.execute(text(f"""
        DO $$ BEGIN
            ALTER TABLE ONLY {table_name} ADD CONSTRAINT {fk_name} {definition};
        EXCEPTION WHEN duplicate_object THEN null;
        END $$
        """))


def _enable_rls(connection) -> None:
    """Enable and force row level security on tables that need it.

    ENABLE RLS and FORCE RLS are idempotent -- re-running is a no-op.
    """
    # Tables that need ENABLE + FORCE RLS
    force_rls_tables = [
        "comments",
        "document_links",
        "document_permissions",
        "document_role_permissions",
        "document_tags",
        "documents",
        "guild_invites",
        "guild_memberships",
        "guild_settings",
        "guilds",
        "initiative_members",
        "initiative_role_permissions",
        "initiative_roles",
        "initiatives",
        "oidc_claim_mappings",
        "project_documents",
        "project_favorites",
        "project_orders",
        "project_permissions",
        "project_role_permissions",
        "project_tags",
        "projects",
        "recent_project_views",
        "subtasks",
        "tags",
        "task_assignees",
        "task_statuses",
        "task_tags",
        "tasks",
    ]

    for table_name in force_rls_tables:
        connection.execute(text(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY"))
        connection.execute(text(f"ALTER TABLE ONLY {table_name} FORCE ROW LEVEL SECURITY"))


# ---------------------------------------------------------------------------
# 3. RLS Policies
# ---------------------------------------------------------------------------

def _create_rls_policies(connection) -> None:
    """Create all RLS policies using DROP IF EXISTS + CREATE pattern."""

    # Shorthand constants for policy expressions
    GUILD_ID = "NULLIF(current_setting('app.current_guild_id'::text, true), ''::text)::integer"
    USER_ID = "NULLIF(current_setting('app.current_user_id'::text, true), ''::text)::integer"
    GUILD_ROLE = "current_setting('app.current_guild_role'::text, true)"
    IS_SUPER = "current_setting('app.is_superadmin'::text, true) = 'true'::text"
    IS_ADMIN = f"{GUILD_ROLE} = 'admin'::text"

    # Helper: standard guild_id = current_guild_id check
    def gid_eq(table_alias: str = "", col: str = "guild_id") -> str:
        prefix = f"{table_alias}." if table_alias else ""
        return f"({prefix}{col} = ({GUILD_ID}))"

    # Helper: guild membership EXISTS check
    def member_check(table_name: str, guild_col: str = "guild_id") -> str:
        return (
            f"(EXISTS (SELECT 1 FROM guild_memberships "
            f"WHERE guild_memberships.guild_id = {table_name}.{guild_col} "
            f"AND guild_memberships.user_id = ({USER_ID})))"
        )

    # Helper: initiative member check via is_initiative_member()
    def init_member(init_col: str) -> str:
        return f"is_initiative_member({init_col}, ({USER_ID}))"

    def init_member_via_role(role_fk_table: str, role_fk_col: str = "initiative_role_id") -> str:
        return (
            f"(EXISTS (SELECT 1 FROM initiative_roles "
            f"WHERE initiative_roles.id = {role_fk_table}.{role_fk_col} "
            f"AND is_initiative_member(initiative_roles.initiative_id, ({USER_ID}))))"
        )

    # Helper: tag-based join check for junction tables
    def tag_guild_check(junction: str) -> str:
        return (
            f"(EXISTS (SELECT 1 FROM tags "
            f"WHERE tags.id = {junction}.tag_id "
            f"AND {gid_eq('tags')}))"
        )

    def tag_member_check(junction: str) -> str:
        return (
            f"(EXISTS (SELECT 1 FROM tags "
            f"JOIN guild_memberships ON guild_memberships.guild_id = tags.guild_id "
            f"WHERE tags.id = {junction}.tag_id "
            f"AND guild_memberships.user_id = ({USER_ID})))"
        )

    # Collect all policies as (table, name, command, type, using_clause, check_clause)
    # type is '' for PERMISSIVE or 'AS RESTRICTIVE' for restrictive
    policies: list[tuple[str, str, str, str, str, str]] = []

    # -----------------------------------------------------------------------
    # GUILD-SCOPED TABLES: standard 4-policy CRUD pattern
    # (guild_select via membership, guild_insert/update/delete via guild_id match)
    # -----------------------------------------------------------------------
    standard_guild_tables = [
        "comments", "document_permissions", "document_role_permissions",
        "documents", "guild_invites",
        "guild_settings", "initiative_members", "initiatives",
        "project_documents", "project_favorites", "project_orders",
        "project_permissions", "project_role_permissions", "projects",
        "recent_project_views", "subtasks", "tags", "task_assignees",
        "task_statuses", "tasks",
    ]
    for t in standard_guild_tables:
        # SELECT via membership
        policies.append((t, "guild_select", "SELECT", "",
            f"({member_check(t)} OR ({IS_SUPER}))", ""))
        # INSERT via guild_id match
        policies.append((t, "guild_insert", "INSERT", "",
            "", f"({gid_eq()} OR ({IS_SUPER}))"))
        # UPDATE via guild_id match
        policies.append((t, "guild_update", "UPDATE", "",
            f"({gid_eq()} OR ({IS_SUPER}))", f"({gid_eq()} OR ({IS_SUPER}))"))
        # DELETE via guild_id match
        policies.append((t, "guild_delete", "DELETE", "",
            f"({gid_eq()} OR ({IS_SUPER}))", ""))

    # Override: guilds has special SELECT, INSERT, UPDATE, DELETE
    # Remove the auto-generated ones and add custom
    policies = [(t, n, c, tp, u, ch) for (t, n, c, tp, u, ch) in policies if t != "guilds"]

    # guilds SELECT: match current guild OR membership
    policies.append(("guilds", "guild_select", "SELECT", "",
        f"((id = ({GUILD_ID})) OR (EXISTS (SELECT 1 FROM guild_memberships WHERE guild_memberships.guild_id = guilds.id AND guild_memberships.user_id = ({USER_ID}))) OR ({IS_SUPER}))", ""))
    # guilds INSERT: any authenticated user (or superadmin)
    policies.append(("guilds", "guild_insert", "INSERT", "",
        "", f"((({USER_ID}) IS NOT NULL) OR ({IS_SUPER}))"))
    # guilds UPDATE: admin of the guild or superadmin
    policies.append(("guilds", "guild_update", "UPDATE", "",
        f"(((id = ({GUILD_ID})) AND ({IS_ADMIN})) OR ({IS_SUPER}))",
        f"(((id = ({GUILD_ID})) AND ({IS_ADMIN})) OR ({IS_SUPER}))"))
    # guilds DELETE: admin of the guild or superadmin
    policies.append(("guilds", "guild_delete", "DELETE", "",
        f"(((id = ({GUILD_ID})) AND ({IS_ADMIN})) OR ({IS_SUPER}))", ""))

    # Override: guild_memberships has separate named policies
    policies = [(t, n, c, tp, u, ch) for (t, n, c, tp, u, ch) in policies if t != "guild_memberships"]

    policies.append(("guild_memberships", "guild_memberships_select", "SELECT", "",
        f"({gid_eq()} OR (user_id = ({USER_ID})) OR ({IS_SUPER}))", ""))
    policies.append(("guild_memberships", "guild_memberships_insert", "INSERT", "",
        "", f"({gid_eq()} OR ({IS_SUPER}))"))
    policies.append(("guild_memberships", "guild_memberships_update", "UPDATE", "",
        f"({gid_eq()} OR ({IS_SUPER}))", f"({gid_eq()} OR ({IS_SUPER}))"))
    policies.append(("guild_memberships", "guild_memberships_delete", "DELETE", "",
        f"({gid_eq()} OR ({IS_SUPER}))", ""))

    # Override: document_links has NULL-guild handling
    policies = [(t, n, c, tp, u, ch) for (t, n, c, tp, u, ch) in policies if t != "document_links"]

    dl_null_or_match = f"((guild_id IS NULL) OR {gid_eq()} OR ({IS_SUPER}))"
    dl_select = f"((guild_id IS NULL) OR {member_check('document_links')} OR ({IS_SUPER}))"
    policies.append(("document_links", "guild_select", "SELECT", "", dl_select, ""))
    policies.append(("document_links", "guild_insert", "INSERT", "", "", dl_null_or_match))
    policies.append(("document_links", "guild_update", "UPDATE", "", dl_null_or_match, dl_null_or_match))
    policies.append(("document_links", "guild_delete", "DELETE", "", dl_null_or_match, ""))

    # Override: document_role_permissions - handled below with initiative scoping

    # Tag-based junction tables: document_tags, project_tags, task_tags
    for jt in ["document_tags", "project_tags", "task_tags"]:
        # Remove auto-generated and replace
        policies = [(t, n, c, tp, u, ch) for (t, n, c, tp, u, ch) in policies if t != jt]

        policies.append((jt, "guild_select", "SELECT", "",
            f"({tag_member_check(jt)} OR ({IS_SUPER}))", ""))
        policies.append((jt, "guild_insert", "INSERT", "",
            "", f"({tag_guild_check(jt)} OR ({IS_SUPER}))"))
        policies.append((jt, "guild_update", "UPDATE", "",
            f"({tag_guild_check(jt)} OR ({IS_SUPER}))",
            f"({tag_guild_check(jt)} OR ({IS_SUPER}))"))
        policies.append((jt, "guild_delete", "DELETE", "",
            f"({tag_guild_check(jt)} OR ({IS_SUPER}))", ""))

    # oidc_claim_mappings: single guild_isolation policy (FOR ALL)
    oidc_check = f"({gid_eq()} OR ({IS_SUPER}))"
    policies.append(("oidc_claim_mappings", "guild_isolation", "ALL", "",
        oidc_check, oidc_check))

    # comments SELECT override: uses membership check (already set above, leave as-is)

    # -----------------------------------------------------------------------
    # INITIATIVE-SCOPED RESTRICTIVE POLICIES
    # Tables: initiatives, initiative_members, documents, projects,
    #         initiative_roles, initiative_role_permissions,
    #         document_role_permissions, project_role_permissions
    # -----------------------------------------------------------------------
    init_bypass = f"OR ({IS_ADMIN}) OR ({IS_SUPER})"

    # initiatives
    for cmd, clause_type in [("SELECT", "USING"), ("INSERT", "WITH CHECK"), ("UPDATE", "BOTH"), ("DELETE", "USING")]:
        expr = f"({init_member('id')} {init_bypass})"
        if cmd == "SELECT":
            policies.append(("initiatives", "initiative_member_select", "SELECT", "AS RESTRICTIVE", expr, ""))
        elif cmd == "INSERT":
            policies.append(("initiatives", "initiative_member_insert", "INSERT", "AS RESTRICTIVE", "", expr))
        elif cmd == "UPDATE":
            policies.append(("initiatives", "initiative_member_update", "UPDATE", "AS RESTRICTIVE", expr, expr))
        elif cmd == "DELETE":
            policies.append(("initiatives", "initiative_member_delete", "DELETE", "AS RESTRICTIVE", expr, ""))

    # initiative_members
    for cmd in ["SELECT", "INSERT", "UPDATE", "DELETE"]:
        expr = f"({init_member('initiative_id')} {init_bypass})"
        name = f"initiative_member_{cmd.lower()}"
        if cmd == "SELECT":
            policies.append(("initiative_members", name, cmd, "AS RESTRICTIVE", expr, ""))
        elif cmd == "INSERT":
            policies.append(("initiative_members", name, cmd, "AS RESTRICTIVE", "", expr))
        elif cmd == "UPDATE":
            policies.append(("initiative_members", name, cmd, "AS RESTRICTIVE", expr, expr))
        elif cmd == "DELETE":
            policies.append(("initiative_members", name, cmd, "AS RESTRICTIVE", expr, ""))

    # documents (initiative scoped)
    for cmd in ["SELECT", "INSERT", "UPDATE", "DELETE"]:
        expr = f"({init_member('initiative_id')} {init_bypass})"
        name = f"initiative_member_{cmd.lower()}"
        if cmd == "SELECT":
            policies.append(("documents", name, cmd, "AS RESTRICTIVE", expr, ""))
        elif cmd == "INSERT":
            policies.append(("documents", name, cmd, "AS RESTRICTIVE", "", expr))
        elif cmd == "UPDATE":
            policies.append(("documents", name, cmd, "AS RESTRICTIVE", expr, expr))
        elif cmd == "DELETE":
            policies.append(("documents", name, cmd, "AS RESTRICTIVE", expr, ""))

    # projects (initiative scoped)
    for cmd in ["SELECT", "INSERT", "UPDATE", "DELETE"]:
        expr = f"({init_member('initiative_id')} {init_bypass})"
        name = f"initiative_member_{cmd.lower()}"
        if cmd == "SELECT":
            policies.append(("projects", name, cmd, "AS RESTRICTIVE", expr, ""))
        elif cmd == "INSERT":
            policies.append(("projects", name, cmd, "AS RESTRICTIVE", "", expr))
        elif cmd == "UPDATE":
            policies.append(("projects", name, cmd, "AS RESTRICTIVE", expr, expr))
        elif cmd == "DELETE":
            policies.append(("projects", name, cmd, "AS RESTRICTIVE", expr, ""))

    # initiative_roles (NOT restrictive per the pg_dump)
    for cmd in ["SELECT", "INSERT", "UPDATE", "DELETE"]:
        expr = f"({init_member('initiative_id')} {init_bypass})"
        name = f"initiative_member_{cmd.lower()}"
        if cmd == "SELECT":
            policies.append(("initiative_roles", name, cmd, "", expr, ""))
        elif cmd == "INSERT":
            policies.append(("initiative_roles", name, cmd, "", "", expr))
        elif cmd == "UPDATE":
            policies.append(("initiative_roles", name, cmd, "", expr, expr))
        elif cmd == "DELETE":
            policies.append(("initiative_roles", name, cmd, "", expr, ""))

    # initiative_role_permissions (NOT restrictive per the pg_dump)
    for cmd in ["SELECT", "INSERT", "UPDATE", "DELETE"]:
        expr = f"({init_member_via_role('initiative_role_permissions')} {init_bypass})"
        name = f"initiative_member_{cmd.lower()}"
        if cmd == "SELECT":
            policies.append(("initiative_role_permissions", name, cmd, "", expr, ""))
        elif cmd == "INSERT":
            policies.append(("initiative_role_permissions", name, cmd, "", "", expr))
        elif cmd == "UPDATE":
            policies.append(("initiative_role_permissions", name, cmd, "", expr, expr))
        elif cmd == "DELETE":
            policies.append(("initiative_role_permissions", name, cmd, "", expr, ""))

    # document_role_permissions (RESTRICTIVE per pg_dump)
    for cmd in ["SELECT", "INSERT", "UPDATE", "DELETE"]:
        expr = f"({init_member_via_role('document_role_permissions')} {init_bypass})"
        name = f"initiative_member_{cmd.lower()}"
        if cmd == "SELECT":
            policies.append(("document_role_permissions", name, cmd, "AS RESTRICTIVE", expr, ""))
        elif cmd == "INSERT":
            policies.append(("document_role_permissions", name, cmd, "AS RESTRICTIVE", "", expr))
        elif cmd == "UPDATE":
            policies.append(("document_role_permissions", name, cmd, "AS RESTRICTIVE", expr, expr))
        elif cmd == "DELETE":
            policies.append(("document_role_permissions", name, cmd, "AS RESTRICTIVE", expr, ""))

    # project_role_permissions (RESTRICTIVE per pg_dump)
    for cmd in ["SELECT", "INSERT", "UPDATE", "DELETE"]:
        expr = f"({init_member_via_role('project_role_permissions')} {init_bypass})"
        name = f"initiative_member_{cmd.lower()}"
        if cmd == "SELECT":
            policies.append(("project_role_permissions", name, cmd, "AS RESTRICTIVE", expr, ""))
        elif cmd == "INSERT":
            policies.append(("project_role_permissions", name, cmd, "AS RESTRICTIVE", "", expr))
        elif cmd == "UPDATE":
            policies.append(("project_role_permissions", name, cmd, "AS RESTRICTIVE", expr, expr))
        elif cmd == "DELETE":
            policies.append(("project_role_permissions", name, cmd, "AS RESTRICTIVE", expr, ""))

    # -----------------------------------------------------------------------
    # Emit all policies using DROP + CREATE pattern
    # -----------------------------------------------------------------------
    for table_name, policy_name, command, restrictive, using_clause, check_clause in policies:
        connection.execute(text(f"DROP POLICY IF EXISTS {policy_name} ON {table_name}"))

        parts = [f"CREATE POLICY {policy_name} ON {table_name}"]
        if restrictive:
            parts.append(restrictive)
        if command != "ALL":
            parts.append(f"FOR {command}")
        else:
            # FOR ALL is the default, omit it
            pass
        if using_clause:
            parts.append(f"USING ({using_clause})")
        if check_clause:
            parts.append(f"WITH CHECK ({check_clause})")

        connection.execute(text(" ".join(parts)))


# ---------------------------------------------------------------------------
# 4. Grants
# ---------------------------------------------------------------------------

def _grant_privileges(connection) -> None:
    """Grant table/sequence/function privileges to app roles."""

    if _role_exists(connection, "app_user"):
        connection.execute(text(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user"
        ))
        connection.execute(text(
            "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user"
        ))
        connection.execute(text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user"
        ))
        connection.execute(text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            "GRANT USAGE, SELECT ON SEQUENCES TO app_user"
        ))
        # Grant EXECUTE on the RLS helper function
        connection.execute(text(
            "GRANT EXECUTE ON FUNCTION is_initiative_member(integer, integer) TO app_user"
        ))

    if _role_exists(connection, "app_admin"):
        connection.execute(text(
            "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO app_admin"
        ))
        connection.execute(text(
            "GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO app_admin"
        ))

    # Revoke EXECUTE from PUBLIC (defense in depth -- SECURITY DEFINER func)
    connection.execute(text("""
    DO $$ BEGIN
        REVOKE EXECUTE ON FUNCTION is_initiative_member(integer, integer) FROM PUBLIC;
    EXCEPTION WHEN undefined_function THEN null;
    END $$
    """))


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------

def upgrade() -> None:
    connection = op.get_bind()

    # Always create/sync roles (even if schema already exists, roles may
    # be missing from a partial previous run or a setup without init-db.sh).
    _create_roles(connection)

    # If the schema already exists (v0.30.0 upgrade), skip DDL.
    if _table_exists(connection, "users"):
        print("Baseline: schema already exists, nothing to do.")
        return

    _create_schema(connection)

    # Create after tables exist (references initiative_members).
    connection.execute(text("""
    CREATE OR REPLACE FUNCTION is_initiative_member(
        p_initiative_id integer, p_user_id integer
    ) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path TO 'public'
        AS $$
            SELECT EXISTS (
                SELECT 1 FROM initiative_members
                WHERE initiative_id = p_initiative_id
                AND user_id = p_user_id
            )
        $$
    """))

    _create_rls_policies(connection)
    _grant_privileges(connection)


def downgrade() -> None:
    raise NotImplementedError("Cannot downgrade from baseline. Restore from backup.")
