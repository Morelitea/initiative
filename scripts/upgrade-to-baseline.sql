-- =============================================================================
-- Initiative: Upgrade pre-v0.30.0 databases to baseline schema (v0.30.0)
-- =============================================================================
--
-- PURPOSE:
--   Brings any pre-v0.30.0 Initiative database (v0.14.1 through v0.29.x) to
--   the v0.30.0 schema state so that the baseline migration
--   (20260216_0053_baseline.py) can run and set up roles, RLS, and grants.
--
-- WHEN TO USE:
--   Run this script if you are upgrading from any version before v0.30.0 and
--   the old incremental Alembic migrations have been removed (replaced by the
--   baseline). After running this script, run `alembic upgrade head` (or start
--   the application) — the baseline migration will create database roles,
--   enable RLS policies, and grant privileges.
--
-- SAFETY:
--   * Fully idempotent -- safe to run multiple times on any schema version.
--   * Uses IF NOT EXISTS, ADD COLUMN IF NOT EXISTS, and DO blocks throughout.
--   * Prints progress via RAISE NOTICE.
--
-- NOTE: The script cannot be wrapped in a single transaction because
-- ALTER TYPE ADD VALUE must be committed before new enum values can be
-- used in DEFAULT clauses. Each phase is individually safe to re-run.
--
-- USAGE:
--   psql -v ON_ERROR_STOP=1 -f scripts/upgrade-to-baseline.sql "$DATABASE_URL"
--
-- =============================================================================

-- =========================================================================
-- PRE-TRANSACTION: Enum type creation and value additions
-- These must be committed before use in DEFAULT clauses inside the
-- transactional phases below.
-- =========================================================================

DO $preflight$
BEGIN
    -- Pre-flight check
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'users'
    ) THEN
        RAISE EXCEPTION 'users table does not exist -- this is not an Initiative database';
    END IF;
    RAISE NOTICE '=== Initiative: Upgrade to baseline v0.30.0 ===';
    RAISE NOTICE 'Phase 0: Pre-flight check passed.';
    RAISE NOTICE 'Phase 1: Ensuring enum types...';

    -- Create missing enum types
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'guild_role') THEN
        CREATE TYPE guild_role AS ENUM ('admin', 'member');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'document_permission_level') THEN
        CREATE TYPE document_permission_level AS ENUM ('read', 'write', 'owner');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'document_type') THEN
        CREATE TYPE document_type AS ENUM ('native', 'file');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'task_status_category') THEN
        CREATE TYPE task_status_category AS ENUM ('backlog', 'todo', 'in_progress', 'done');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'task_priority') THEN
        CREATE TYPE task_priority AS ENUM ('low', 'medium', 'high', 'urgent');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_role') THEN
        CREATE TYPE user_role AS ENUM ('admin', 'member');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_token_purpose') THEN
        CREATE TYPE user_token_purpose AS ENUM ('email_verification', 'password_reset', 'device_auth');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'project_permission_level') THEN
        CREATE TYPE project_permission_level AS ENUM ('owner', 'write', 'read');
    END IF;
END $preflight$;

-- Add missing enum values -- must be committed before the main transaction
-- can use them in DEFAULT clauses. IF NOT EXISTS makes them safe to repeat.
ALTER TYPE user_token_purpose ADD VALUE IF NOT EXISTS 'device_auth';
ALTER TYPE project_permission_level ADD VALUE IF NOT EXISTS 'read';
ALTER TYPE document_permission_level ADD VALUE IF NOT EXISTS 'owner';
ALTER TYPE document_type ADD VALUE IF NOT EXISTS 'file';

-- =========================================================================
-- MAIN TRANSACTION: Everything from Phase 2 onward
-- =========================================================================
BEGIN;

DO $phase2$
DECLARE
    _default_guild_id integer;
    _admin_user_id integer;
    _fallback_user_id integer;
    _default_initiative_id integer;
BEGIN

-- =========================================================================
-- PHASE 2: Reduce user_role enum if it still has 'project_manager'
-- =========================================================================
RAISE NOTICE 'Phase 2: Normalizing user_role enum...';

IF EXISTS (
    SELECT 1 FROM pg_enum
    WHERE enumtypid = 'user_role'::regtype AND enumlabel = 'project_manager'
) THEN
    -- Remap project_manager -> member
    UPDATE users SET role = 'member' WHERE role::text = 'project_manager';

    -- Recreate enum without project_manager
    ALTER TABLE users ALTER COLUMN role DROP DEFAULT;
    ALTER TYPE user_role RENAME TO user_role_old;
    CREATE TYPE user_role AS ENUM ('admin', 'member');
    ALTER TABLE users ALTER COLUMN role TYPE user_role USING role::text::user_role;
    ALTER TABLE users ALTER COLUMN role SET DEFAULT 'member'::user_role;
    DROP TYPE user_role_old;
END IF;

-- =========================================================================
-- PHASE 3: Handle table renames (teams -> initiatives, etc.)
-- =========================================================================
RAISE NOTICE 'Phase 3: Handling table renames...';

-- teams -> initiatives (from v0.14-era renames)
IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'teams'
) AND NOT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'initiatives'
) THEN
    ALTER TABLE teams RENAME TO initiatives;
    ALTER INDEX IF EXISTS ix_teams_name RENAME TO ix_initiatives_name;
END IF;

-- team_members -> initiative_members
IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'team_members'
) AND NOT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'initiative_members'
) THEN
    ALTER TABLE team_members RENAME TO initiative_members;
END IF;

-- Rename team_id -> initiative_id in initiative_members if needed
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'initiative_members' AND column_name = 'team_id'
) THEN
    ALTER TABLE initiative_members RENAME COLUMN team_id TO initiative_id;
END IF;

-- Rename team_id -> initiative_id in projects if needed
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'projects' AND column_name = 'team_id'
) THEN
    ALTER TABLE projects RENAME COLUMN team_id TO initiative_id;
END IF;

-- project_members -> project_permissions (DAC migration)
IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'project_members'
) AND NOT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'project_permissions'
) THEN
    ALTER TABLE project_members RENAME TO project_permissions;
END IF;

-- Rename joined_at -> created_at in project_permissions if needed
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'project_permissions' AND column_name = 'joined_at'
) THEN
    ALTER TABLE project_permissions RENAME COLUMN joined_at TO created_at;
END IF;

-- Drop old role column from project_permissions if exists, replace with level
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'project_permissions' AND column_name = 'role'
) THEN
    -- Add level column first
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'project_permissions' AND column_name = 'level'
    ) THEN
        ALTER TABLE project_permissions
            ADD COLUMN level project_permission_level NOT NULL DEFAULT 'owner'::project_permission_level;
        -- Map old project_role values to permission levels
        UPDATE project_permissions SET level = CASE
            WHEN role::text = 'admin' THEN 'owner'::project_permission_level
            WHEN role::text = 'project_manager' THEN 'write'::project_permission_level
            ELSE 'read'::project_permission_level
        END;
    END IF;
    ALTER TABLE project_permissions DROP COLUMN role;
END IF;

-- admin_api_keys -> user_api_keys
IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'admin_api_keys'
) AND NOT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'user_api_keys'
) THEN
    ALTER TABLE admin_api_keys RENAME TO user_api_keys;
END IF;

-- Rename oidc_discovery_url -> oidc_issuer in app_settings if needed
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'app_settings' AND column_name = 'oidc_discovery_url'
) THEN
    ALTER TABLE app_settings RENAME COLUMN oidc_discovery_url TO oidc_issuer;
END IF;

-- =========================================================================
-- PHASE 4: Drop obsolete columns
-- =========================================================================
RAISE NOTICE 'Phase 4: Dropping obsolete columns...';

-- Drop old UI preference columns from users
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'users' AND column_name = 'show_project_sidebar'
) THEN
    ALTER TABLE users DROP COLUMN show_project_sidebar;
END IF;

IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'users' AND column_name = 'show_project_tabs'
) THEN
    ALTER TABLE users DROP COLUMN show_project_tabs;
END IF;

-- Drop old read_roles/write_roles from projects
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'projects' AND column_name = 'read_roles'
) THEN
    ALTER TABLE projects DROP COLUMN read_roles;
END IF;

IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'projects' AND column_name = 'write_roles'
) THEN
    ALTER TABLE projects DROP COLUMN write_roles;
END IF;

-- Drop members_can_write from projects (replaced by DAC)
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'projects' AND column_name = 'members_can_write'
) THEN
    ALTER TABLE projects DROP COLUMN members_can_write;
END IF;

-- Drop active_guild_id from users (removed post-guild era)
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'users' AND column_name = 'active_guild_id'
) THEN
    ALTER TABLE users
        DROP CONSTRAINT IF EXISTS fk_users_active_guild_id;
    ALTER TABLE users DROP COLUMN active_guild_id;
END IF;

-- Drop old status column from tasks (replaced by task_status_id)
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'tasks' AND column_name = 'status'
) THEN
    -- We will handle task_statuses migration below; for now just note it
    NULL;
END IF;

-- Drop old initiative_role enum column from initiative_members if present
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'initiative_members' AND column_name = 'role'
) THEN
    -- We handle migration to role_id below
    NULL;
END IF;

-- =========================================================================
-- PHASE 5: Create missing tables
-- =========================================================================
RAISE NOTICE 'Phase 5: Creating missing tables...';

-- guilds
CREATE TABLE IF NOT EXISTS guilds (
    id serial NOT NULL,
    name character varying NOT NULL,
    description text,
    icon_base64 text,
    created_by_user_id integer,
    created_at timestamp with time zone DEFAULT timezone('utc', now()) NOT NULL,
    updated_at timestamp with time zone DEFAULT timezone('utc', now()) NOT NULL
);

-- guild_memberships
CREATE TABLE IF NOT EXISTS guild_memberships (
    guild_id integer NOT NULL,
    user_id integer NOT NULL,
    role guild_role DEFAULT 'member'::guild_role NOT NULL,
    joined_at timestamp with time zone DEFAULT timezone('utc', now()) NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    oidc_managed boolean DEFAULT false NOT NULL
);

-- guild_invites
CREATE TABLE IF NOT EXISTS guild_invites (
    id serial NOT NULL,
    code character varying(64) NOT NULL,
    guild_id integer NOT NULL,
    created_by_user_id integer,
    expires_at timestamp with time zone,
    max_uses integer,
    uses integer DEFAULT 0 NOT NULL,
    invitee_email character varying,
    created_at timestamp with time zone DEFAULT timezone('utc', now()) NOT NULL
);

-- guild_settings
CREATE TABLE IF NOT EXISTS guild_settings (
    id serial NOT NULL,
    guild_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    ai_enabled boolean,
    ai_provider character varying(50),
    ai_api_key character varying(2000),
    ai_base_url character varying(1000),
    ai_model character varying(500),
    ai_allow_user_override boolean
);

-- app_settings (may already exist or may have been dropped/recreated)
CREATE TABLE IF NOT EXISTS app_settings (
    id serial NOT NULL,
    oidc_enabled boolean DEFAULT false NOT NULL,
    oidc_issuer character varying,
    oidc_client_id character varying,
    oidc_client_secret character varying,
    oidc_provider_name character varying,
    oidc_scopes json DEFAULT '["openid", "profile", "email"]'::jsonb NOT NULL,
    light_accent_color character varying(20) DEFAULT '#2563eb' NOT NULL,
    dark_accent_color character varying(20) DEFAULT '#60a5fa' NOT NULL,
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
);

