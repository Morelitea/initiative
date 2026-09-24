"""an install answers to its scopes

An installed app's standing (20260924_0379) names the resources its scopes let
it read and write. This revision makes every gate an install passes through
ask it.

- Tool content asks the governing tool's scope: read for SELECT, write for
  every other command. A token narrowed to one initiative reaches rows of an
  initiative and none of the community's own. Both are inline legs in the
  policies, rendered at boot from ``app.db.initiative_rls``; ``entity_access``
  carries the same legs in its tool arms, and is restated here.
- Sharing reaches an install through a grant naming it. ``resource_access``
  and ``resource_level`` gain that leg, and are restated here.
- An install owns what it creates. ``public.fn_install_owns_what_it_creates``
  is an AFTER INSERT trigger on each tool's table, in every guild schema and
  the template: when the request is an install's and names no person, it
  writes the owner grant naming the install. It is the one way an install's
  request writes a grant; the policy on ``resource_grants`` admits that row
  from a trigger and no other.
- The tables no tool governs carry RESTRICTIVE ``app_scope_*`` policies,
  rendered at boot from ``app.db.app_rls``.

A person's request carries no install, and each leg answers for it with its
first comparison. The bodies are stated here in full, as they were and as they
become, so this revision reads the same whatever the modules say later.

Revision ID: 20260924_0380
Revises: 20260924_0379
Create Date: 2026-09-24
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import guild_schema_names, run_for_each_guild_schema

revision = "20260924_0380"
down_revision = "20260924_0379"
branch_labels = None
depends_on = None

#: What a rendered guild schema is found by: the render creates every gate
#: together, so a schema holding this one holds the others.
RESOURCE_ACCESS_SIG = (
    "resource_access(text, integer, integer, integer, boolean, public.standing)"
)

#: Each tool's table and the value its grants name it by, as ``Tool`` said at
#: this revision.
TOOL_TABLES: tuple[tuple[str, str], ...] = (
    ("projects", "project"),
    ("documents", "document"),
    ("queues", "queue"),
    ("counter_groups", "counter_group"),
    ("calendars", "calendar"),
    ("dashboards", "dashboard"),
    ("posts", "post"),
    ("galleries", "gallery"),
    ("wikis", "wiki"),
)

#: Shared, in ``public``; each guild schema attaches it to every tool table
#: with that tool's value as its argument. The grant lands in the schema the
#: trigger fired in, whatever the caller's search_path.
OWNS_FUNCTION = """
CREATE OR REPLACE FUNCTION public.fn_install_owns_what_it_creates() RETURNS trigger
    LANGUAGE plpgsql AS $owns$
DECLARE
    v_install integer := NULLIF(
        current_setting('app.current_install_id', true), ''
    )::integer;
BEGIN
    IF v_install IS NOT NULL
       AND NULLIF(current_setting('app.current_user_id', true), '') IS NULL THEN
        EXECUTE format(
            'INSERT INTO %I.resource_grants '
            '(resource_type, resource_id, initiative_id, app_install_id, level, '
            'all_initiative_members, created_at) '
            'VALUES ($1, $2, $3, $4, ''owner'', false, now())',
            TG_TABLE_SCHEMA
        ) USING TG_ARGV[0], NEW.id, NEW.initiative_id, v_install;
    END IF;
    RETURN NULL;
END;
$owns$;
"""


def _owns_trigger(table: str) -> str:
    return f"tr_{table}_install_owns"


#: The tables whose ``app_scope_*`` policies the render adds, for the
#: downgrade to remove.
APP_POLICY_TABLES = (
    "comments",
    "event_outbox",
    "initiative_members",
    "initiative_roles",
    "initiatives",
    "property_definitions",
    "reaction_digest_items",
    "reactions",
    "recent_views",
    "relationships",
    "resource_grants",
    "search_entries",
    "tags",
    "webhook_subscriptions",
)
APP_POLICY_NAMES = (
    "app_scope_select",
    "app_scope_insert",
    "app_scope_update",
    "app_scope_delete",
)

#: ``resource_access`` before this revision.
RESOURCE_ACCESS_BEFORE = """\
CREATE OR REPLACE FUNCTION resource_access(p_tool text, p_resource_id integer, p_user_id integer, p_initiative_id integer, p_need_write boolean, p_st standing)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN
        p_tool IS NULL
        OR (p_st).system_session
        OR (p_st).guild_admin
        OR ((p_st).this_guild
            AND p_initiative_id = ANY ((p_st).override_initiatives))
        OR (CASE WHEN p_need_write THEN (p_st).pam_write ELSE (p_st).pam_read OR (p_st).pam_write END)
        OR EXISTS (
            SELECT 1 FROM resource_grants g
            WHERE g.resource_type = p_tool
              AND g.resource_id = p_resource_id
              AND (
                   g.user_id = p_user_id
                OR ((p_st).this_guild
                    AND g.role_id = ANY ((p_st).member_role_ids))
                OR (g.all_initiative_members
                    AND (p_st).this_guild
                    AND (g.initiative_id IS NULL
                         OR g.initiative_id = ANY ((p_st).member_initiatives)))
                OR (g.dashboard_id IS NOT NULL
                    AND g.dashboard_id = (p_st).via_dashboard_id)
              )
              AND (NOT p_need_write OR g.level IN ('write', 'owner'))
        )
    ;
