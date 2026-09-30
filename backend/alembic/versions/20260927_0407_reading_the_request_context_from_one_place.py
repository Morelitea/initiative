"""reading the request context from one place

The sign-in functions, ``public.guild_superadmin()`` and
``public.fn_install_owns_what_it_creates()`` read the request context in the
same spelling as every policy and gate (``app.db.gucs``). What each does is
unchanged.

The bodies are stated here in full, as they were and as they become, so this
revision reads the same whatever the modules say later.

Revision ID: 20260927_0407
Revises: 20260925_0406
Create Date: 2026-09-27
"""

from alembic import op

revision = "20260927_0407"
down_revision = "20260925_0406"
branch_labels = None
depends_on = None


GUILD_CONNECTION_SATISFIED_BEFORE = """CREATE OR REPLACE FUNCTION public.guild_connection_satisfied(p_guild_id integer, p_provider_id integer DEFAULT NULL::integer)
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT public.guild_connection_admits(
        p_guild_id,
        -- NULLIF twice: an unset value and the system sentinel both leave
        -- nothing to cast, and a bare ''::int[] would fault every policy on
        -- the table.
        COALESCE(
            string_to_array(
                NULLIF(
                    NULLIF(current_setting('app.satisfied_providers', true), ''),
                    'system'
                ),
                ','
            )::integer[],
            ARRAY[]::integer[]
        ),
        COALESCE(
            NULLIF(current_setting('app.satisfied_claims', true), '')::jsonb,
            '{}'::jsonb
        ),
        p_provider_id
    )
$function$

"""

GUILD_CONNECTION_SATISFIED_AFTER = """CREATE OR REPLACE FUNCTION public.guild_connection_satisfied(p_guild_id integer, p_provider_id integer DEFAULT NULL::integer)
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT public.guild_connection_admits(
        p_guild_id,
        -- NULLIF twice: an unset value and the system sentinel both leave
        -- nothing to cast, and a bare ''::int[] would fault every policy on
        -- the table.
        COALESCE(
            string_to_array(
                NULLIF(NULLIF(current_setting('app.satisfied_providers'::text, true), ''::text), 'system'::text),
                ','
            )::integer[],
            ARRAY[]::integer[]
        ),
        COALESCE(
            NULLIF(current_setting('app.satisfied_claims'::text, true), ''::text)::jsonb,
            '{}'::jsonb
        ),
        p_provider_id
    )
$function$

"""

SESSION_AMR_BEFORE = """CREATE OR REPLACE FUNCTION public.session_amr()
 RETURNS text[]
 LANGUAGE sql
 STABLE
AS $function$
    SELECT COALESCE(
        string_to_array(
            NULLIF(current_setting('app.session_amr', true), ''),
            ','
        ),
        ARRAY[]::text[]
    )
$function$

"""

SESSION_AMR_AFTER = """CREATE OR REPLACE FUNCTION public.session_amr()
 RETURNS text[]
 LANGUAGE sql
 STABLE
AS $function$
    SELECT COALESCE(string_to_array(NULLIF(current_setting('app.session_amr'::text, true), ''::text), ','::text), ARRAY[]::text[])
$function$

"""

PLATFORM_FACTOR_SATISFIED_BEFORE = """CREATE OR REPLACE FUNCTION public.platform_factor_satisfied()
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT NOT EXISTS (
        SELECT 1 FROM public.app_settings s
        WHERE s.id = 1
          AND s.second_factor_requirement <> 'nobody'
          AND (
              s.second_factor_requirement = 'everyone'
              OR COALESCE(current_setting('app.platform_role', true), '') <> 'member'
          )
          AND COALESCE(
                current_setting('app.platform_factor', true), 'false'
              ) <> 'true'
    )
$function$

"""

PLATFORM_FACTOR_SATISFIED_AFTER = """CREATE OR REPLACE FUNCTION public.platform_factor_satisfied()
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT NOT EXISTS (
        SELECT 1 FROM public.app_settings s
        WHERE s.id = 1
          AND s.second_factor_requirement <> 'nobody'
          AND (
              s.second_factor_requirement = 'everyone'
              OR NULLIF(current_setting('app.platform_role'::text, true), ''::text) IS DISTINCT FROM 'member'
          )
          AND (current_setting('app.platform_factor'::text, true) = 'true'::text) IS NOT TRUE
    )
$function$

"""