-- initiative_roles
CREATE TABLE IF NOT EXISTS initiative_roles (
    id serial NOT NULL,
    initiative_id integer NOT NULL,
    name character varying(100) NOT NULL,
    display_name character varying(100) NOT NULL,
    is_builtin boolean DEFAULT false NOT NULL,
    is_manager boolean DEFAULT false NOT NULL,
    "position" integer DEFAULT 0 NOT NULL
);

-- initiative_role_permissions
CREATE TABLE IF NOT EXISTS initiative_role_permissions (
    initiative_role_id integer NOT NULL,
    permission_key character varying(50) NOT NULL,
    enabled boolean DEFAULT true NOT NULL
);

-- oidc_claim_mappings
CREATE TABLE IF NOT EXISTS oidc_claim_mappings (
    id serial NOT NULL,
    claim_value character varying(500) NOT NULL,
    target_type character varying(20) NOT NULL,
    guild_id integer NOT NULL,
    guild_role character varying(20) DEFAULT 'member' NOT NULL,
    initiative_id integer,
    initiative_role_id integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

-- tags
CREATE TABLE IF NOT EXISTS tags (
    id serial NOT NULL,
    guild_id integer NOT NULL,
    name character varying(100) NOT NULL,
    color character varying(7) DEFAULT '''#6366F1''' NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

-- task_statuses
CREATE TABLE IF NOT EXISTS task_statuses (
    id serial NOT NULL,
    project_id integer NOT NULL,
    name character varying(100) NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    category task_status_category NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    guild_id integer NOT NULL DEFAULT 0
);

-- task_tags
CREATE TABLE IF NOT EXISTS task_tags (
    task_id integer NOT NULL,
    tag_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL
);

-- project_tags
CREATE TABLE IF NOT EXISTS project_tags (
    project_id integer NOT NULL,
    tag_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL
);

-- subtasks
CREATE TABLE IF NOT EXISTS subtasks (
    id serial NOT NULL,
    task_id integer NOT NULL,
    content text NOT NULL,
    is_completed boolean DEFAULT false NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    guild_id integer NOT NULL DEFAULT 0
);

-- documents
CREATE TABLE IF NOT EXISTS documents (
    id serial NOT NULL,
    initiative_id integer NOT NULL,
    title character varying(255) NOT NULL,
    content jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_by_id integer NOT NULL,
    updated_by_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT timezone('utc', now()) NOT NULL,
    updated_at timestamp with time zone DEFAULT timezone('utc', now()) NOT NULL,
    featured_image_url character varying(512),
    is_template boolean NOT NULL DEFAULT false,
    yjs_state bytea,
    yjs_updated_at timestamp with time zone,
    guild_id integer NOT NULL DEFAULT 0,
    document_type document_type DEFAULT 'native'::document_type NOT NULL,
    file_url character varying(512),
    file_content_type character varying(128),
    file_size bigint,
    original_filename character varying(255)
);

-- document_permissions
CREATE TABLE IF NOT EXISTS document_permissions (
    document_id integer NOT NULL,
    user_id integer NOT NULL,
    level document_permission_level NOT NULL,
    created_at timestamp with time zone DEFAULT timezone('utc', now()) NOT NULL,
    guild_id integer NOT NULL DEFAULT 0
);

-- document_role_permissions
CREATE TABLE IF NOT EXISTS document_role_permissions (
    document_id integer NOT NULL,
    initiative_role_id integer NOT NULL,
    guild_id integer NOT NULL,
    level document_permission_level DEFAULT 'read'::document_permission_level NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

-- document_links
CREATE TABLE IF NOT EXISTS document_links (
    source_document_id integer NOT NULL,
    target_document_id integer NOT NULL,
    guild_id integer,
    created_at timestamp with time zone NOT NULL
);

-- document_tags
CREATE TABLE IF NOT EXISTS document_tags (
    document_id integer NOT NULL,
    tag_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL
);

-- project_documents
CREATE TABLE IF NOT EXISTS project_documents (
    project_id integer NOT NULL,
    document_id integer NOT NULL,
    attached_by_id integer,
    attached_at timestamp with time zone DEFAULT timezone('utc', now()) NOT NULL,
    guild_id integer NOT NULL DEFAULT 0
);

-- project_permissions (may already exist from rename)
CREATE TABLE IF NOT EXISTS project_permissions (
    project_id integer NOT NULL,
    user_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    level project_permission_level NOT NULL,
    guild_id integer NOT NULL DEFAULT 0
);

-- project_role_permissions
CREATE TABLE IF NOT EXISTS project_role_permissions (
    project_id integer NOT NULL,
    initiative_role_id integer NOT NULL,
    guild_id integer NOT NULL,
    level project_permission_level DEFAULT 'read'::project_permission_level NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

-- project_favorites
CREATE TABLE IF NOT EXISTS project_favorites (
    user_id integer NOT NULL,
    project_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    guild_id integer NOT NULL DEFAULT 0
);

-- project_orders
CREATE TABLE IF NOT EXISTS project_orders (
    user_id integer NOT NULL,
    project_id integer NOT NULL,
    sort_order double precision DEFAULT 0 NOT NULL,
    guild_id integer NOT NULL DEFAULT 0
);

-- recent_project_views
CREATE TABLE IF NOT EXISTS recent_project_views (
    user_id integer NOT NULL,
    project_id integer NOT NULL,
    last_viewed_at timestamp with time zone NOT NULL,
    guild_id integer NOT NULL DEFAULT 0
);

-- comments
CREATE TABLE IF NOT EXISTS comments (
    id serial NOT NULL,
    content text NOT NULL,
    author_id integer NOT NULL,
    task_id integer,
    document_id integer,
    parent_comment_id integer,
    created_at timestamp with time zone NOT NULL,
    guild_id integer,
    updated_at timestamp with time zone
);

-- notifications
CREATE TABLE IF NOT EXISTS notifications (
    id serial NOT NULL,
    user_id integer NOT NULL,
    type character varying(64) NOT NULL,
    data json DEFAULT '{}'::json NOT NULL,
    read_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT timezone('utc', now()) NOT NULL
);

-- user_tokens
CREATE TABLE IF NOT EXISTS user_tokens (
    id serial NOT NULL,
    user_id integer NOT NULL,
    token character varying(128) NOT NULL,
    purpose user_token_purpose NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    device_name character varying(255)
);

-- user_api_keys (may already exist from rename)
CREATE TABLE IF NOT EXISTS user_api_keys (
    id serial NOT NULL,
    user_id integer NOT NULL,
    name character varying(100) NOT NULL,
    token_prefix character varying(16) NOT NULL,
    token_hash character varying(128) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone NOT NULL,
    last_used_at timestamp with time zone,
    expires_at timestamp with time zone
);

-- push_tokens
CREATE TABLE IF NOT EXISTS push_tokens (
    id serial NOT NULL,
    user_id integer NOT NULL,
    device_token_id integer,
    push_token character varying(512) NOT NULL,
    platform character varying(32) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    last_used_at timestamp with time zone
);

-- task_assignment_digest_items
CREATE TABLE IF NOT EXISTS task_assignment_digest_items (
    id serial NOT NULL,
    user_id integer NOT NULL,
    task_id integer NOT NULL,
    project_id integer NOT NULL,
    task_title character varying(255) NOT NULL,
    project_name character varying(255) NOT NULL,
    assigned_by_name character varying(255) NOT NULL,
    assigned_by_id integer,
    created_at timestamp with time zone NOT NULL,
    processed_at timestamp with time zone
);

-- =========================================================================
-- PHASE 6: Add missing columns to existing tables
-- =========================================================================
RAISE NOTICE 'Phase 6: Adding missing columns...';

-- ----- users -----
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified boolean DEFAULT true NOT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS timezone character varying(64) DEFAULT 'UTC' NOT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS overdue_notification_time character varying(5) DEFAULT '21:00' NOT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_overdue_notification_at timestamp with time zone;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_task_assignment_digest_at timestamp with time zone;
ALTER TABLE users ADD COLUMN IF NOT EXISTS week_starts_on integer DEFAULT 0 NOT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_enabled boolean;
ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_provider character varying(50);
ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_api_key character varying(2000);
ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_base_url character varying(1000);
ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_model character varying(500);
-- Widen AI columns in case they were created at smaller sizes (migration 0021 -> 0022)
ALTER TABLE users ALTER COLUMN ai_api_key TYPE character varying(2000);
ALTER TABLE users ALTER COLUMN ai_base_url TYPE character varying(1000);
ALTER TABLE users ALTER COLUMN ai_model TYPE character varying(500);
ALTER TABLE users ADD COLUMN IF NOT EXISTS color_theme character varying(50) DEFAULT 'kobold' NOT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS oidc_refresh_token_encrypted text;
ALTER TABLE users ADD COLUMN IF NOT EXISTS oidc_last_synced_at timestamp with time zone;
ALTER TABLE users ADD COLUMN IF NOT EXISTS oidc_sub character varying(255);
ALTER TABLE users ADD COLUMN IF NOT EXISTS locale character varying(10) DEFAULT 'en' NOT NULL;

-- Notification preference columns (may exist as notify_* or email_*)
-- Handle the rename: notify_* -> email_*
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'users' AND column_name = 'notify_initiative_addition'
) THEN
    ALTER TABLE users RENAME COLUMN notify_initiative_addition TO email_initiative_addition;
END IF;
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'users' AND column_name = 'notify_task_assignment'
) THEN
    ALTER TABLE users RENAME COLUMN notify_task_assignment TO email_task_assignment;
END IF;
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'users' AND column_name = 'notify_project_added'
) THEN
    ALTER TABLE users RENAME COLUMN notify_project_added TO email_project_added;
END IF;
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'users' AND column_name = 'notify_overdue_tasks'
) THEN
    ALTER TABLE users RENAME COLUMN notify_overdue_tasks TO email_overdue_tasks;
END IF;
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'users' AND column_name = 'notify_mentions'
) THEN
    ALTER TABLE users RENAME COLUMN notify_mentions TO email_mentions;
END IF;

-- Add email_* columns if they still don't exist (fresh pre-notification schema)
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_initiative_addition boolean DEFAULT true NOT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_task_assignment boolean DEFAULT true NOT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_project_added boolean DEFAULT true NOT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_overdue_tasks boolean DEFAULT true NOT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_mentions boolean DEFAULT true NOT NULL;

-- Push notification columns
ALTER TABLE users ADD COLUMN IF NOT EXISTS push_initiative_addition boolean DEFAULT true NOT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS push_task_assignment boolean DEFAULT true NOT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS push_project_added boolean DEFAULT true NOT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS push_overdue_tasks boolean DEFAULT true NOT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS push_mentions boolean DEFAULT true NOT NULL;

-- ----- initiatives -----
ALTER TABLE initiatives ADD COLUMN IF NOT EXISTS color character varying(32);
ALTER TABLE initiatives ADD COLUMN IF NOT EXISTS is_default boolean NOT NULL DEFAULT false;
ALTER TABLE initiatives ADD COLUMN IF NOT EXISTS guild_id integer;

-- ----- projects -----
ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_archived boolean NOT NULL DEFAULT false;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_template boolean NOT NULL DEFAULT false;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS archived_at timestamp with time zone;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS pinned_at timestamp with time zone;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS icon character varying(8);
ALTER TABLE projects ADD COLUMN IF NOT EXISTS guild_id integer;

-- Make initiative_id NOT NULL on projects if it's nullable
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'projects' AND column_name = 'initiative_id' AND is_nullable = 'YES'
) THEN
    -- Handled after guild bootstrap when we ensure a default initiative
    NULL;