END
$function$

"""

#: ``resource_access``, reaching a grant that names the install.
RESOURCE_ACCESS_AFTER = """\
CREATE OR REPLACE FUNCTION resource_access(p_tool text, p_resource_id integer, p_user_id integer, p_initiative_id integer, p_need_write boolean, p_st standing)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN
        p_tool IS NULL
        OR (p_st).system_session
        OR (p_st).guild_admin
        OR ((p_st).this_guild
            AND p_initiative_id = ANY ((p_st).override_initiatives))
        OR (CASE WHEN p_need_write THEN (p_st).pam_write ELSE (p_st).pam_read OR (p_st).pam_write END)
        OR EXISTS (
            SELECT 1 FROM resource_grants g
            WHERE g.resource_type = p_tool
              AND g.resource_id = p_resource_id
              AND (
                   g.user_id = p_user_id
                OR ((p_st).this_guild
                    AND g.role_id = ANY ((p_st).member_role_ids))
                OR (g.all_initiative_members
                    AND (p_st).this_guild
                    AND (g.initiative_id IS NULL
                         OR g.initiative_id = ANY ((p_st).member_initiatives)))
                OR (g.dashboard_id IS NOT NULL
                    AND g.dashboard_id = (p_st).via_dashboard_id)
                OR (g.app_install_id IS NOT NULL
                    AND g.app_install_id = (p_st).install_id)
              )
              AND (NOT p_need_write OR g.level IN ('write', 'owner'))
        )
    ;
END
$function$

"""

#: ``resource_level`` before this revision.
RESOURCE_LEVEL_BEFORE = """\
CREATE OR REPLACE FUNCTION resource_level(p_tool text, p_resource_id integer, p_user_id integer, p_initiative_id integer, p_st standing)
 RETURNS text
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
    v_level text;
BEGIN
    IF p_tool IS NULL
        OR (p_st).system_session
        OR (p_st).guild_admin
        OR ((p_st).this_guild
            AND p_initiative_id = ANY ((p_st).override_initiatives))
    THEN
        RETURN 'owner';
    END IF;
    SELECT CASE
             WHEN bool_or(g.level = 'owner') THEN 'owner'
             WHEN bool_or(g.level = 'write') THEN 'write'
             WHEN count(*) > 0 THEN 'read'
           END
      INTO v_level
      FROM resource_grants g
     WHERE g.resource_type = p_tool
              AND g.resource_id = p_resource_id
              AND (
                   g.user_id = p_user_id
                OR ((p_st).this_guild
                    AND g.role_id = ANY ((p_st).member_role_ids))
                OR (g.all_initiative_members
                    AND (p_st).this_guild
                    AND (g.initiative_id IS NULL
                         OR g.initiative_id = ANY ((p_st).member_initiatives)))
                OR (g.dashboard_id IS NOT NULL
                    AND g.dashboard_id = (p_st).via_dashboard_id)
              );
    IF (p_st).pam_write
       AND v_level IS DISTINCT FROM 'owner' THEN
        RETURN 'write';
    END IF;
    IF (p_st).pam_read AND v_level IS NULL THEN
        RETURN 'read';
    END IF;
    RETURN v_level;
END
$function$

"""

#: ``resource_level``, reaching a grant that names the install.
RESOURCE_LEVEL_AFTER = """\
CREATE OR REPLACE FUNCTION resource_level(p_tool text, p_resource_id integer, p_user_id integer, p_initiative_id integer, p_st standing)
 RETURNS text
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
    v_level text;