GUILD_AUTH_SATISFIED_BEFORE = """CREATE OR REPLACE FUNCTION public.guild_auth_satisfied()
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT
        -- Pure system routing (no user context) and the explicit sentinel a
        -- user-attributed job sets are not sessions to gate.
        NULLIF(current_setting('app.current_user_id', true), '') IS NULL
        OR current_setting('app.satisfied_providers', true) = 'system'
        OR (
        -- What the deployment asks of the account, before what the community
        -- asks of the session. Both have to hold.
        public.platform_factor_satisfied()
        AND NOT EXISTS (
            SELECT 1 FROM public.guild_auth_policies p
            WHERE p.guild_id = COALESCE(
                    NULLIF(current_setting('app.current_guild_id', true), ''),
                    NULLIF(current_setting('app.pam_guild_id', true), ''),
                    NULLIF(current_setting('app.settings_guild_id', true), '')
                  )::int
              AND p.policy <> 'open'
              AND (
                  -- The provider this guild names, if it names one: the
                  -- session came through it, and this community counts the
                  -- arrival as one of its own.
                  (
                      p.provider_id IS NOT NULL
                      AND NOT public.guild_connection_satisfied(
                            p.guild_id, p.provider_id
                          )
                  )
                  -- Or the account's own second factor, where the community
                  -- asks for one. The session records it when a code is
                  -- presented and the request carries that here.
                  OR (
                      'totp' = ANY(p.require_methods)
                      AND NOT ('mfa' = ANY(public.session_amr()))
                  )
                  -- Or a passkey, where the community asks for one. Its own
                  -- leg rather than the factor's: an assertion records the
                  -- second factor too, so the two are asked for separately.
                  -- Either kind of key answers, which is what the overlap says.
                  OR (
                      'passkey' = ANY(p.require_methods)
                      AND NOT (public.session_amr() && ARRAY['hwk', 'swk'])
                  )
                  -- Or any of its own, whichever provider served it. Named
                  -- rather than counted, so a list holding some other method
                  -- is not read as this one.
                  OR (
                      'sso' = ANY(p.require_methods)
                      AND NOT public.guild_connection_satisfied(p.guild_id)
                  )
              )
        )
        AND NOT EXISTS (
            -- Asked of everybody reaching this community, whatever it says
            -- about how they arrive. Its own row rather than the policy's,
            -- because a community that asks nothing about arrival holds no
            -- policy row and still asks this. Unsatisfied is what this finds,
            -- like the leg above it.
            SELECT 1
            FROM public.guilds g
            WHERE g.id = COALESCE(
                    NULLIF(current_setting('app.current_guild_id', true), ''),
                    NULLIF(current_setting('app.pam_guild_id', true), ''),
                    NULLIF(current_setting('app.settings_guild_id', true), '')
                  )::int
              AND g.require_second_factor
              AND NOT ('mfa' = ANY(public.session_amr()))
        ))
$function$

"""

GUILD_AUTH_SATISFIED_AFTER = """CREATE OR REPLACE FUNCTION public.guild_auth_satisfied()
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT
        -- Pure system routing (no user context) and the explicit sentinel a
        -- user-attributed job sets are not sessions to gate.
        NULLIF(current_setting('app.current_user_id'::text, true), ''::text) IS NULL
        OR current_setting('app.satisfied_providers'::text, true) = 'system'::text
        OR (
        -- What the deployment asks of the account, before what the community
        -- asks of the session. Both have to hold.
        public.platform_factor_satisfied()
        AND NOT EXISTS (
            SELECT 1 FROM public.guild_auth_policies p
            WHERE p.guild_id = (COALESCE(NULLIF(current_setting('app.current_guild_id'::text, true), ''::text), NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text), NULLIF(current_setting('app.settings_guild_id'::text, true), ''::text)))::integer
              AND p.policy <> 'open'
              AND (
                  -- The provider this guild names, if it names one: the
                  -- session came through it, and this community counts the
                  -- arrival as one of its own.
                  (
                      p.provider_id IS NOT NULL
                      AND NOT public.guild_connection_satisfied(
                            p.guild_id, p.provider_id
                          )
                  )
                  -- Or the account's own second factor, where the community
                  -- asks for one. The session records it when a code is
                  -- presented and the request carries that here.
                  OR (
                      'totp' = ANY(p.require_methods)
                      AND NOT ('mfa' = ANY(public.session_amr()))
                  )
                  -- Or a passkey, where the community asks for one. Its own
                  -- leg rather than the factor's: an assertion records the
                  -- second factor too, so the two are asked for separately.
                  -- Either kind of key answers, which is what the overlap says.
                  OR (
                      'passkey' = ANY(p.require_methods)
                      AND NOT (public.session_amr() && ARRAY['hwk', 'swk'])
                  )
                  -- Or any of its own, whichever provider served it. Named
                  -- rather than counted, so a list holding some other method
                  -- is not read as this one.
                  OR (
                      'sso' = ANY(p.require_methods)
                      AND NOT public.guild_connection_satisfied(p.guild_id)
                  )
              )
        )
        AND NOT EXISTS (
            -- Asked of everybody reaching this community, whatever it says
            -- about how they arrive. Its own row rather than the policy's,
            -- because a community that asks nothing about arrival holds no
            -- policy row and still asks this. Unsatisfied is what this finds,
            -- like the leg above it.
            SELECT 1
            FROM public.guilds g
            WHERE g.id = (COALESCE(NULLIF(current_setting('app.current_guild_id'::text, true), ''::text), NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text), NULLIF(current_setting('app.settings_guild_id'::text, true), ''::text)))::integer
              AND g.require_second_factor
              AND NOT ('mfa' = ANY(public.session_amr()))
        ))
$function$

"""