END IF;

-- ----- tasks -----
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS recurrence json;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS recurrence_occurrence_count integer NOT NULL DEFAULT 0;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS start_date timestamp with time zone;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS recurrence_strategy character varying(20) NOT NULL DEFAULT 'fixed';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS is_archived boolean DEFAULT false NOT NULL;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS task_status_id integer;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS guild_id integer;

-- ----- task_assignees -----
ALTER TABLE task_assignees ADD COLUMN IF NOT EXISTS guild_id integer;

-- ----- subtasks -----
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS guild_id integer;

-- ----- comments -----
ALTER TABLE comments ADD COLUMN IF NOT EXISTS guild_id integer;
ALTER TABLE comments ADD COLUMN IF NOT EXISTS updated_at timestamp with time zone;
ALTER TABLE comments ADD COLUMN IF NOT EXISTS document_id integer;

-- ----- documents -----
-- Convert content column from json to jsonb if needed (old schema used json)
DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'documents' AND column_name = 'content'
        AND data_type = 'json'
    ) THEN
        ALTER TABLE documents ALTER COLUMN content TYPE jsonb USING content::jsonb;
        ALTER TABLE documents ALTER COLUMN content SET DEFAULT '{}'::jsonb;
    END IF;
END $$;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS featured_image_url character varying(512);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_template boolean NOT NULL DEFAULT false;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS yjs_state bytea;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS yjs_updated_at timestamp with time zone;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS guild_id integer;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS document_type document_type DEFAULT 'native'::document_type NOT NULL;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_url character varying(512);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_content_type character varying(128);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_size bigint;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS original_filename character varying(255);

-- ----- document_permissions -----
ALTER TABLE document_permissions ADD COLUMN IF NOT EXISTS guild_id integer;

-- ----- project_permissions -----
ALTER TABLE project_permissions ADD COLUMN IF NOT EXISTS guild_id integer;

-- ----- project_favorites -----
ALTER TABLE project_favorites ADD COLUMN IF NOT EXISTS guild_id integer;

-- ----- project_orders -----
ALTER TABLE project_orders ADD COLUMN IF NOT EXISTS guild_id integer;

-- ----- recent_project_views -----
ALTER TABLE recent_project_views ADD COLUMN IF NOT EXISTS guild_id integer;

-- ----- project_documents -----
ALTER TABLE project_documents ADD COLUMN IF NOT EXISTS guild_id integer;

-- ----- initiative_members -----
ALTER TABLE initiative_members ADD COLUMN IF NOT EXISTS guild_id integer;
ALTER TABLE initiative_members ADD COLUMN IF NOT EXISTS role_id integer;
ALTER TABLE initiative_members ADD COLUMN IF NOT EXISTS oidc_managed boolean DEFAULT false NOT NULL;

-- ----- guild_memberships -----
ALTER TABLE guild_memberships ADD COLUMN IF NOT EXISTS "position" integer DEFAULT 0 NOT NULL;
ALTER TABLE guild_memberships ADD COLUMN IF NOT EXISTS oidc_managed boolean DEFAULT false NOT NULL;

-- ----- task_statuses -----
ALTER TABLE task_statuses ADD COLUMN IF NOT EXISTS guild_id integer;

-- ----- user_tokens -----
ALTER TABLE user_tokens ADD COLUMN IF NOT EXISTS device_name character varying(255);

-- ----- app_settings (add missing columns) -----
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS role_labels json
    DEFAULT '{"admin": "Admin", "member": "Member", "project_manager": "Project manager"}'::jsonb NOT NULL;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS smtp_host character varying(255);
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS smtp_port integer;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS smtp_secure boolean DEFAULT false NOT NULL;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS smtp_reject_unauthorized boolean DEFAULT true NOT NULL;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS smtp_username character varying(255);
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS smtp_password character varying(255);
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS smtp_from_address character varying(255);
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS smtp_test_recipient character varying(255);
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS ai_enabled boolean DEFAULT false NOT NULL;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS ai_provider character varying(50);
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS ai_api_key character varying(2000);
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS ai_base_url character varying(1000);
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS ai_model character varying(500);
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS ai_allow_guild_override boolean DEFAULT true NOT NULL;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS ai_allow_user_override boolean DEFAULT true NOT NULL;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS oidc_role_claim_path character varying(500);
-- Widen AI columns in case they were created at smaller sizes
ALTER TABLE app_settings ALTER COLUMN ai_api_key TYPE character varying(2000);
ALTER TABLE app_settings ALTER COLUMN ai_base_url TYPE character varying(1000);
ALTER TABLE app_settings ALTER COLUMN ai_model TYPE character varying(500);

-- ----- guild_settings (strip old columns that moved to app_settings) -----
-- These columns were migrated from guild_settings to app_settings in
-- 20240805_0003. If they still exist on guild_settings, drop them.
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'guild_settings' AND column_name = 'auto_approved_domains'
) THEN
    ALTER TABLE guild_settings DROP COLUMN auto_approved_domains;
END IF;
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'guild_settings' AND column_name = 'oidc_enabled'
) THEN
    ALTER TABLE guild_settings DROP COLUMN oidc_enabled;
END IF;
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'guild_settings' AND column_name = 'oidc_discovery_url'
) THEN
    ALTER TABLE guild_settings DROP COLUMN oidc_discovery_url;
END IF;
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'guild_settings' AND column_name = 'oidc_client_id'
) THEN
    ALTER TABLE guild_settings DROP COLUMN oidc_client_id;
END IF;
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'guild_settings' AND column_name = 'oidc_client_secret'
) THEN
    ALTER TABLE guild_settings DROP COLUMN oidc_client_secret;
END IF;
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'guild_settings' AND column_name = 'oidc_provider_name'
) THEN
    ALTER TABLE guild_settings DROP COLUMN oidc_provider_name;
END IF;
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'guild_settings' AND column_name = 'oidc_scopes'
) THEN
    ALTER TABLE guild_settings DROP COLUMN oidc_scopes;
END IF;
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'guild_settings' AND column_name = 'light_accent_color'
) THEN
    ALTER TABLE guild_settings DROP COLUMN light_accent_color;
END IF;
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'guild_settings' AND column_name = 'dark_accent_color'
) THEN
    ALTER TABLE guild_settings DROP COLUMN dark_accent_color;
END IF;
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'guild_settings' AND column_name = 'role_labels'
) THEN
    ALTER TABLE guild_settings DROP COLUMN role_labels;
END IF;
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'guild_settings' AND column_name = 'smtp_host'
) THEN
    ALTER TABLE guild_settings DROP COLUMN smtp_host;
END IF;
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'guild_settings' AND column_name = 'smtp_port'
) THEN
    ALTER TABLE guild_settings DROP COLUMN smtp_port;
END IF;
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'guild_settings' AND column_name = 'smtp_secure'
) THEN
    ALTER TABLE guild_settings DROP COLUMN smtp_secure;
END IF;
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'guild_settings' AND column_name = 'smtp_reject_unauthorized'
) THEN
    ALTER TABLE guild_settings DROP COLUMN smtp_reject_unauthorized;
END IF;
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'guild_settings' AND column_name = 'smtp_username'
) THEN
    ALTER TABLE guild_settings DROP COLUMN smtp_username;
END IF;
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'guild_settings' AND column_name = 'smtp_password'
) THEN
    ALTER TABLE guild_settings DROP COLUMN smtp_password;
END IF;
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'guild_settings' AND column_name = 'smtp_from_address'
) THEN
    ALTER TABLE guild_settings DROP COLUMN smtp_from_address;
END IF;
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'guild_settings' AND column_name = 'smtp_test_recipient'
) THEN
    ALTER TABLE guild_settings DROP COLUMN smtp_test_recipient;
END IF;

-- Add guild_settings columns that may be missing
ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS created_at timestamp with time zone NOT NULL DEFAULT timezone('utc', now());
ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS updated_at timestamp with time zone NOT NULL DEFAULT timezone('utc', now());
ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS ai_enabled boolean;
ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS ai_provider character varying(50);
ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS ai_api_key character varying(2000);
ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS ai_base_url character varying(1000);
ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS ai_model character varying(500);
ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS ai_allow_user_override boolean;
-- Widen AI columns in case they were created at smaller sizes
ALTER TABLE guild_settings ALTER COLUMN ai_api_key TYPE character varying(2000);
ALTER TABLE guild_settings ALTER COLUMN ai_base_url TYPE character varying(1000);
ALTER TABLE guild_settings ALTER COLUMN ai_model TYPE character varying(500);

-- =========================================================================
-- PHASE 7: Guild bootstrap -- create default guild if none exist
-- =========================================================================
RAISE NOTICE 'Phase 7: Guild bootstrap...';

IF NOT EXISTS (SELECT 1 FROM guilds LIMIT 1) THEN
    RAISE NOTICE '  No guilds found. Creating default guild and migrating users...';

    INSERT INTO guilds (name, description, created_at, updated_at)
    VALUES ('Primary Guild', 'Migrated default guild', timezone('utc', now()), timezone('utc', now()))
    RETURNING id INTO _default_guild_id;

    -- Migrate all existing users to the new guild
    INSERT INTO guild_memberships (guild_id, user_id, role, joined_at)
    SELECT _default_guild_id, u.id,
           CASE WHEN u.role::text = 'admin' THEN 'admin'::guild_role
                ELSE 'member'::guild_role END,
           timezone('utc', now())
    FROM users u
    WHERE NOT EXISTS (
        SELECT 1 FROM guild_memberships gm
        WHERE gm.guild_id = _default_guild_id AND gm.user_id = u.id
    );

    -- Create guild_settings for the new guild
    IF NOT EXISTS (SELECT 1 FROM guild_settings WHERE guild_id = _default_guild_id) THEN
        INSERT INTO guild_settings (guild_id, created_at, updated_at)
        VALUES (_default_guild_id, timezone('utc', now()), timezone('utc', now()));
    END IF;
ELSE
    SELECT id INTO _default_guild_id FROM guilds ORDER BY id LIMIT 1;
    RAISE NOTICE '  Guilds already exist. Using guild % as default for backfill.', _default_guild_id;
END IF;

-- =========================================================================
-- PHASE 8: Backfill guild_id on initiatives and create default initiative
-- =========================================================================
RAISE NOTICE 'Phase 8: Backfilling initiatives...';

-- Set guild_id on initiatives that don't have it
UPDATE initiatives SET guild_id = _default_guild_id WHERE guild_id IS NULL;

-- Ensure a default initiative exists
IF NOT EXISTS (SELECT 1 FROM initiatives WHERE is_default = true LIMIT 1) THEN
    -- Try to mark an existing initiative as default
    UPDATE initiatives SET is_default = true
    WHERE id = (SELECT id FROM initiatives ORDER BY id LIMIT 1)
    AND NOT EXISTS (SELECT 1 FROM initiatives WHERE is_default = true);

    -- If no initiatives at all, create one
    IF NOT EXISTS (SELECT 1 FROM initiatives LIMIT 1) THEN
        INSERT INTO initiatives (name, description, color, guild_id, is_default, created_at, updated_at)
        VALUES ('Default Initiative', 'Automatically created default initiative', '#2563eb',
                _default_guild_id, true, timezone('utc', now()), timezone('utc', now()));
    END IF;
END IF;

-- Make guild_id NOT NULL on initiatives
ALTER TABLE initiatives ALTER COLUMN guild_id SET NOT NULL;