BEGIN
    IF p_tool IS NULL
        OR (p_st).system_session
        OR (p_st).guild_admin
        OR ((p_st).this_guild
            AND p_initiative_id = ANY ((p_st).override_initiatives))
    THEN
        RETURN 'owner';
    END IF;
    SELECT CASE
             WHEN bool_or(g.level = 'owner') THEN 'owner'
             WHEN bool_or(g.level = 'write') THEN 'write'
             WHEN count(*) > 0 THEN 'read'
           END
      INTO v_level
      FROM resource_grants g
     WHERE g.resource_type = p_tool
              AND g.resource_id = p_resource_id
              AND (
                   g.user_id = p_user_id
                OR ((p_st).this_guild
                    AND g.role_id = ANY ((p_st).member_role_ids))
                OR (g.all_initiative_members
                    AND (p_st).this_guild
                    AND (g.initiative_id IS NULL
                         OR g.initiative_id = ANY ((p_st).member_initiatives)))
                OR (g.dashboard_id IS NOT NULL
                    AND g.dashboard_id = (p_st).via_dashboard_id)
                OR (g.app_install_id IS NOT NULL
                    AND g.app_install_id = (p_st).install_id)
              );
    IF (p_st).pam_write
       AND v_level IS DISTINCT FROM 'owner' THEN
        RETURN 'write';
    END IF;
    IF (p_st).pam_read AND v_level IS NULL THEN
        RETURN 'read';
    END IF;
    RETURN v_level;
END
$function$

"""

#: ``entity_access`` before this revision.
ENTITY_ACCESS_BEFORE = """
CREATE OR REPLACE FUNCTION entity_access(
    p_kind text, p_entity_id integer, p_need_write boolean, p_need_share_write boolean,
    p_st standing
) RETURNS boolean
    LANGUAGE plpgsql STABLE
    AS $entity_access$
