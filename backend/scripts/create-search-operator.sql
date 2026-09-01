-- Search match operator + GIN operator class (one-time, superuser).
--
-- Fresh docker-compose installs never need this — their init script creates
-- these objects at first database init. Run this ONCE on existing deployments,
-- connected to the app database AS A SUPERUSER, BEFORE upgrading the app:
--
--   docker exec -i initiative-db \
--     psql -v ON_ERROR_STOP=1 -U initiative -d initiative \
--          -f - < backend/scripts/create-search-operator.sql
--
-- Re-running is safe. After running it, restart the app: the guild search
-- index is rebuilt against this operator class on the next provisioning sweep.
--
-- What it is
-- -----------
-- Guild search matches a `tsvector` against a `tsquery`. These objects give it
-- its own match operator and GIN operator class, so its index can be used. The
-- stock `@@` operator is left exactly as Postgres ships it.
--
-- Creating them requires superuser, which the app never holds: it runs as
-- app_provisioner (NOSUPERUSER, NOBYPASSRLS). They are ordinary schema objects
-- once created, so pg_dump carries them.
--
-- Without them search still returns the same rows, reading more of the index
-- table to do it. The app says so at boot.

\set ON_ERROR_STOP on

-- 1. The match function. PL/pgSQL rather than SQL on purpose: a SQL body is
--    inlined into the calling query, which discards the attributes set here.
CREATE OR REPLACE FUNCTION public.search_tsmatch(tsvector, tsquery)
    RETURNS boolean
    LANGUAGE plpgsql
    IMMUTABLE STRICT PARALLEL SAFE LEAKPROOF
    AS $$ BEGIN RETURN $1 OPERATOR(pg_catalog.@@) $2; END $$;

COMMENT ON FUNCTION public.search_tsmatch(tsvector, tsquery) IS
    'Guild search text match, behind the public.@@@ operator. Body is PL/pgSQL '
    'so the attributes declared here survive planning.';

-- 2. The operator. Selectivity estimators are the stock full-text ones, so the
--    planner costs it exactly as it costs `@@`.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_operator o
        JOIN pg_namespace n ON n.oid = o.oprnamespace
        WHERE n.nspname = 'public' AND o.oprname = '@@@'
          AND o.oprleft = 'tsvector'::regtype AND o.oprright = 'tsquery'::regtype
    ) THEN
        CREATE OPERATOR public.@@@ (
            LEFTARG   = tsvector,
            RIGHTARG  = tsquery,
            PROCEDURE = public.search_tsmatch,
            RESTRICT  = tsmatchsel,
            JOIN      = tsmatchjoinsel
        );
    END IF;
END
$$;

-- 3. The GIN operator class. Support functions are the stock ones — only the
--    operator differs, so an index built on it behaves like any tsvector GIN
--    index.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_opclass c
        JOIN pg_namespace n ON n.oid = c.opcnamespace
        WHERE n.nspname = 'public' AND c.opcname = 'tsvector_search_ops'
    ) THEN
        CREATE OPERATOR CLASS public.tsvector_search_ops
            FOR TYPE tsvector USING gin AS
            OPERATOR 1 public.@@@ (tsvector, tsquery),
            FUNCTION 1 pg_catalog.gin_cmp_tslexeme(text, text),
            FUNCTION 2 pg_catalog.gin_extract_tsvector(tsvector, internal, internal),
            FUNCTION 3 pg_catalog.gin_extract_tsquery(tsvector, internal, smallint,
                           internal, internal, internal, internal),
            FUNCTION 4 pg_catalog.gin_tsquery_consistent(internal, smallint, tsvector,
                           integer, internal, internal, internal, internal),
            FUNCTION 5 pg_catalog.gin_cmp_prefix(text, text, smallint, internal),
            FUNCTION 6 pg_catalog.gin_tsquery_triconsistent(internal, smallint, tsvector,
                           integer, internal, internal, internal),
            STORAGE text;
    END IF;
END
$$;

-- 4. Confirm. Both must be present for search to use its index.
SELECT
    (SELECT proleakproof FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
      WHERE n.nspname='public' AND p.proname='search_tsmatch') AS function_leakproof,
    EXISTS (SELECT 1 FROM pg_opclass c JOIN pg_namespace n ON n.oid = c.opcnamespace
             WHERE n.nspname='public' AND c.opcname='tsvector_search_ops') AS opclass_present;