-- Ensure all projects have an initiative_id
SELECT id INTO _default_initiative_id FROM initiatives WHERE is_default = true AND guild_id = _default_guild_id LIMIT 1;
IF _default_initiative_id IS NULL THEN
    SELECT id INTO _default_initiative_id FROM initiatives ORDER BY id LIMIT 1;
END IF;

IF _default_initiative_id IS NOT NULL THEN
    UPDATE projects SET initiative_id = _default_initiative_id
    WHERE initiative_id IS NULL;
END IF;

-- Make initiative_id NOT NULL on projects
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'projects' AND column_name = 'initiative_id' AND is_nullable = 'YES'
) THEN
    ALTER TABLE projects ALTER COLUMN initiative_id SET NOT NULL;
END IF;

-- =========================================================================
-- PHASE 9: Seed initiative_roles for all initiatives that lack them
-- =========================================================================
RAISE NOTICE 'Phase 9: Seeding initiative roles...';

-- PM roles
INSERT INTO initiative_roles (initiative_id, name, display_name, is_builtin, is_manager, "position")
SELECT i.id, 'project_manager', 'Project Manager', true, true, 0
FROM initiatives i
WHERE NOT EXISTS (
    SELECT 1 FROM initiative_roles ir
    WHERE ir.initiative_id = i.id AND ir.name = 'project_manager'
);

-- Member roles
INSERT INTO initiative_roles (initiative_id, name, display_name, is_builtin, is_manager, "position")
SELECT i.id, 'member', 'Member', true, false, 1
FROM initiatives i
WHERE NOT EXISTS (
    SELECT 1 FROM initiative_roles ir
    WHERE ir.initiative_id = i.id AND ir.name = 'member'
);

-- Seed permissions for new roles that lack them
INSERT INTO initiative_role_permissions (initiative_role_id, permission_key, enabled)
SELECT ir.id, perm.key, true
FROM initiative_roles ir
CROSS JOIN (VALUES ('docs_enabled'), ('projects_enabled'), ('create_docs'), ('create_projects')) AS perm(key)
WHERE ir.name = 'project_manager'
AND NOT EXISTS (
    SELECT 1 FROM initiative_role_permissions irp
    WHERE irp.initiative_role_id = ir.id AND irp.permission_key = perm.key
);

INSERT INTO initiative_role_permissions (initiative_role_id, permission_key, enabled)
SELECT ir.id, perm.key, perm.enabled
FROM initiative_roles ir
CROSS JOIN (VALUES
    ('docs_enabled', true),
    ('projects_enabled', true),
    ('create_docs', false),
    ('create_projects', false)
) AS perm(key, enabled)
WHERE ir.name = 'member'
AND NOT EXISTS (
    SELECT 1 FROM initiative_role_permissions irp
    WHERE irp.initiative_role_id = ir.id AND irp.permission_key = perm.key
);

-- =========================================================================
-- PHASE 10: Migrate initiative_members role enum -> role_id FK
-- =========================================================================
RAISE NOTICE 'Phase 10: Migrating initiative member roles...';

-- If initiative_members still has the old 'role' enum column, migrate to role_id
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'initiative_members' AND column_name = 'role'
) THEN
    -- Map old role to new role_id
    UPDATE initiative_members im
    SET role_id = ir.id
    FROM initiative_roles ir
    WHERE ir.initiative_id = im.initiative_id
    AND ir.name = im.role::text
    AND im.role_id IS NULL;

    -- For any remaining unmapped, set to 'member' role
    UPDATE initiative_members im
    SET role_id = ir.id
    FROM initiative_roles ir
    WHERE ir.initiative_id = im.initiative_id
    AND ir.name = 'member'
    AND im.role_id IS NULL;

    ALTER TABLE initiative_members DROP COLUMN role;
END IF;

-- Drop the old initiative_role enum type if it exists
DROP TYPE IF EXISTS initiative_role;

-- =========================================================================
-- PHASE 11: Migrate tasks from old status enum to task_status_id
-- =========================================================================
RAISE NOTICE 'Phase 11: Migrating task statuses...';

-- If tasks still has the old 'status' column, migrate to task_status_id
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'tasks' AND column_name = 'status'
) THEN
    -- Create default task_statuses for each project that lacks them
    INSERT INTO task_statuses (project_id, name, "position", category, is_default, guild_id)
    SELECT p.id, 'Backlog', 0, 'backlog'::task_status_category, true, COALESCE(p.guild_id, _default_guild_id)
    FROM projects p
    WHERE NOT EXISTS (
        SELECT 1 FROM task_statuses ts WHERE ts.project_id = p.id AND ts.category = 'backlog'
    );

    INSERT INTO task_statuses (project_id, name, "position", category, is_default, guild_id)
    SELECT p.id, 'In Progress', 1, 'in_progress'::task_status_category, false, COALESCE(p.guild_id, _default_guild_id)
    FROM projects p
    WHERE NOT EXISTS (
        SELECT 1 FROM task_statuses ts WHERE ts.project_id = p.id AND ts.category = 'in_progress'
    );

    INSERT INTO task_statuses (project_id, name, "position", category, is_default, guild_id)
    SELECT p.id, 'Blocked', 2, 'todo'::task_status_category, false, COALESCE(p.guild_id, _default_guild_id)
    FROM projects p
    WHERE NOT EXISTS (
        SELECT 1 FROM task_statuses ts WHERE ts.project_id = p.id AND ts.category = 'todo'
    );

    INSERT INTO task_statuses (project_id, name, "position", category, is_default, guild_id)
    SELECT p.id, 'Done', 3, 'done'::task_status_category, false, COALESCE(p.guild_id, _default_guild_id)
    FROM projects p
    WHERE NOT EXISTS (
        SELECT 1 FROM task_statuses ts WHERE ts.project_id = p.id AND ts.category = 'done'
    );

    -- Map legacy status values to task_status_id
    UPDATE tasks t
    SET task_status_id = ts.id
    FROM task_statuses ts
    WHERE ts.project_id = t.project_id
    AND task_status_id IS NULL
    AND (
        (t.status::text = 'backlog' AND ts.category = 'backlog') OR
        (t.status::text = 'in_progress' AND ts.category = 'in_progress') OR
        (t.status::text = 'blocked' AND ts.category = 'todo') OR
        (t.status::text = 'done' AND ts.category = 'done')
    );

    -- Catch any remaining unmapped tasks
    UPDATE tasks t
    SET task_status_id = (
        SELECT id FROM task_statuses ts2
        WHERE ts2.project_id = t.project_id
        ORDER BY ts2."position", ts2.id LIMIT 1
    )
    WHERE t.task_status_id IS NULL;

    ALTER TABLE tasks DROP COLUMN status;
    DROP TYPE IF EXISTS task_status;
END IF;

-- Make task_status_id NOT NULL
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'tasks' AND column_name = 'task_status_id' AND is_nullable = 'YES'
) THEN
    ALTER TABLE tasks ALTER COLUMN task_status_id SET NOT NULL;
END IF;

-- =========================================================================
-- PHASE 12: Backfill guild_id on all tables from their parents
-- =========================================================================
RAISE NOTICE 'Phase 12: Backfilling guild_id...';

-- Tier 2: from initiatives
UPDATE projects p SET guild_id = i.guild_id
FROM initiatives i WHERE p.initiative_id = i.id AND p.guild_id IS NULL;

UPDATE documents d SET guild_id = i.guild_id
FROM initiatives i WHERE d.initiative_id = i.id AND d.guild_id IS NULL;

UPDATE initiative_members im SET guild_id = i.guild_id
FROM initiatives i WHERE im.initiative_id = i.id AND im.guild_id IS NULL;

-- Tier 3: from projects
UPDATE tasks t SET guild_id = p.guild_id
FROM projects p WHERE t.project_id = p.id AND t.guild_id IS NULL;

UPDATE task_statuses ts SET guild_id = p.guild_id
FROM projects p WHERE ts.project_id = p.id AND ts.guild_id IS NULL;

UPDATE project_permissions pp SET guild_id = p.guild_id
FROM projects p WHERE pp.project_id = p.id AND pp.guild_id IS NULL;

UPDATE project_favorites pf SET guild_id = p.guild_id
FROM projects p WHERE pf.project_id = p.id AND pf.guild_id IS NULL;

UPDATE project_orders po SET guild_id = p.guild_id
FROM projects p WHERE po.project_id = p.id AND po.guild_id IS NULL;

UPDATE recent_project_views rpv SET guild_id = p.guild_id
FROM projects p WHERE rpv.project_id = p.id AND rpv.guild_id IS NULL;

UPDATE project_documents pd SET guild_id = p.guild_id
FROM projects p WHERE pd.project_id = p.id AND pd.guild_id IS NULL;

-- Tier 4: from tasks
UPDATE subtasks s SET guild_id = t.guild_id
FROM tasks t WHERE s.task_id = t.id AND s.guild_id IS NULL;

UPDATE task_assignees ta SET guild_id = t.guild_id
FROM tasks t WHERE ta.task_id = t.id AND ta.guild_id IS NULL;

-- Comments: polymorphic (task or document)
UPDATE comments c SET guild_id = t.guild_id
FROM tasks t WHERE c.task_id = t.id AND c.guild_id IS NULL;

UPDATE comments c SET guild_id = d.guild_id
FROM documents d WHERE c.document_id = d.id AND c.guild_id IS NULL;

-- Document permissions
UPDATE document_permissions dp SET guild_id = d.guild_id
FROM documents d WHERE dp.document_id = d.id AND dp.guild_id IS NULL;

-- =========================================================================
-- PHASE 13: Make guild_id NOT NULL where required
-- =========================================================================
RAISE NOTICE 'Phase 13: Setting guild_id NOT NULL constraints...';

-- For all these tables, guild_id must be NOT NULL in the target schema
-- Set remaining NULLs to the default guild as a safety net
UPDATE projects SET guild_id = _default_guild_id WHERE guild_id IS NULL;
UPDATE documents SET guild_id = _default_guild_id WHERE guild_id IS NULL;
UPDATE initiative_members SET guild_id = _default_guild_id WHERE guild_id IS NULL;
UPDATE tasks SET guild_id = _default_guild_id WHERE guild_id IS NULL;
UPDATE task_statuses SET guild_id = _default_guild_id WHERE guild_id IS NULL;
UPDATE subtasks SET guild_id = _default_guild_id WHERE guild_id IS NULL;
UPDATE task_assignees SET guild_id = _default_guild_id WHERE guild_id IS NULL;
UPDATE project_permissions SET guild_id = _default_guild_id WHERE guild_id IS NULL;
UPDATE project_favorites SET guild_id = _default_guild_id WHERE guild_id IS NULL;
UPDATE project_orders SET guild_id = _default_guild_id WHERE guild_id IS NULL;
UPDATE recent_project_views SET guild_id = _default_guild_id WHERE guild_id IS NULL;
UPDATE project_documents SET guild_id = _default_guild_id WHERE guild_id IS NULL;
UPDATE document_permissions SET guild_id = _default_guild_id WHERE guild_id IS NULL;

ALTER TABLE projects ALTER COLUMN guild_id SET NOT NULL;
ALTER TABLE documents ALTER COLUMN guild_id SET NOT NULL;
ALTER TABLE initiative_members ALTER COLUMN guild_id SET NOT NULL;
ALTER TABLE tasks ALTER COLUMN guild_id SET NOT NULL;
ALTER TABLE task_statuses ALTER COLUMN guild_id SET NOT NULL;
ALTER TABLE subtasks ALTER COLUMN guild_id SET NOT NULL;
ALTER TABLE task_assignees ALTER COLUMN guild_id SET NOT NULL;
ALTER TABLE project_permissions ALTER COLUMN guild_id SET NOT NULL;
ALTER TABLE project_favorites ALTER COLUMN guild_id SET NOT NULL;
ALTER TABLE project_orders ALTER COLUMN guild_id SET NOT NULL;
ALTER TABLE recent_project_views ALTER COLUMN guild_id SET NOT NULL;
ALTER TABLE project_documents ALTER COLUMN guild_id SET NOT NULL;
ALTER TABLE document_permissions ALTER COLUMN guild_id SET NOT NULL;