BEGIN
    CASE p_kind
        WHEN 'calendar' THEN
            RETURN EXISTS (SELECT 1 FROM calendars re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (initiative_access(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st))) AND (NOT p_need_share_write OR (((((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR re.initiative_id IS NULL OR ((p_st).this_guild AND (re.initiative_id::text || ':calendar') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'calendars_enabled', false, p_st) AND resource_access('calendar', re.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, re.initiative_id, true, p_st))))));
        WHEN 'calendar_event' THEN
            RETURN EXISTS (SELECT 1 FROM calendar_events re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (EXISTS (SELECT 1 FROM calendars WHERE calendars.id = re.calendar_id AND initiative_access(calendars.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st)))) AND (NOT p_need_share_write OR (EXISTS (SELECT 1 FROM calendars dac WHERE dac.id = re.calendar_id AND ((((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR dac.initiative_id IS NULL OR ((p_st).this_guild AND (dac.initiative_id::text || ':calendar') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(dac.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'calendars_enabled', false, p_st) AND resource_access('calendar', dac.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, dac.initiative_id, true, p_st)))))));
        WHEN 'comment' THEN
            RETURN EXISTS (SELECT 1 FROM comments re WHERE re.id = p_entity_id AND ((NOT p_need_write AND NOT p_need_share_write) OR entity_access((CASE WHEN re.task_id IS NOT NULL THEN 'task' WHEN re.wiki_page_id IS NOT NULL THEN 'wiki_page' WHEN re.project_id IS NOT NULL THEN 'project' WHEN re.document_id IS NOT NULL THEN 'document' WHEN re.queue_id IS NOT NULL THEN 'queue' WHEN re.counter_group_id IS NOT NULL THEN 'counter_group' WHEN re.calendar_id IS NOT NULL THEN 'calendar' WHEN re.dashboard_id IS NOT NULL THEN 'dashboard' WHEN re.post_id IS NOT NULL THEN 'post' WHEN re.gallery_id IS NOT NULL THEN 'gallery' WHEN re.wiki_id IS NOT NULL THEN 'wiki' END), COALESCE(re.task_id, re.wiki_page_id, re.project_id, re.document_id, re.queue_id, re.counter_group_id, re.calendar_id, re.dashboard_id, re.post_id, re.gallery_id, re.wiki_id), p_need_write, p_need_share_write, p_st)));
        WHEN 'counter' THEN
            RETURN EXISTS (SELECT 1 FROM counters re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (EXISTS (SELECT 1 FROM counter_groups WHERE counter_groups.id = re.counter_group_id AND initiative_access(counter_groups.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st)))) AND (NOT p_need_share_write OR (EXISTS (SELECT 1 FROM counter_groups dac WHERE dac.id = re.counter_group_id AND ((((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR dac.initiative_id IS NULL OR ((p_st).this_guild AND (dac.initiative_id::text || ':counter_group') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(dac.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'counter_groups_enabled', false, p_st) AND resource_access('counter_group', dac.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, dac.initiative_id, true, p_st)))))));
        WHEN 'counter_group' THEN
            RETURN EXISTS (SELECT 1 FROM counter_groups re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (initiative_access(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st))) AND (NOT p_need_share_write OR (((((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR re.initiative_id IS NULL OR ((p_st).this_guild AND (re.initiative_id::text || ':counter_group') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'counter_groups_enabled', false, p_st) AND resource_access('counter_group', re.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, re.initiative_id, true, p_st))))));
        WHEN 'dashboard' THEN
            RETURN EXISTS (SELECT 1 FROM dashboards re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (initiative_access(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st))) AND (NOT p_need_share_write OR (((((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR re.initiative_id IS NULL OR ((p_st).this_guild AND (re.initiative_id::text || ':dashboard') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'dashboards_enabled', false, p_st) AND resource_access('dashboard', re.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, re.initiative_id, true, p_st))))));
        WHEN 'document' THEN
            RETURN EXISTS (SELECT 1 FROM documents re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (initiative_access(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st))) AND (NOT p_need_share_write OR (((((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR re.initiative_id IS NULL OR ((p_st).this_guild AND (re.initiative_id::text || ':document') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'documents_enabled', true, p_st) AND resource_access('document', re.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, re.initiative_id, true, p_st))))));
        WHEN 'gallery' THEN
            RETURN EXISTS (SELECT 1 FROM galleries re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (initiative_access(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st))) AND (NOT p_need_share_write OR (((((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR re.initiative_id IS NULL OR ((p_st).this_guild AND (re.initiative_id::text || ':gallery') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'galleries_enabled', false, p_st) AND resource_access('gallery', re.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, re.initiative_id, true, p_st))))));
        WHEN 'gallery_image' THEN
            RETURN EXISTS (SELECT 1 FROM gallery_images re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (EXISTS (SELECT 1 FROM galleries WHERE galleries.id = re.gallery_id AND initiative_access(galleries.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st)))) AND (NOT p_need_share_write OR (EXISTS (SELECT 1 FROM galleries dac WHERE dac.id = re.gallery_id AND ((((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR dac.initiative_id IS NULL OR ((p_st).this_guild AND (dac.initiative_id::text || ':gallery') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(dac.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'galleries_enabled', false, p_st) AND resource_access('gallery', dac.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, dac.initiative_id, true, p_st)))))));
        WHEN 'post' THEN
            RETURN EXISTS (SELECT 1 FROM posts re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (initiative_access(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st))) AND (NOT p_need_share_write OR (((((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR re.initiative_id IS NULL OR ((p_st).this_guild AND (re.initiative_id::text || ':post') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'posts_enabled', false, p_st) AND resource_access('post', re.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, re.initiative_id, true, p_st))))));
        WHEN 'project' THEN
            RETURN EXISTS (SELECT 1 FROM projects re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (initiative_access(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st))) AND (NOT p_need_share_write OR (((((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR re.initiative_id IS NULL OR ((p_st).this_guild AND (re.initiative_id::text || ':project') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'projects_enabled', true, p_st) AND resource_access('project', re.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, re.initiative_id, true, p_st))))));
        WHEN 'queue' THEN
            RETURN EXISTS (SELECT 1 FROM queues re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (initiative_access(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st))) AND (NOT p_need_share_write OR (((((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR re.initiative_id IS NULL OR ((p_st).this_guild AND (re.initiative_id::text || ':queue') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'queues_enabled', false, p_st) AND resource_access('queue', re.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, re.initiative_id, true, p_st))))));
        WHEN 'queue_item' THEN
            RETURN EXISTS (SELECT 1 FROM queue_items re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (EXISTS (SELECT 1 FROM queues WHERE queues.id = re.queue_id AND initiative_access(queues.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st)))) AND (NOT p_need_share_write OR (EXISTS (SELECT 1 FROM queues dac WHERE dac.id = re.queue_id AND ((((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR dac.initiative_id IS NULL OR ((p_st).this_guild AND (dac.initiative_id::text || ':queue') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(dac.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'queues_enabled', false, p_st) AND resource_access('queue', dac.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, dac.initiative_id, true, p_st)))))));
        WHEN 'tag' THEN
            RETURN EXISTS (SELECT 1 FROM tags re WHERE re.id = p_entity_id AND (TRUE));
        WHEN 'task' THEN
            RETURN EXISTS (SELECT 1 FROM tasks re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (EXISTS (SELECT 1 FROM projects WHERE projects.id = re.project_id AND initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st)))) AND (NOT p_need_share_write OR (EXISTS (SELECT 1 FROM projects dac WHERE dac.id = re.project_id AND ((((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR dac.initiative_id IS NULL OR ((p_st).this_guild AND (dac.initiative_id::text || ':project') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(dac.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'projects_enabled', true, p_st) AND resource_access('project', dac.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, dac.initiative_id, true, p_st)))))));
        WHEN 'wiki' THEN
            RETURN EXISTS (SELECT 1 FROM wikis re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (initiative_access(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st))) AND (NOT p_need_share_write OR (((((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR re.initiative_id IS NULL OR ((p_st).this_guild AND (re.initiative_id::text || ':wiki') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'wikis_enabled', false, p_st) AND resource_access('wiki', re.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, re.initiative_id, true, p_st))))));
        WHEN 'wiki_page' THEN
            RETURN EXISTS (SELECT 1 FROM wiki_pages re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (EXISTS (SELECT 1 FROM wikis WHERE wikis.id = re.wiki_id AND initiative_access(wikis.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st)))) AND (NOT p_need_share_write OR (EXISTS (SELECT 1 FROM wikis dac WHERE dac.id = re.wiki_id AND ((((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR dac.initiative_id IS NULL OR ((p_st).this_guild AND (dac.initiative_id::text || ':wiki') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(dac.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'wikis_enabled', false, p_st) AND resource_access('wiki', dac.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, dac.initiative_id, true, p_st)))))));
        ELSE
            RETURN false;
    END CASE;
END;
$entity_access$;
"""

#: ``entity_access``, its tool arms asking an install's scopes.
ENTITY_ACCESS_AFTER = """
CREATE OR REPLACE FUNCTION entity_access(
    p_kind text, p_entity_id integer, p_need_write boolean, p_need_share_write boolean,
    p_st standing
) RETURNS boolean
    LANGUAGE plpgsql STABLE
    AS $entity_access$
BEGIN
    CASE p_kind
        WHEN 'calendar' THEN
            RETURN EXISTS (SELECT 1 FROM calendars re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (initiative_access(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st))) AND (NOT p_need_share_write OR ((((p_st).install_id IS NULL OR 'calendars' = ANY ((p_st).install_write)) AND ((p_st).install_id IS NULL OR (p_st).scope_initiative_id IS NULL OR re.initiative_id IS NOT NULL) AND (((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR re.initiative_id IS NULL OR ((p_st).this_guild AND (re.initiative_id::text || ':calendar') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'calendars_enabled', false, p_st) AND resource_access('calendar', re.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, re.initiative_id, true, p_st))))));
        WHEN 'calendar_event' THEN
            RETURN EXISTS (SELECT 1 FROM calendar_events re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (EXISTS (SELECT 1 FROM calendars WHERE calendars.id = re.calendar_id AND initiative_access(calendars.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st)))) AND (NOT p_need_share_write OR (EXISTS (SELECT 1 FROM calendars dac WHERE dac.id = re.calendar_id AND (((p_st).install_id IS NULL OR 'calendars' = ANY ((p_st).install_write)) AND ((p_st).install_id IS NULL OR (p_st).scope_initiative_id IS NULL OR dac.initiative_id IS NOT NULL) AND (((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR dac.initiative_id IS NULL OR ((p_st).this_guild AND (dac.initiative_id::text || ':calendar') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(dac.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'calendars_enabled', false, p_st) AND resource_access('calendar', dac.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, dac.initiative_id, true, p_st)))))));
        WHEN 'comment' THEN
            RETURN EXISTS (SELECT 1 FROM comments re WHERE re.id = p_entity_id AND ((NOT p_need_write AND NOT p_need_share_write) OR entity_access((CASE WHEN re.task_id IS NOT NULL THEN 'task' WHEN re.wiki_page_id IS NOT NULL THEN 'wiki_page' WHEN re.project_id IS NOT NULL THEN 'project' WHEN re.document_id IS NOT NULL THEN 'document' WHEN re.queue_id IS NOT NULL THEN 'queue' WHEN re.counter_group_id IS NOT NULL THEN 'counter_group' WHEN re.calendar_id IS NOT NULL THEN 'calendar' WHEN re.dashboard_id IS NOT NULL THEN 'dashboard' WHEN re.post_id IS NOT NULL THEN 'post' WHEN re.gallery_id IS NOT NULL THEN 'gallery' WHEN re.wiki_id IS NOT NULL THEN 'wiki' END), COALESCE(re.task_id, re.wiki_page_id, re.project_id, re.document_id, re.queue_id, re.counter_group_id, re.calendar_id, re.dashboard_id, re.post_id, re.gallery_id, re.wiki_id), p_need_write, p_need_share_write, p_st)));
        WHEN 'counter' THEN
            RETURN EXISTS (SELECT 1 FROM counters re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (EXISTS (SELECT 1 FROM counter_groups WHERE counter_groups.id = re.counter_group_id AND initiative_access(counter_groups.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st)))) AND (NOT p_need_share_write OR (EXISTS (SELECT 1 FROM counter_groups dac WHERE dac.id = re.counter_group_id AND (((p_st).install_id IS NULL OR 'counter_groups' = ANY ((p_st).install_write)) AND ((p_st).install_id IS NULL OR (p_st).scope_initiative_id IS NULL OR dac.initiative_id IS NOT NULL) AND (((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR dac.initiative_id IS NULL OR ((p_st).this_guild AND (dac.initiative_id::text || ':counter_group') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(dac.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'counter_groups_enabled', false, p_st) AND resource_access('counter_group', dac.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, dac.initiative_id, true, p_st)))))));
        WHEN 'counter_group' THEN
            RETURN EXISTS (SELECT 1 FROM counter_groups re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (initiative_access(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st))) AND (NOT p_need_share_write OR ((((p_st).install_id IS NULL OR 'counter_groups' = ANY ((p_st).install_write)) AND ((p_st).install_id IS NULL OR (p_st).scope_initiative_id IS NULL OR re.initiative_id IS NOT NULL) AND (((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR re.initiative_id IS NULL OR ((p_st).this_guild AND (re.initiative_id::text || ':counter_group') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'counter_groups_enabled', false, p_st) AND resource_access('counter_group', re.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, re.initiative_id, true, p_st))))));
        WHEN 'dashboard' THEN
            RETURN EXISTS (SELECT 1 FROM dashboards re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (initiative_access(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st))) AND (NOT p_need_share_write OR ((((p_st).install_id IS NULL OR 'dashboards' = ANY ((p_st).install_write)) AND ((p_st).install_id IS NULL OR (p_st).scope_initiative_id IS NULL OR re.initiative_id IS NOT NULL) AND (((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR re.initiative_id IS NULL OR ((p_st).this_guild AND (re.initiative_id::text || ':dashboard') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'dashboards_enabled', false, p_st) AND resource_access('dashboard', re.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, re.initiative_id, true, p_st))))));
        WHEN 'document' THEN
            RETURN EXISTS (SELECT 1 FROM documents re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (initiative_access(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st))) AND (NOT p_need_share_write OR ((((p_st).install_id IS NULL OR 'documents' = ANY ((p_st).install_write)) AND ((p_st).install_id IS NULL OR (p_st).scope_initiative_id IS NULL OR re.initiative_id IS NOT NULL) AND (((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR re.initiative_id IS NULL OR ((p_st).this_guild AND (re.initiative_id::text || ':document') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'documents_enabled', true, p_st) AND resource_access('document', re.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, re.initiative_id, true, p_st))))));
        WHEN 'gallery' THEN
            RETURN EXISTS (SELECT 1 FROM galleries re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (initiative_access(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st))) AND (NOT p_need_share_write OR ((((p_st).install_id IS NULL OR 'galleries' = ANY ((p_st).install_write)) AND ((p_st).install_id IS NULL OR (p_st).scope_initiative_id IS NULL OR re.initiative_id IS NOT NULL) AND (((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR re.initiative_id IS NULL OR ((p_st).this_guild AND (re.initiative_id::text || ':gallery') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'galleries_enabled', false, p_st) AND resource_access('gallery', re.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, re.initiative_id, true, p_st))))));
        WHEN 'gallery_image' THEN
            RETURN EXISTS (SELECT 1 FROM gallery_images re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (EXISTS (SELECT 1 FROM galleries WHERE galleries.id = re.gallery_id AND initiative_access(galleries.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st)))) AND (NOT p_need_share_write OR (EXISTS (SELECT 1 FROM galleries dac WHERE dac.id = re.gallery_id AND (((p_st).install_id IS NULL OR 'galleries' = ANY ((p_st).install_write)) AND ((p_st).install_id IS NULL OR (p_st).scope_initiative_id IS NULL OR dac.initiative_id IS NOT NULL) AND (((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR dac.initiative_id IS NULL OR ((p_st).this_guild AND (dac.initiative_id::text || ':gallery') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(dac.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'galleries_enabled', false, p_st) AND resource_access('gallery', dac.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, dac.initiative_id, true, p_st)))))));
        WHEN 'post' THEN
            RETURN EXISTS (SELECT 1 FROM posts re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (initiative_access(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st))) AND (NOT p_need_share_write OR ((((p_st).install_id IS NULL OR 'posts' = ANY ((p_st).install_write)) AND ((p_st).install_id IS NULL OR (p_st).scope_initiative_id IS NULL OR re.initiative_id IS NOT NULL) AND (((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR re.initiative_id IS NULL OR ((p_st).this_guild AND (re.initiative_id::text || ':post') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'posts_enabled', false, p_st) AND resource_access('post', re.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, re.initiative_id, true, p_st))))));
        WHEN 'project' THEN
            RETURN EXISTS (SELECT 1 FROM projects re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (initiative_access(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st))) AND (NOT p_need_share_write OR ((((p_st).install_id IS NULL OR 'projects' = ANY ((p_st).install_write)) AND ((p_st).install_id IS NULL OR (p_st).scope_initiative_id IS NULL OR re.initiative_id IS NOT NULL) AND (((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR re.initiative_id IS NULL OR ((p_st).this_guild AND (re.initiative_id::text || ':project') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'projects_enabled', true, p_st) AND resource_access('project', re.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, re.initiative_id, true, p_st))))));
        WHEN 'queue' THEN
            RETURN EXISTS (SELECT 1 FROM queues re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (initiative_access(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st))) AND (NOT p_need_share_write OR ((((p_st).install_id IS NULL OR 'queues' = ANY ((p_st).install_write)) AND ((p_st).install_id IS NULL OR (p_st).scope_initiative_id IS NULL OR re.initiative_id IS NOT NULL) AND (((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR re.initiative_id IS NULL OR ((p_st).this_guild AND (re.initiative_id::text || ':queue') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'queues_enabled', false, p_st) AND resource_access('queue', re.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, re.initiative_id, true, p_st))))));
        WHEN 'queue_item' THEN
            RETURN EXISTS (SELECT 1 FROM queue_items re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (EXISTS (SELECT 1 FROM queues WHERE queues.id = re.queue_id AND initiative_access(queues.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st)))) AND (NOT p_need_share_write OR (EXISTS (SELECT 1 FROM queues dac WHERE dac.id = re.queue_id AND (((p_st).install_id IS NULL OR 'queues' = ANY ((p_st).install_write)) AND ((p_st).install_id IS NULL OR (p_st).scope_initiative_id IS NULL OR dac.initiative_id IS NOT NULL) AND (((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR dac.initiative_id IS NULL OR ((p_st).this_guild AND (dac.initiative_id::text || ':queue') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(dac.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'queues_enabled', false, p_st) AND resource_access('queue', dac.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, dac.initiative_id, true, p_st)))))));
        WHEN 'tag' THEN
            RETURN EXISTS (SELECT 1 FROM tags re WHERE re.id = p_entity_id AND (TRUE));
        WHEN 'task' THEN
            RETURN EXISTS (SELECT 1 FROM tasks re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (EXISTS (SELECT 1 FROM projects WHERE projects.id = re.project_id AND initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st)))) AND (NOT p_need_share_write OR (EXISTS (SELECT 1 FROM projects dac WHERE dac.id = re.project_id AND (((p_st).install_id IS NULL OR 'projects' = ANY ((p_st).install_write)) AND ((p_st).install_id IS NULL OR (p_st).scope_initiative_id IS NULL OR dac.initiative_id IS NOT NULL) AND (((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR dac.initiative_id IS NULL OR ((p_st).this_guild AND (dac.initiative_id::text || ':project') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(dac.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'projects_enabled', true, p_st) AND resource_access('project', dac.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, dac.initiative_id, true, p_st)))))));
        WHEN 'wiki' THEN
            RETURN EXISTS (SELECT 1 FROM wikis re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (initiative_access(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st))) AND (NOT p_need_share_write OR ((((p_st).install_id IS NULL OR 'wikis' = ANY ((p_st).install_write)) AND ((p_st).install_id IS NULL OR (p_st).scope_initiative_id IS NULL OR re.initiative_id IS NOT NULL) AND (((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR re.initiative_id IS NULL OR ((p_st).this_guild AND (re.initiative_id::text || ':wiki') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(re.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'wikis_enabled', false, p_st) AND resource_access('wiki', re.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, re.initiative_id, true, p_st))))));
        WHEN 'wiki_page' THEN
            RETURN EXISTS (SELECT 1 FROM wiki_pages re WHERE re.id = p_entity_id AND ((NOT p_need_write OR (EXISTS (SELECT 1 FROM wikis WHERE wikis.id = re.wiki_id AND initiative_access(wikis.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true, p_st)))) AND (NOT p_need_share_write OR (EXISTS (SELECT 1 FROM wikis dac WHERE dac.id = re.wiki_id AND (((p_st).install_id IS NULL OR 'wikis' = ANY ((p_st).install_write)) AND ((p_st).install_id IS NULL OR (p_st).scope_initiative_id IS NULL OR dac.initiative_id IS NOT NULL) AND (((p_st).system_session OR (p_st).guild_admin) OR ((p_st).pam_read OR (p_st).pam_write) OR dac.initiative_id IS NULL OR ((p_st).this_guild AND (dac.initiative_id::text || ':wiki') = ANY ((p_st).enabled_tools))) AND initiative_role_permits(dac.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, 'wikis_enabled', false, p_st) AND resource_access('wiki', dac.id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, dac.initiative_id, true, p_st)))))));
        ELSE
            RETURN false;
    END CASE;
END;
$entity_access$;
"""


def _schemas_holding(bind, signature: str) -> list[str]:
    """The guild schemas that carry ``signature``. The template holds structure
    only, and a schema the back-fill has not rendered yet is given the current
    bodies when it is."""
    return [
        schema
        for schema in guild_schema_names(bind)
        if bind.execute(
            sa.text("SELECT to_regprocedure(CAST(:sig AS text)) IS NOT NULL"),
            {"sig": f"{schema}.{signature}"},
        ).scalar()
    ]


def _in_schema(bind, schema: str) -> None:
    bind.execute(
        sa.text("SELECT set_config('search_path', :sp, true)"),
        {"sp": f"{schema}, public"},
    )


def _restate(bind, bodies: tuple[str, ...]) -> None:
    for schema in _schemas_holding(bind, RESOURCE_ACCESS_SIG):
        _in_schema(bind, schema)
        for body in bodies:
            op.execute(body)
    bind.execute(sa.text("SELECT set_config('search_path', 'public', true)"))


def _attach_owns_triggers() -> None:
    for table, tool in TOOL_TABLES:
        op.execute(
            f"CREATE OR REPLACE TRIGGER {_owns_trigger(table)} "
            f"AFTER INSERT ON {table} FOR EACH ROW "
            f"EXECUTE FUNCTION public.fn_install_owns_what_it_creates('{tool}')"
        )


def _detach_owns_triggers() -> None:
    for table, _tool in TOOL_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {_owns_trigger(table)} ON {table}")


def upgrade() -> None:
    bind = op.get_bind()
    _restate(
        bind,
        (RESOURCE_LEVEL_AFTER, RESOURCE_ACCESS_AFTER, ENTITY_ACCESS_AFTER),
    )
    op.execute(OWNS_FUNCTION)
    # The template too, so a guild provisioned later takes the triggers with
    # the rest of its structure.
    run_for_each_guild_schema(bind, _attach_owns_triggers)


def downgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, _detach_owns_triggers)
    # Reachable only from the triggers just dropped.
    op.execute("DROP FUNCTION IF EXISTS public.fn_install_owns_what_it_creates()")
    for schema in guild_schema_names(bind):
        for table in APP_POLICY_TABLES:
            if bind.execute(
                sa.text("SELECT to_regclass(CAST(:t AS text)) IS NOT NULL"),
                {"t": f'"{schema}".{table}'},
            ).scalar():
                for name in APP_POLICY_NAMES:
                    op.execute(f'DROP POLICY IF EXISTS {name} ON "{schema}".{table}')
    _restate(
        bind,
        (RESOURCE_LEVEL_BEFORE, RESOURCE_ACCESS_BEFORE, ENTITY_ACCESS_BEFORE),
    )