GUILD_SUPERADMIN_BEFORE = """CREATE OR REPLACE FUNCTION public.guild_superadmin(p_guild_id integer, p_user_id integer)
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT EXISTS (
        SELECT 1
        FROM public.guild_memberships m
        WHERE m.guild_id = p_guild_id
          AND m.user_id = p_user_id
          AND m.role = 'superadmin'
    )
    -- A live superadmin settings grant satisfies the same predicate.
    OR EXISTS (
        SELECT 1
        FROM public.access_grants g
        WHERE g.guild_id = p_guild_id
          AND g.user_id = p_user_id
          AND g.purpose = 'settings'
          AND g.access_level = 'superadmin'
          AND g.status = 'approved'
          AND g.expires_at > now()
    )
$function$

"""

GUILD_SUPERADMIN_AFTER = """CREATE OR REPLACE FUNCTION public.guild_superadmin(p_guild_id integer, p_user_id integer)
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT EXISTS (
        SELECT 1
        FROM public.guild_memberships m
        WHERE m.guild_id = p_guild_id
          AND m.user_id = p_user_id
          AND m.role = 'superadmin'
    )
    -- A live superadmin settings grant satisfies the same predicate.
    OR EXISTS (
        SELECT 1
        FROM public.access_grants g
        WHERE g.guild_id = p_guild_id
          AND g.user_id = p_user_id
          AND g.purpose = 'settings'
          AND g.access_level = 'superadmin'
          AND g.status = 'approved' AND g.expires_at > now()
    )
$function$

"""

OWNS_FUNCTION_BEFORE = """
CREATE OR REPLACE FUNCTION public.fn_install_owns_what_it_creates() RETURNS trigger
    LANGUAGE plpgsql AS $owns$
DECLARE
    v_install integer := NULLIF(
        current_setting('app.current_install_id', true), ''
    )::integer;
    v_member integer := NULLIF(
        current_setting('app.current_user_id', true), ''
    )::integer;
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

#: (before, after), in dependency order: ``guild_auth_satisfied`` calls the
#: three before it.
_BODIES = (
    (GUILD_CONNECTION_SATISFIED_BEFORE, GUILD_CONNECTION_SATISFIED_AFTER),
    (SESSION_AMR_BEFORE, SESSION_AMR_AFTER),
    (PLATFORM_FACTOR_SATISFIED_BEFORE, PLATFORM_FACTOR_SATISFIED_AFTER),
    (GUILD_AUTH_SATISFIED_BEFORE, GUILD_AUTH_SATISFIED_AFTER),
    (GUILD_SUPERADMIN_BEFORE, GUILD_SUPERADMIN_AFTER),
)


def upgrade() -> None:
    bind = op.get_bind()
    for _before, after in _BODIES:
        bind.exec_driver_sql(after)
    op.execute(OWNS_FUNCTION_AFTER)


def downgrade() -> None:
    bind = op.get_bind()
    for before, _after in reversed(_BODIES):
        bind.exec_driver_sql(before)
    op.execute(OWNS_FUNCTION_BEFORE)