-- recurrence_strategy NOT NULL
ALTER TABLE tasks ALTER COLUMN recurrence_strategy SET NOT NULL;
-- recurrence_occurrence_count NOT NULL
ALTER TABLE tasks ALTER COLUMN recurrence_occurrence_count SET NOT NULL;
-- is_archived on tasks NOT NULL
ALTER TABLE tasks ALTER COLUMN is_archived SET NOT NULL;

-- =========================================================================
-- PHASE 14: Ensure app_settings row exists (singleton)
-- =========================================================================
RAISE NOTICE 'Phase 14: Ensuring app_settings singleton...';

IF NOT EXISTS (SELECT 1 FROM app_settings LIMIT 1) THEN
    INSERT INTO app_settings (id) VALUES (1);
END IF;

-- =========================================================================
-- PHASE 15: Sequences -- create and wire up
-- =========================================================================
RAISE NOTICE 'Phase 15: Ensuring sequences...';

-- Create sequences if missing and wire up defaults
-- users_id_seq
IF NOT EXISTS (SELECT 1 FROM pg_sequences WHERE schemaname = 'public' AND sequencename = 'users_id_seq') THEN
    CREATE SEQUENCE users_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
    ALTER SEQUENCE users_id_seq OWNED BY users.id;
END IF;
ALTER TABLE ONLY users ALTER COLUMN id SET DEFAULT nextval('users_id_seq'::regclass);

-- guilds_id_seq
IF NOT EXISTS (SELECT 1 FROM pg_sequences WHERE schemaname = 'public' AND sequencename = 'guilds_id_seq') THEN
    CREATE SEQUENCE guilds_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
    ALTER SEQUENCE guilds_id_seq OWNED BY guilds.id;
END IF;
ALTER TABLE ONLY guilds ALTER COLUMN id SET DEFAULT nextval('guilds_id_seq'::regclass);

-- guild_invites_id_seq
IF NOT EXISTS (SELECT 1 FROM pg_sequences WHERE schemaname = 'public' AND sequencename = 'guild_invites_id_seq') THEN
    CREATE SEQUENCE guild_invites_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
    ALTER SEQUENCE guild_invites_id_seq OWNED BY guild_invites.id;
END IF;
ALTER TABLE ONLY guild_invites ALTER COLUMN id SET DEFAULT nextval('guild_invites_id_seq'::regclass);

-- guild_settings_id_seq
IF NOT EXISTS (SELECT 1 FROM pg_sequences WHERE schemaname = 'public' AND sequencename = 'guild_settings_id_seq') THEN
    CREATE SEQUENCE guild_settings_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
    ALTER SEQUENCE guild_settings_id_seq OWNED BY guild_settings.id;
END IF;
ALTER TABLE ONLY guild_settings ALTER COLUMN id SET DEFAULT nextval('guild_settings_id_seq'::regclass);

-- app_settings_id_seq
IF NOT EXISTS (SELECT 1 FROM pg_sequences WHERE schemaname = 'public' AND sequencename = 'app_settings_id_seq') THEN
    CREATE SEQUENCE app_settings_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
    ALTER SEQUENCE app_settings_id_seq OWNED BY app_settings.id;
END IF;
ALTER TABLE ONLY app_settings ALTER COLUMN id SET DEFAULT nextval('app_settings_id_seq'::regclass);

-- teams_id_seq (legacy name, owned by initiatives.id)
IF NOT EXISTS (SELECT 1 FROM pg_sequences WHERE schemaname = 'public' AND sequencename = 'teams_id_seq') THEN
    CREATE SEQUENCE teams_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
    ALTER SEQUENCE teams_id_seq OWNED BY initiatives.id;
END IF;
ALTER TABLE ONLY initiatives ALTER COLUMN id SET DEFAULT nextval('teams_id_seq'::regclass);

-- initiative_roles_id_seq
IF NOT EXISTS (SELECT 1 FROM pg_sequences WHERE schemaname = 'public' AND sequencename = 'initiative_roles_id_seq') THEN
    CREATE SEQUENCE initiative_roles_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
    ALTER SEQUENCE initiative_roles_id_seq OWNED BY initiative_roles.id;
END IF;
ALTER TABLE ONLY initiative_roles ALTER COLUMN id SET DEFAULT nextval('initiative_roles_id_seq'::regclass);

-- oidc_claim_mappings_id_seq
IF NOT EXISTS (SELECT 1 FROM pg_sequences WHERE schemaname = 'public' AND sequencename = 'oidc_claim_mappings_id_seq') THEN
    CREATE SEQUENCE oidc_claim_mappings_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
    ALTER SEQUENCE oidc_claim_mappings_id_seq OWNED BY oidc_claim_mappings.id;
END IF;
ALTER TABLE ONLY oidc_claim_mappings ALTER COLUMN id SET DEFAULT nextval('oidc_claim_mappings_id_seq'::regclass);

-- projects_id_seq
IF NOT EXISTS (SELECT 1 FROM pg_sequences WHERE schemaname = 'public' AND sequencename = 'projects_id_seq') THEN
    CREATE SEQUENCE projects_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
    ALTER SEQUENCE projects_id_seq OWNED BY projects.id;
END IF;
ALTER TABLE ONLY projects ALTER COLUMN id SET DEFAULT nextval('projects_id_seq'::regclass);

-- tags_id_seq
IF NOT EXISTS (SELECT 1 FROM pg_sequences WHERE schemaname = 'public' AND sequencename = 'tags_id_seq') THEN
    CREATE SEQUENCE tags_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
    ALTER SEQUENCE tags_id_seq OWNED BY tags.id;
END IF;
ALTER TABLE ONLY tags ALTER COLUMN id SET DEFAULT nextval('tags_id_seq'::regclass);

-- task_statuses_id_seq
IF NOT EXISTS (SELECT 1 FROM pg_sequences WHERE schemaname = 'public' AND sequencename = 'task_statuses_id_seq') THEN
    CREATE SEQUENCE task_statuses_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
    ALTER SEQUENCE task_statuses_id_seq OWNED BY task_statuses.id;
END IF;
ALTER TABLE ONLY task_statuses ALTER COLUMN id SET DEFAULT nextval('task_statuses_id_seq'::regclass);

-- tasks_id_seq
IF NOT EXISTS (SELECT 1 FROM pg_sequences WHERE schemaname = 'public' AND sequencename = 'tasks_id_seq') THEN
    CREATE SEQUENCE tasks_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
    ALTER SEQUENCE tasks_id_seq OWNED BY tasks.id;
END IF;
ALTER TABLE ONLY tasks ALTER COLUMN id SET DEFAULT nextval('tasks_id_seq'::regclass);

-- subtasks_id_seq
IF NOT EXISTS (SELECT 1 FROM pg_sequences WHERE schemaname = 'public' AND sequencename = 'subtasks_id_seq') THEN
    CREATE SEQUENCE subtasks_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
    ALTER SEQUENCE subtasks_id_seq OWNED BY subtasks.id;
END IF;
ALTER TABLE ONLY subtasks ALTER COLUMN id SET DEFAULT nextval('subtasks_id_seq'::regclass);

-- documents_id_seq
IF NOT EXISTS (SELECT 1 FROM pg_sequences WHERE schemaname = 'public' AND sequencename = 'documents_id_seq') THEN
    CREATE SEQUENCE documents_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
    ALTER SEQUENCE documents_id_seq OWNED BY documents.id;
END IF;
ALTER TABLE ONLY documents ALTER COLUMN id SET DEFAULT nextval('documents_id_seq'::regclass);

-- comments_id_seq
IF NOT EXISTS (SELECT 1 FROM pg_sequences WHERE schemaname = 'public' AND sequencename = 'comments_id_seq') THEN
    CREATE SEQUENCE comments_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
    ALTER SEQUENCE comments_id_seq OWNED BY comments.id;
END IF;
ALTER TABLE ONLY comments ALTER COLUMN id SET DEFAULT nextval('comments_id_seq'::regclass);

-- notifications_id_seq
IF NOT EXISTS (SELECT 1 FROM pg_sequences WHERE schemaname = 'public' AND sequencename = 'notifications_id_seq') THEN
    CREATE SEQUENCE notifications_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
    ALTER SEQUENCE notifications_id_seq OWNED BY notifications.id;
END IF;
ALTER TABLE ONLY notifications ALTER COLUMN id SET DEFAULT nextval('notifications_id_seq'::regclass);

-- user_tokens_id_seq
IF NOT EXISTS (SELECT 1 FROM pg_sequences WHERE schemaname = 'public' AND sequencename = 'user_tokens_id_seq') THEN
    CREATE SEQUENCE user_tokens_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
    ALTER SEQUENCE user_tokens_id_seq OWNED BY user_tokens.id;
END IF;
ALTER TABLE ONLY user_tokens ALTER COLUMN id SET DEFAULT nextval('user_tokens_id_seq'::regclass);

-- admin_api_keys_id_seq (legacy name, owned by user_api_keys.id)
IF NOT EXISTS (SELECT 1 FROM pg_sequences WHERE schemaname = 'public' AND sequencename = 'admin_api_keys_id_seq') THEN
    CREATE SEQUENCE admin_api_keys_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
    ALTER SEQUENCE admin_api_keys_id_seq OWNED BY user_api_keys.id;
END IF;
ALTER TABLE ONLY user_api_keys ALTER COLUMN id SET DEFAULT nextval('admin_api_keys_id_seq'::regclass);

-- push_tokens_id_seq
IF NOT EXISTS (SELECT 1 FROM pg_sequences WHERE schemaname = 'public' AND sequencename = 'push_tokens_id_seq') THEN
    CREATE SEQUENCE push_tokens_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
    ALTER SEQUENCE push_tokens_id_seq OWNED BY push_tokens.id;
END IF;
ALTER TABLE ONLY push_tokens ALTER COLUMN id SET DEFAULT nextval('push_tokens_id_seq'::regclass);

-- task_assignment_digest_items_id_seq
IF NOT EXISTS (SELECT 1 FROM pg_sequences WHERE schemaname = 'public' AND sequencename = 'task_assignment_digest_items_id_seq') THEN
    CREATE SEQUENCE task_assignment_digest_items_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
    ALTER SEQUENCE task_assignment_digest_items_id_seq OWNED BY task_assignment_digest_items.id;
END IF;
ALTER TABLE ONLY task_assignment_digest_items ALTER COLUMN id SET DEFAULT nextval('task_assignment_digest_items_id_seq'::regclass);

