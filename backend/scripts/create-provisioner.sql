-- One-time handover to the least-privilege provisioning role (existing installs).
--
-- Fresh docker-compose installs never need this — their init script creates
-- app_provisioner at first database init. Run this ONCE on deployments that
-- predate it, connected to the app database AS THE CURRENT DATABASE_URL ROLE
-- (the role that has been running migrations — it owns the app's objects):
--
--   docker exec -i initiative-db \
--     psql -v ON_ERROR_STOP=1 -U initiative -d initiative \
--          -v provisioner_password='CHANGE-ME' \
--          -f - < backend/scripts/create-provisioner.sql
--
-- Then set DATABASE_URL to connect as app_provisioner and restart the app.
-- Re-running is safe (attributes, grants and ownership are re-asserted).
--
-- Why: the app needs CREATEROLE + CREATE on the database + ownership of its
-- own objects for migrations and guild provisioning — never a SUPERUSER.
-- FORCE ROW LEVEL SECURITY keeps even the object owner policy-bound for DML.

\set ON_ERROR_STOP on

-- 1. The role: DDL-capable, never SUPERUSER, never BYPASSRLS.
SELECT format(
    'CREATE ROLE app_provisioner WITH LOGIN CREATEROLE NOSUPERUSER NOBYPASSRLS PASSWORD %L',
    :'provisioner_password'
) WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_provisioner')
\gexec
SELECT format(
    'ALTER ROLE app_provisioner WITH LOGIN CREATEROLE NOSUPERUSER NOBYPASSRLS PASSWORD %L',
    :'provisioner_password'
)
\gexec

-- 2. Schema creation (guild provisioning) in this database.
SELECT format(
    'GRANT CREATE, CONNECT ON DATABASE %I TO app_provisioner', current_database()
)
\gexec

-- 2b. The public schema itself. Postgres 15+ made CREATE on public
--     owner-only, and provisioner-run migrations create shared tables there
--     (the baseline also COMMENTs on the schema, which needs ownership).
ALTER SCHEMA public OWNER TO app_provisioner;

-- 3. Administer the app's existing cluster roles (sync login-role passwords,
--    grant guild-role memberships, drop guild roles on deprovision). Roles the
--    provisioner CREATES from now on carry implicit ADMIN (PG16+ CREATEROLE).
DO $$
DECLARE r record;
BEGIN
    FOR r IN
        SELECT rolname FROM pg_roles
        WHERE rolname IN (
            'app_user', 'app_admin', 'app_guild_base', 'platform_base',
            'platform_member', 'platform_support', 'platform_moderator',
            -- platform_admin is the pre-0139 name; platform_operator is the
            -- current one. List both so this runs before or after that migration.
            'platform_admin', 'platform_operator', 'platform_owner'
        )
        OR rolname ~ '^guild_[0-9]+(_ro|_support)?$'
    LOOP
        EXECUTE format('GRANT %I TO app_provisioner WITH ADMIN OPTION', r.rolname);
    END LOOP;
END $$;

-- 4. Hand over the app's objects. Explicit catalog iteration, NOT REASSIGN
--    OWNED (which fails for a bootstrap superuser's pinned system objects).
--    Tables first — their owned (serial) sequences follow automatically.
DO $$
DECLARE r record;
BEGIN
    FOR r IN
        SELECT n.nspname, c.relname FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE (n.nspname = 'public' OR n.nspname ~ '^guild_([0-9]+|template)$')
          AND c.relkind IN ('r', 'v', 'm', 'p')
          AND c.relowner = current_user::regrole
    LOOP
        EXECUTE format('ALTER TABLE %I.%I OWNER TO app_provisioner', r.nspname, r.relname);
    END LOOP;
    FOR r IN
        SELECT n.nspname, c.relname FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE (n.nspname = 'public' OR n.nspname ~ '^guild_([0-9]+|template)$')
          AND c.relkind = 'S' AND c.relowner = current_user::regrole
          AND NOT EXISTS (
              SELECT 1 FROM pg_depend d WHERE d.objid = c.oid AND d.deptype = 'a'
          )
    LOOP
        EXECUTE format('ALTER SEQUENCE %I.%I OWNER TO app_provisioner', r.nspname, r.relname);
    END LOOP;
    FOR r IN
        SELECT p.oid::regprocedure AS sig FROM pg_proc p
        WHERE p.pronamespace = 'public'::regnamespace
          AND p.proowner = current_user::regrole
          AND NOT EXISTS (
              SELECT 1 FROM pg_depend d WHERE d.objid = p.oid AND d.deptype = 'e'
          )
    LOOP
        EXECUTE format('ALTER FUNCTION %s OWNER TO app_provisioner', r.sig);
    END LOOP;
    FOR r IN
        SELECT t.typname FROM pg_type t
        WHERE t.typnamespace = 'public'::regnamespace AND t.typtype = 'e'
          AND t.typowner = current_user::regrole
    LOOP
        EXECUTE format('ALTER TYPE public.%I OWNER TO app_provisioner', r.typname);
    END LOOP;
    FOR r IN
        SELECT n.nspname FROM pg_namespace n
        WHERE n.nspname ~ '^guild_([0-9]+|template)$'
          AND n.nspowner = current_user::regrole
    LOOP
        EXECUTE format('ALTER SCHEMA %I OWNER TO app_provisioner', r.nspname);
    END LOOP;
END $$;

-- 5. Tables created by future provisioner-run migrations get the standard
--    working grants automatically (deliberately WITHOUT app_admin — the system
--    engine is granted per table by migrations, never implicitly).
ALTER DEFAULT PRIVILEGES FOR ROLE app_provisioner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES
    TO app_user, app_guild_base, platform_base;
ALTER DEFAULT PRIVILEGES FOR ROLE app_provisioner IN SCHEMA public
    GRANT SELECT, USAGE ON SEQUENCES
    TO app_user, app_guild_base, platform_base;

-- 6. Least privilege on the database itself: the app creates no temporary
--    objects, so it does not need the TEMPORARY grant PUBLIC carries by
--    default on a new database. Fresh docker-compose installs do this at
--    database init; this brings an existing deployment in line.
SELECT format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC', current_database())
\gexec

-- Only a database's owner can change its ACL. A REVOKE issued by any other
-- role reports success with a WARNING and changes nothing, so confirm the
-- grant is actually gone rather than trusting the command's exit.
DO $verify$
DECLARE
    db_owner text;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_database d,
             aclexplode(coalesce(d.datacl, acldefault('d', d.datdba))) a
        WHERE d.datname = current_database()
          AND a.grantee = 0                       -- 0 is PUBLIC
          AND a.privilege_type = 'TEMPORARY'
    ) THEN
        SELECT pg_get_userbyid(datdba) INTO db_owner
          FROM pg_database WHERE datname = current_database();
        RAISE EXCEPTION
            'REVOKE TEMPORARY did not take effect on database %. Re-run this '
            'script connected as its owner (%).',
            current_database(), db_owner;
    END IF;
END
$verify$;

\echo 'app_provisioner ready — point DATABASE_URL at it and restart the app.'