-- Sync all sequences to the current max value
PERFORM setval('users_id_seq', COALESCE((SELECT MAX(id) FROM users), 0) + 1, false);
PERFORM setval('guilds_id_seq', COALESCE((SELECT MAX(id) FROM guilds), 0) + 1, false);
PERFORM setval('guild_invites_id_seq', COALESCE((SELECT MAX(id) FROM guild_invites), 0) + 1, false);
PERFORM setval('guild_settings_id_seq', COALESCE((SELECT MAX(id) FROM guild_settings), 0) + 1, false);
PERFORM setval('app_settings_id_seq', COALESCE((SELECT MAX(id) FROM app_settings), 0) + 1, false);
PERFORM setval('teams_id_seq', COALESCE((SELECT MAX(id) FROM initiatives), 0) + 1, false);
PERFORM setval('initiative_roles_id_seq', COALESCE((SELECT MAX(id) FROM initiative_roles), 0) + 1, false);
PERFORM setval('oidc_claim_mappings_id_seq', COALESCE((SELECT MAX(id) FROM oidc_claim_mappings), 0) + 1, false);
PERFORM setval('projects_id_seq', COALESCE((SELECT MAX(id) FROM projects), 0) + 1, false);
PERFORM setval('tags_id_seq', COALESCE((SELECT MAX(id) FROM tags), 0) + 1, false);
PERFORM setval('task_statuses_id_seq', COALESCE((SELECT MAX(id) FROM task_statuses), 0) + 1, false);
PERFORM setval('tasks_id_seq', COALESCE((SELECT MAX(id) FROM tasks), 0) + 1, false);
PERFORM setval('subtasks_id_seq', COALESCE((SELECT MAX(id) FROM subtasks), 0) + 1, false);
PERFORM setval('documents_id_seq', COALESCE((SELECT MAX(id) FROM documents), 0) + 1, false);
PERFORM setval('comments_id_seq', COALESCE((SELECT MAX(id) FROM comments), 0) + 1, false);
PERFORM setval('notifications_id_seq', COALESCE((SELECT MAX(id) FROM notifications), 0) + 1, false);
PERFORM setval('user_tokens_id_seq', COALESCE((SELECT MAX(id) FROM user_tokens), 0) + 1, false);
PERFORM setval('admin_api_keys_id_seq', COALESCE((SELECT MAX(id) FROM user_api_keys), 0) + 1, false);
PERFORM setval('push_tokens_id_seq', COALESCE((SELECT MAX(id) FROM push_tokens), 0) + 1, false);
PERFORM setval('task_assignment_digest_items_id_seq', COALESCE((SELECT MAX(id) FROM task_assignment_digest_items), 0) + 1, false);

-- =========================================================================
-- PHASE 16: Primary keys and unique constraints
-- =========================================================================
RAISE NOTICE 'Phase 16: Ensuring primary keys and constraints...';

-- Use DO blocks to ignore already-existing constraints
DO $$ BEGIN ALTER TABLE ONLY users ADD CONSTRAINT users_pkey PRIMARY KEY (id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY guilds ADD CONSTRAINT guilds_pkey PRIMARY KEY (id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY guild_memberships ADD CONSTRAINT guild_memberships_pkey PRIMARY KEY (guild_id, user_id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY guild_invites ADD CONSTRAINT guild_invites_pkey PRIMARY KEY (id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY guild_settings ADD CONSTRAINT guild_settings_pkey PRIMARY KEY (id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY app_settings ADD CONSTRAINT app_settings_pkey PRIMARY KEY (id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY initiatives ADD CONSTRAINT teams_pkey PRIMARY KEY (id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY initiative_roles ADD CONSTRAINT initiative_roles_pkey PRIMARY KEY (id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY initiative_role_permissions ADD CONSTRAINT initiative_role_permissions_pkey PRIMARY KEY (initiative_role_id, permission_key); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY initiative_members ADD CONSTRAINT team_members_pkey PRIMARY KEY (initiative_id, user_id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY oidc_claim_mappings ADD CONSTRAINT oidc_claim_mappings_pkey PRIMARY KEY (id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY projects ADD CONSTRAINT projects_pkey PRIMARY KEY (id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY project_permissions ADD CONSTRAINT project_members_pkey PRIMARY KEY (project_id, user_id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY project_role_permissions ADD CONSTRAINT project_role_permissions_pkey PRIMARY KEY (project_id, initiative_role_id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY project_favorites ADD CONSTRAINT project_favorites_pkey PRIMARY KEY (user_id, project_id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY project_orders ADD CONSTRAINT project_orders_pkey PRIMARY KEY (user_id, project_id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY recent_project_views ADD CONSTRAINT recent_project_views_pkey PRIMARY KEY (user_id, project_id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY tags ADD CONSTRAINT tags_pkey PRIMARY KEY (id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY task_statuses ADD CONSTRAINT task_statuses_pkey PRIMARY KEY (id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY tasks ADD CONSTRAINT tasks_pkey PRIMARY KEY (id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY task_assignees ADD CONSTRAINT task_assignees_pkey PRIMARY KEY (task_id, user_id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY task_tags ADD CONSTRAINT task_tags_pkey PRIMARY KEY (task_id, tag_id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY project_tags ADD CONSTRAINT project_tags_pkey PRIMARY KEY (project_id, tag_id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY subtasks ADD CONSTRAINT subtasks_pkey PRIMARY KEY (id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY documents ADD CONSTRAINT documents_pkey PRIMARY KEY (id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY document_permissions ADD CONSTRAINT document_permissions_pkey PRIMARY KEY (document_id, user_id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY document_role_permissions ADD CONSTRAINT document_role_permissions_pkey PRIMARY KEY (document_id, initiative_role_id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY document_links ADD CONSTRAINT document_links_pkey PRIMARY KEY (source_document_id, target_document_id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY document_tags ADD CONSTRAINT document_tags_pkey PRIMARY KEY (document_id, tag_id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY project_documents ADD CONSTRAINT project_documents_pkey PRIMARY KEY (project_id, document_id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY comments ADD CONSTRAINT comments_pkey PRIMARY KEY (id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY notifications ADD CONSTRAINT notifications_pkey PRIMARY KEY (id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY user_tokens ADD CONSTRAINT user_tokens_pkey PRIMARY KEY (id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY user_api_keys ADD CONSTRAINT admin_api_keys_pkey PRIMARY KEY (id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY push_tokens ADD CONSTRAINT push_tokens_pkey PRIMARY KEY (id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY task_assignment_digest_items ADD CONSTRAINT task_assignment_digest_items_pkey PRIMARY KEY (id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;

-- Unique constraints
DO $$ BEGIN ALTER TABLE ONLY users ADD CONSTRAINT users_email_key UNIQUE (email); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY guild_settings ADD CONSTRAINT guild_settings_guild_id_key UNIQUE (guild_id); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY user_api_keys ADD CONSTRAINT admin_api_keys_token_hash_key UNIQUE (token_hash); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY initiative_roles ADD CONSTRAINT uq_initiative_role_name UNIQUE (initiative_id, name); EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL; END $$;

-- Check constraint on comments
DO $$ BEGIN ALTER TABLE ONLY comments ADD CONSTRAINT ck_comments_task_or_document CHECK (((task_id IS NULL) <> (document_id IS NULL))); EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- =========================================================================
-- PHASE 17: Indexes
-- =========================================================================
RAISE NOTICE 'Phase 17: Creating indexes...';

CREATE INDEX IF NOT EXISTS idx_documents_updated_at ON documents USING btree (updated_at);
CREATE INDEX IF NOT EXISTS idx_guild_memberships_user_guild ON guild_memberships USING btree (user_id, guild_id);
CREATE INDEX IF NOT EXISTS idx_task_assignment_digest_items_unprocessed ON task_assignment_digest_items USING btree (processed_at) WHERE (processed_at IS NULL);
CREATE INDEX IF NOT EXISTS idx_tasks_due_date_status ON tasks USING btree (due_date, task_status_id) WHERE (due_date IS NOT NULL);
CREATE INDEX IF NOT EXISTS idx_tasks_project_archived ON tasks USING btree (project_id, is_archived);
CREATE INDEX IF NOT EXISTS idx_tasks_updated_at ON tasks USING btree (updated_at);
CREATE INDEX IF NOT EXISTS ix_admin_api_keys_token_prefix ON user_api_keys USING btree (token_prefix);
CREATE INDEX IF NOT EXISTS ix_admin_api_keys_user_id ON user_api_keys USING btree (user_id);
CREATE INDEX IF NOT EXISTS ix_comments_author_id ON comments USING btree (author_id);
CREATE INDEX IF NOT EXISTS ix_comments_created_at ON comments USING btree (created_at);
CREATE INDEX IF NOT EXISTS ix_comments_document_id ON comments USING btree (document_id);
CREATE INDEX IF NOT EXISTS ix_comments_parent_comment_id ON comments USING btree (parent_comment_id);
CREATE INDEX IF NOT EXISTS ix_comments_task_id ON comments USING btree (task_id);
CREATE INDEX IF NOT EXISTS ix_document_links_target_document_id ON document_links USING btree (target_document_id);
CREATE INDEX IF NOT EXISTS ix_document_permissions_guild_id ON document_permissions USING btree (guild_id);
CREATE INDEX IF NOT EXISTS ix_document_tags_document_id ON document_tags USING btree (document_id);
CREATE INDEX IF NOT EXISTS ix_document_tags_tag_id ON document_tags USING btree (tag_id);
CREATE INDEX IF NOT EXISTS ix_documents_guild_id ON documents USING btree (guild_id);
CREATE INDEX IF NOT EXISTS ix_documents_initiative_id ON documents USING btree (initiative_id);
CREATE INDEX IF NOT EXISTS ix_documents_title ON documents USING btree (title);
CREATE INDEX IF NOT EXISTS ix_initiative_members_guild_id ON initiative_members USING btree (guild_id);
CREATE INDEX IF NOT EXISTS ix_initiative_members_role_id ON initiative_members USING btree (role_id);
CREATE INDEX IF NOT EXISTS ix_initiative_roles_initiative_id ON initiative_roles USING btree (initiative_id);
CREATE INDEX IF NOT EXISTS ix_initiatives_name ON initiatives USING btree (name);
CREATE INDEX IF NOT EXISTS ix_notifications_user_read ON notifications USING btree (user_id, read_at);
CREATE INDEX IF NOT EXISTS ix_project_documents_guild_id ON project_documents USING btree (guild_id);
CREATE INDEX IF NOT EXISTS ix_project_documents_project_id ON project_documents USING btree (project_id);
CREATE INDEX IF NOT EXISTS ix_project_favorites_guild_id ON project_favorites USING btree (guild_id);
CREATE INDEX IF NOT EXISTS ix_project_favorites_project_id ON project_favorites USING btree (project_id);
CREATE INDEX IF NOT EXISTS ix_project_favorites_user_id ON project_favorites USING btree (user_id);
CREATE INDEX IF NOT EXISTS ix_project_orders_guild_id ON project_orders USING btree (guild_id);
CREATE INDEX IF NOT EXISTS ix_project_permissions_guild_id ON project_permissions USING btree (guild_id);
CREATE INDEX IF NOT EXISTS ix_project_tags_project_id ON project_tags USING btree (project_id);
CREATE INDEX IF NOT EXISTS ix_project_tags_tag_id ON project_tags USING btree (tag_id);
CREATE INDEX IF NOT EXISTS ix_projects_guild_id ON projects USING btree (guild_id);
CREATE INDEX IF NOT EXISTS ix_projects_name ON projects USING btree (name);
CREATE INDEX IF NOT EXISTS ix_push_tokens_push_token ON push_tokens USING btree (push_token);
CREATE INDEX IF NOT EXISTS ix_push_tokens_user_id ON push_tokens USING btree (user_id);
CREATE INDEX IF NOT EXISTS ix_recent_project_views_guild_id ON recent_project_views USING btree (guild_id);
CREATE INDEX IF NOT EXISTS ix_recent_project_views_last_viewed_at ON recent_project_views USING btree (last_viewed_at);
CREATE INDEX IF NOT EXISTS ix_recent_project_views_project_id ON recent_project_views USING btree (project_id);
CREATE INDEX IF NOT EXISTS ix_recent_project_views_user_id ON recent_project_views USING btree (user_id);
CREATE INDEX IF NOT EXISTS ix_subtasks_guild_id ON subtasks USING btree (guild_id);
CREATE INDEX IF NOT EXISTS ix_subtasks_task_id ON subtasks USING btree (task_id);
CREATE INDEX IF NOT EXISTS ix_tags_guild_id ON tags USING btree (guild_id);
CREATE INDEX IF NOT EXISTS ix_task_assignees_guild_id ON task_assignees USING btree (guild_id);
CREATE INDEX IF NOT EXISTS ix_task_assignment_digest_items_user_id ON task_assignment_digest_items USING btree (user_id);
CREATE INDEX IF NOT EXISTS ix_task_statuses_guild_id ON task_statuses USING btree (guild_id);
CREATE INDEX IF NOT EXISTS ix_task_statuses_project_position ON task_statuses USING btree (project_id, "position");
CREATE INDEX IF NOT EXISTS ix_task_tags_tag_id ON task_tags USING btree (tag_id);
CREATE INDEX IF NOT EXISTS ix_task_tags_task_id ON task_tags USING btree (task_id);
CREATE INDEX IF NOT EXISTS ix_tasks_guild_id ON tasks USING btree (guild_id);
CREATE INDEX IF NOT EXISTS ix_tasks_is_archived ON tasks USING btree (is_archived);
CREATE INDEX IF NOT EXISTS ix_tasks_project_id_id ON tasks USING btree (project_id, id);
CREATE INDEX IF NOT EXISTS ix_user_tokens_user_id ON user_tokens USING btree (user_id);
CREATE INDEX IF NOT EXISTS ix_users_email ON users USING btree (email);

-- Unique indexes
CREATE UNIQUE INDEX IF NOT EXISTS ix_guild_invites_code ON guild_invites USING btree (code);
CREATE UNIQUE INDEX IF NOT EXISTS ix_tags_guild_name_unique ON tags USING btree (guild_id, lower((name)::text));
CREATE UNIQUE INDEX IF NOT EXISTS ix_push_tokens_user_device_token ON push_tokens USING btree (user_id, push_token);
CREATE UNIQUE INDEX IF NOT EXISTS ix_user_tokens_token ON user_tokens USING btree (token);
CREATE UNIQUE INDEX IF NOT EXISTS uq_initiatives_guild_default ON initiatives USING btree (guild_id) WHERE is_default;
CREATE UNIQUE INDEX IF NOT EXISTS uq_initiatives_guild_name ON initiatives USING btree (guild_id, lower((name)::text));

-- Drop old unique constraint on initiative name if it exists
IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'initiatives_name_key'
) THEN
    ALTER TABLE initiatives DROP CONSTRAINT initiatives_name_key;
END IF;

-- Drop old unique default index if it exists (pre-guild era)
DROP INDEX IF EXISTS uq_initiatives_default;

-- =========================================================================
-- PHASE 18: Foreign keys
-- =========================================================================
RAISE NOTICE 'Phase 18: Ensuring foreign keys...';

-- user_api_keys
DO $$ BEGIN ALTER TABLE ONLY user_api_keys ADD CONSTRAINT admin_api_keys_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- comments
DO $$ BEGIN ALTER TABLE ONLY comments ADD CONSTRAINT comments_author_id_fkey FOREIGN KEY (author_id) REFERENCES users(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY comments ADD CONSTRAINT comments_document_id_fkey FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY comments ADD CONSTRAINT comments_parent_comment_id_fkey FOREIGN KEY (parent_comment_id) REFERENCES comments(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY comments ADD CONSTRAINT comments_task_id_fkey FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- document_links
DO $$ BEGIN ALTER TABLE ONLY document_links ADD CONSTRAINT document_links_guild_id_fkey FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY document_links ADD CONSTRAINT document_links_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES documents(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY document_links ADD CONSTRAINT document_links_target_document_id_fkey FOREIGN KEY (target_document_id) REFERENCES documents(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- document_permissions
DO $$ BEGIN ALTER TABLE ONLY document_permissions ADD CONSTRAINT document_permissions_document_id_fkey FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY document_permissions ADD CONSTRAINT document_permissions_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY document_permissions ADD CONSTRAINT fk_document_permissions_guild_id FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- document_role_permissions
DO $$ BEGIN ALTER TABLE ONLY document_role_permissions ADD CONSTRAINT document_role_permissions_document_id_fkey FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY document_role_permissions ADD CONSTRAINT document_role_permissions_guild_id_fkey FOREIGN KEY (guild_id) REFERENCES guilds(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY document_role_permissions ADD CONSTRAINT document_role_permissions_initiative_role_id_fkey FOREIGN KEY (initiative_role_id) REFERENCES initiative_roles(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- document_tags
DO $$ BEGIN ALTER TABLE ONLY document_tags ADD CONSTRAINT document_tags_document_id_fkey FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY document_tags ADD CONSTRAINT document_tags_tag_id_fkey FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- documents
DO $$ BEGIN ALTER TABLE ONLY documents ADD CONSTRAINT documents_created_by_id_fkey FOREIGN KEY (created_by_id) REFERENCES users(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY documents ADD CONSTRAINT documents_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES initiatives(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY documents ADD CONSTRAINT documents_updated_by_id_fkey FOREIGN KEY (updated_by_id) REFERENCES users(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY documents ADD CONSTRAINT fk_documents_guild_id FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- guild_invites
DO $$ BEGIN ALTER TABLE ONLY guild_invites ADD CONSTRAINT guild_invites_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY guild_invites ADD CONSTRAINT guild_invites_guild_id_fkey FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- guild_memberships
DO $$ BEGIN ALTER TABLE ONLY guild_memberships ADD CONSTRAINT guild_memberships_guild_id_fkey FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY guild_memberships ADD CONSTRAINT guild_memberships_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- guild_settings
DO $$ BEGIN ALTER TABLE ONLY guild_settings ADD CONSTRAINT guild_settings_guild_id_fkey FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- guilds
DO $$ BEGIN ALTER TABLE ONLY guilds ADD CONSTRAINT guilds_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES users(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- initiative_members
DO $$ BEGIN ALTER TABLE ONLY initiative_members ADD CONSTRAINT fk_initiative_members_guild_id FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY initiative_members ADD CONSTRAINT initiative_members_role_id_fkey FOREIGN KEY (role_id) REFERENCES initiative_roles(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY initiative_members ADD CONSTRAINT team_members_team_id_fkey FOREIGN KEY (initiative_id) REFERENCES initiatives(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY initiative_members ADD CONSTRAINT team_members_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- initiative_role_permissions
DO $$ BEGIN ALTER TABLE ONLY initiative_role_permissions ADD CONSTRAINT initiative_role_permissions_initiative_role_id_fkey FOREIGN KEY (initiative_role_id) REFERENCES initiative_roles(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- initiative_roles
DO $$ BEGIN ALTER TABLE ONLY initiative_roles ADD CONSTRAINT initiative_roles_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES initiatives(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- initiatives
DO $$ BEGIN ALTER TABLE ONLY initiatives ADD CONSTRAINT fk_initiatives_guild_id FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- notifications
DO $$ BEGIN ALTER TABLE ONLY notifications ADD CONSTRAINT notifications_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- oidc_claim_mappings
DO $$ BEGIN ALTER TABLE ONLY oidc_claim_mappings ADD CONSTRAINT oidc_claim_mappings_guild_id_fkey FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY oidc_claim_mappings ADD CONSTRAINT oidc_claim_mappings_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES initiatives(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY oidc_claim_mappings ADD CONSTRAINT oidc_claim_mappings_initiative_role_id_fkey FOREIGN KEY (initiative_role_id) REFERENCES initiative_roles(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- project_documents
DO $$ BEGIN ALTER TABLE ONLY project_documents ADD CONSTRAINT fk_project_documents_guild_id FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY project_documents ADD CONSTRAINT project_documents_attached_by_id_fkey FOREIGN KEY (attached_by_id) REFERENCES users(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY project_documents ADD CONSTRAINT project_documents_document_id_fkey FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY project_documents ADD CONSTRAINT project_documents_project_id_fkey FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- project_favorites
DO $$ BEGIN ALTER TABLE ONLY project_favorites ADD CONSTRAINT fk_project_favorites_guild_id FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY project_favorites ADD CONSTRAINT project_favorites_project_id_fkey FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY project_favorites ADD CONSTRAINT project_favorites_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- project_orders
DO $$ BEGIN ALTER TABLE ONLY project_orders ADD CONSTRAINT fk_project_orders_guild_id FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY project_orders ADD CONSTRAINT project_orders_project_id_fkey FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY project_orders ADD CONSTRAINT project_orders_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- project_permissions
DO $$ BEGIN ALTER TABLE ONLY project_permissions ADD CONSTRAINT fk_project_permissions_guild_id FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY project_permissions ADD CONSTRAINT project_members_project_id_fkey FOREIGN KEY (project_id) REFERENCES projects(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY project_permissions ADD CONSTRAINT project_members_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- project_role_permissions
DO $$ BEGIN ALTER TABLE ONLY project_role_permissions ADD CONSTRAINT project_role_permissions_guild_id_fkey FOREIGN KEY (guild_id) REFERENCES guilds(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY project_role_permissions ADD CONSTRAINT project_role_permissions_initiative_role_id_fkey FOREIGN KEY (initiative_role_id) REFERENCES initiative_roles(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY project_role_permissions ADD CONSTRAINT project_role_permissions_project_id_fkey FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- project_tags
DO $$ BEGIN ALTER TABLE ONLY project_tags ADD CONSTRAINT project_tags_project_id_fkey FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY project_tags ADD CONSTRAINT project_tags_tag_id_fkey FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- projects
DO $$ BEGIN ALTER TABLE ONLY projects ADD CONSTRAINT fk_projects_guild_id FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY projects ADD CONSTRAINT projects_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES users(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY projects ADD CONSTRAINT projects_team_id_fkey FOREIGN KEY (initiative_id) REFERENCES initiatives(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- push_tokens
DO $$ BEGIN ALTER TABLE ONLY push_tokens ADD CONSTRAINT push_tokens_device_token_id_fkey FOREIGN KEY (device_token_id) REFERENCES user_tokens(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY push_tokens ADD CONSTRAINT push_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- recent_project_views
DO $$ BEGIN ALTER TABLE ONLY recent_project_views ADD CONSTRAINT fk_recent_project_views_guild_id FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY recent_project_views ADD CONSTRAINT recent_project_views_project_id_fkey FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY recent_project_views ADD CONSTRAINT recent_project_views_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- subtasks
DO $$ BEGIN ALTER TABLE ONLY subtasks ADD CONSTRAINT fk_subtasks_guild_id FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY subtasks ADD CONSTRAINT fk_subtasks_task_id FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- tags
DO $$ BEGIN ALTER TABLE ONLY tags ADD CONSTRAINT tags_guild_id_fkey FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- task_assignees
DO $$ BEGIN ALTER TABLE ONLY task_assignees ADD CONSTRAINT fk_task_assignees_guild_id FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY task_assignees ADD CONSTRAINT task_assignees_task_id_fkey FOREIGN KEY (task_id) REFERENCES tasks(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY task_assignees ADD CONSTRAINT task_assignees_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- task_assignment_digest_items
DO $$ BEGIN ALTER TABLE ONLY task_assignment_digest_items ADD CONSTRAINT task_assignment_digest_items_assigned_by_id_fkey FOREIGN KEY (assigned_by_id) REFERENCES users(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY task_assignment_digest_items ADD CONSTRAINT task_assignment_digest_items_project_id_fkey FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY task_assignment_digest_items ADD CONSTRAINT task_assignment_digest_items_task_id_fkey FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY task_assignment_digest_items ADD CONSTRAINT task_assignment_digest_items_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- task_statuses
DO $$ BEGIN ALTER TABLE ONLY task_statuses ADD CONSTRAINT fk_task_statuses_guild_id FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY task_statuses ADD CONSTRAINT task_statuses_project_id_fkey FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- task_tags
DO $$ BEGIN ALTER TABLE ONLY task_tags ADD CONSTRAINT task_tags_tag_id_fkey FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY task_tags ADD CONSTRAINT task_tags_task_id_fkey FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- tasks
DO $$ BEGIN ALTER TABLE ONLY tasks ADD CONSTRAINT fk_tasks_guild_id FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY tasks ADD CONSTRAINT fk_tasks_task_status_id FOREIGN KEY (task_status_id) REFERENCES task_statuses(id) ON DELETE RESTRICT; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE ONLY tasks ADD CONSTRAINT tasks_project_id_fkey FOREIGN KEY (project_id) REFERENCES projects(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- user_tokens
DO $$ BEGIN ALTER TABLE ONLY user_tokens ADD CONSTRAINT user_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- =========================================================================
-- PHASE 19: Trigger functions and triggers
-- =========================================================================
RAISE NOTICE 'Phase 19: Creating trigger functions and triggers...';

-- guild_id propagation trigger functions
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
    $$;

CREATE OR REPLACE FUNCTION fn_document_permissions_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.document_id IS DISTINCT FROM NEW.document_id) THEN
            SELECT guild_id INTO NEW.guild_id FROM documents WHERE id = NEW.document_id;
        END IF;
        RETURN NEW;
    END;
    $$;

CREATE OR REPLACE FUNCTION fn_documents_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.initiative_id IS DISTINCT FROM NEW.initiative_id) THEN
            SELECT guild_id INTO NEW.guild_id FROM initiatives WHERE id = NEW.initiative_id;
        END IF;
        RETURN NEW;
    END;
    $$;

CREATE OR REPLACE FUNCTION fn_initiative_members_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.initiative_id IS DISTINCT FROM NEW.initiative_id) THEN
            SELECT guild_id INTO NEW.guild_id FROM initiatives WHERE id = NEW.initiative_id;
        END IF;
        RETURN NEW;
    END;
    $$;

CREATE OR REPLACE FUNCTION fn_project_documents_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.project_id IS DISTINCT FROM NEW.project_id) THEN
            SELECT guild_id INTO NEW.guild_id FROM projects WHERE id = NEW.project_id;
        END IF;
        RETURN NEW;
    END;
    $$;

CREATE OR REPLACE FUNCTION fn_project_favorites_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.project_id IS DISTINCT FROM NEW.project_id) THEN
            SELECT guild_id INTO NEW.guild_id FROM projects WHERE id = NEW.project_id;
        END IF;
        RETURN NEW;
    END;
    $$;

CREATE OR REPLACE FUNCTION fn_project_orders_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.project_id IS DISTINCT FROM NEW.project_id) THEN
            SELECT guild_id INTO NEW.guild_id FROM projects WHERE id = NEW.project_id;
        END IF;
        RETURN NEW;
    END;
    $$;

CREATE OR REPLACE FUNCTION fn_project_permissions_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.project_id IS DISTINCT FROM NEW.project_id) THEN
            SELECT guild_id INTO NEW.guild_id FROM projects WHERE id = NEW.project_id;
        END IF;
        RETURN NEW;
    END;
    $$;

CREATE OR REPLACE FUNCTION fn_projects_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.initiative_id IS DISTINCT FROM NEW.initiative_id) THEN
            SELECT guild_id INTO NEW.guild_id FROM initiatives WHERE id = NEW.initiative_id;
        END IF;
        RETURN NEW;
    END;
    $$;

CREATE OR REPLACE FUNCTION fn_recent_project_views_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.project_id IS DISTINCT FROM NEW.project_id) THEN
            SELECT guild_id INTO NEW.guild_id FROM projects WHERE id = NEW.project_id;
        END IF;
        RETURN NEW;
    END;
    $$;

CREATE OR REPLACE FUNCTION fn_subtasks_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.task_id IS DISTINCT FROM NEW.task_id) THEN
            SELECT guild_id INTO NEW.guild_id FROM tasks WHERE id = NEW.task_id;
        END IF;
        RETURN NEW;
    END;
    $$;

CREATE OR REPLACE FUNCTION fn_task_assignees_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.task_id IS DISTINCT FROM NEW.task_id) THEN
            SELECT guild_id INTO NEW.guild_id FROM tasks WHERE id = NEW.task_id;
        END IF;
        RETURN NEW;
    END;
    $$;

CREATE OR REPLACE FUNCTION fn_task_statuses_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.project_id IS DISTINCT FROM NEW.project_id) THEN
            SELECT guild_id INTO NEW.guild_id FROM projects WHERE id = NEW.project_id;
        END IF;
        RETURN NEW;
    END;
    $$;

CREATE OR REPLACE FUNCTION fn_tasks_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.project_id IS DISTINCT FROM NEW.project_id) THEN
            SELECT guild_id INTO NEW.guild_id FROM projects WHERE id = NEW.project_id;
        END IF;
        RETURN NEW;
    END;
    $$;

-- Create the is_initiative_member() helper function
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
    $$;

-- Drop and recreate triggers (idempotent)
DROP TRIGGER IF EXISTS tr_comments_set_guild_id ON comments;
CREATE TRIGGER tr_comments_set_guild_id BEFORE INSERT OR UPDATE OF task_id, document_id ON comments FOR EACH ROW EXECUTE FUNCTION fn_comments_set_guild_id();

DROP TRIGGER IF EXISTS tr_document_permissions_set_guild_id ON document_permissions;
CREATE TRIGGER tr_document_permissions_set_guild_id BEFORE INSERT OR UPDATE OF document_id ON document_permissions FOR EACH ROW EXECUTE FUNCTION fn_document_permissions_set_guild_id();

DROP TRIGGER IF EXISTS tr_documents_set_guild_id ON documents;
CREATE TRIGGER tr_documents_set_guild_id BEFORE INSERT OR UPDATE OF initiative_id ON documents FOR EACH ROW EXECUTE FUNCTION fn_documents_set_guild_id();

DROP TRIGGER IF EXISTS tr_initiative_members_set_guild_id ON initiative_members;
CREATE TRIGGER tr_initiative_members_set_guild_id BEFORE INSERT OR UPDATE OF initiative_id ON initiative_members FOR EACH ROW EXECUTE FUNCTION fn_initiative_members_set_guild_id();

DROP TRIGGER IF EXISTS tr_project_documents_set_guild_id ON project_documents;
CREATE TRIGGER tr_project_documents_set_guild_id BEFORE INSERT OR UPDATE OF project_id ON project_documents FOR EACH ROW EXECUTE FUNCTION fn_project_documents_set_guild_id();

DROP TRIGGER IF EXISTS tr_project_favorites_set_guild_id ON project_favorites;
CREATE TRIGGER tr_project_favorites_set_guild_id BEFORE INSERT OR UPDATE OF project_id ON project_favorites FOR EACH ROW EXECUTE FUNCTION fn_project_favorites_set_guild_id();

DROP TRIGGER IF EXISTS tr_project_orders_set_guild_id ON project_orders;
CREATE TRIGGER tr_project_orders_set_guild_id BEFORE INSERT OR UPDATE OF project_id ON project_orders FOR EACH ROW EXECUTE FUNCTION fn_project_orders_set_guild_id();

DROP TRIGGER IF EXISTS tr_project_permissions_set_guild_id ON project_permissions;
CREATE TRIGGER tr_project_permissions_set_guild_id BEFORE INSERT OR UPDATE OF project_id ON project_permissions FOR EACH ROW EXECUTE FUNCTION fn_project_permissions_set_guild_id();

DROP TRIGGER IF EXISTS tr_projects_set_guild_id ON projects;
CREATE TRIGGER tr_projects_set_guild_id BEFORE INSERT OR UPDATE OF initiative_id ON projects FOR EACH ROW EXECUTE FUNCTION fn_projects_set_guild_id();

DROP TRIGGER IF EXISTS tr_recent_project_views_set_guild_id ON recent_project_views;
CREATE TRIGGER tr_recent_project_views_set_guild_id BEFORE INSERT OR UPDATE OF project_id ON recent_project_views FOR EACH ROW EXECUTE FUNCTION fn_recent_project_views_set_guild_id();

DROP TRIGGER IF EXISTS tr_subtasks_set_guild_id ON subtasks;
CREATE TRIGGER tr_subtasks_set_guild_id BEFORE INSERT OR UPDATE OF task_id ON subtasks FOR EACH ROW EXECUTE FUNCTION fn_subtasks_set_guild_id();

DROP TRIGGER IF EXISTS tr_task_assignees_set_guild_id ON task_assignees;
CREATE TRIGGER tr_task_assignees_set_guild_id BEFORE INSERT OR UPDATE OF task_id ON task_assignees FOR EACH ROW EXECUTE FUNCTION fn_task_assignees_set_guild_id();

DROP TRIGGER IF EXISTS tr_task_statuses_set_guild_id ON task_statuses;
CREATE TRIGGER tr_task_statuses_set_guild_id BEFORE INSERT OR UPDATE OF project_id ON task_statuses FOR EACH ROW EXECUTE FUNCTION fn_task_statuses_set_guild_id();

DROP TRIGGER IF EXISTS tr_tasks_set_guild_id ON tasks;
CREATE TRIGGER tr_tasks_set_guild_id BEFORE INSERT OR UPDATE OF project_id ON tasks FOR EACH ROW EXECUTE FUNCTION fn_tasks_set_guild_id();

-- =========================================================================
-- PHASE 20: Clean up obsolete types
-- =========================================================================
RAISE NOTICE 'Phase 20: Cleaning up obsolete types...';

-- Drop old enum types that are no longer used
DROP TYPE IF EXISTS task_status;
DROP TYPE IF EXISTS project_role;
DROP TYPE IF EXISTS initiative_role;

-- =========================================================================
-- PHASE 21: Prepare alembic_version for baseline
-- =========================================================================
RAISE NOTICE 'Phase 21: Preparing alembic_version...';

-- Clear any stale alembic_version so the baseline migration can run fresh.
-- Do NOT stamp 20260216_0053 here — let "alembic upgrade head" run the
-- baseline, which creates roles, RLS policies, and grants.
CREATE TABLE IF NOT EXISTS alembic_version (
    version_num character varying(32) NOT NULL
);
DELETE FROM alembic_version;

RAISE NOTICE '=== Schema upgrade complete! ===';
RAISE NOTICE '';
RAISE NOTICE 'NEXT STEP: Run "alembic upgrade head" (or start the application).';
RAISE NOTICE 'The baseline migration will create database roles, enable RLS policies,';
RAISE NOTICE 'and grant privileges. It will skip schema creation since tables already exist.';

END $phase2$;

COMMIT;
