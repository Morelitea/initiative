"""a community's schema is what says which community it is

Forty-three tables inside ``guild_<id>`` carried a ``guild_id`` column holding
the number already in the schema name. Twenty more tables in the same schemas
carried none and worked identically. This removes it everywhere below the guild
boundary, with the indexes, triggers and shared functions that existed only to
keep it filled.

Nothing authorised on it. No row-level-security policy in a guild schema reads
it, and neither do ``initiative_access``, ``resource_access`` or
``resource_frozen`` — isolation is the schema boundary plus the initiative
check, and both are untouched here.

What it cost was the write path. Thirteen tables filled the column from a
``BEFORE INSERT`` trigger that reads the parent row, and the paths that matter
never supplied a value: creating a task ran a lookup against ``projects``, and
creating a comment walked an eleven-branch ``ELSIF`` to decide which parent to
read. Every task, comment, assignee and reaction insert paid for it, and a bulk
import paid once per row.

Five constraints folded the column in and are rebuilt without it. Each is the
same predicate with a leading column removed that is constant inside one
schema, so nothing legal today becomes illegal: one initiative name per
community becomes one per schema, and so on for the default initiative, tag
names, an app's listing, and the webhook dispatch index. ``guild_settings``
kept "one row per community" as a unique index on a constant, which is what
that constraint always meant here.

The eighteen foreign keys to ``public.guilds`` existed in ``guild_template``
alone — provisioning copies intra-schema keys only, so no guild ever had them.
They go with the column, and the downgrade puts them back where they were.

Guild content, so this walks ``guild_template`` and every ``guild_<id>``. The
shared trigger functions live in ``public`` and are dropped once, after the
loop. The downgrade restores the column from the schema name, which is the same
answer the triggers derived and the reason the column was redundant.

Revision ID: 20260921_0347
Revises: 20260921_0346
Create Date: 2026-09-21
"""

import re

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import guild_schema_names

revision = "20260921_0347"
down_revision = "20260921_0346"
branch_labels = None
depends_on = None


#: Every guild-schema table that carried the column, with whether it was NOT NULL.
_TABLES: tuple[tuple[str, bool], ...] = (
    ("calendar_event_attendees", True),
    ("calendar_events", True),
    ("calendars", True),
    ("comments", False),
    ("counter_groups", True),
    ("counters", True),
    ("dashboards", True),
    ("document_file_versions", False),
    ("documents", True),
    ("export_jobs", True),
    ("galleries", True),
    ("gallery_image_versions", True),
    ("gallery_images", True),
    ("guild_ai_connections", False),
    ("guild_ai_member_keys", False),
    ("guild_ai_member_prefs", False),
    ("guild_app_user_connections", True),
    ("guild_app_user_delegations", True),
    ("guild_apps", True),
    ("guild_settings", True),
    ("import_jobs", True),
    ("initiative_members", True),
    ("initiatives", True),
    ("moderation_reports", True),
    ("posts", True),
    ("project_favorites", True),
    ("project_filter_presets", False),
    ("project_orders", True),
    ("projects", True),
    ("queue_items", True),
    ("queues", True),
    ("reactions", False),
    ("recent_views", False),
    ("relationships", False),
    ("resource_grants", True),
    ("tags", True),
    ("task_assignees", True),
    ("task_statuses", True),
    ("tasks", True),
    ("uploads", True),
    ("webhook_subscriptions", True),
    ("wiki_pages", True),
    ("wikis", True),
)

#: The triggers whose only job was to fill it, and the definition to restore.
_TRIGGERS: tuple[tuple[str, str, str], ...] = (
    (
        "comments",
        "tr_comments_set_guild_id",
        "CREATE TRIGGER tr_comments_set_guild_id BEFORE INSERT OR UPDATE OF task_id, wiki_page_id, project_id, document_id, queue_id, counter_group_id, calendar_id, dashboard_id, post_id, gallery_id, wiki_id ON comments FOR EACH ROW EXECUTE FUNCTION fn_comments_set_guild_id()",
    ),
    (
        "documents",
        "tr_documents_set_guild_id",
        "CREATE TRIGGER tr_documents_set_guild_id BEFORE INSERT OR UPDATE OF initiative_id ON documents FOR EACH ROW EXECUTE FUNCTION fn_documents_set_guild_id()",
    ),
    (
        "initiative_members",
        "tr_initiative_members_set_guild_id",
        "CREATE TRIGGER tr_initiative_members_set_guild_id BEFORE INSERT OR UPDATE OF initiative_id ON initiative_members FOR EACH ROW EXECUTE FUNCTION fn_initiative_members_set_guild_id()",
    ),
    (
        "project_favorites",
        "tr_project_favorites_set_guild_id",
        "CREATE TRIGGER tr_project_favorites_set_guild_id BEFORE INSERT OR UPDATE OF project_id ON project_favorites FOR EACH ROW EXECUTE FUNCTION fn_project_favorites_set_guild_id()",
    ),
    (
        "project_filter_presets",
        "tr_project_filter_presets_set_guild_id",
        "CREATE TRIGGER tr_project_filter_presets_set_guild_id BEFORE INSERT OR UPDATE OF project_id ON project_filter_presets FOR EACH ROW EXECUTE FUNCTION fn_project_filter_presets_set_guild_id()",
    ),
    (
        "project_orders",
        "tr_project_orders_set_guild_id",
        "CREATE TRIGGER tr_project_orders_set_guild_id BEFORE INSERT OR UPDATE OF project_id ON project_orders FOR EACH ROW EXECUTE FUNCTION fn_project_orders_set_guild_id()",
    ),
    (
        "projects",
        "tr_projects_set_guild_id",
        "CREATE TRIGGER tr_projects_set_guild_id BEFORE INSERT OR UPDATE OF initiative_id ON projects FOR EACH ROW EXECUTE FUNCTION fn_projects_set_guild_id()",
    ),
    (
        "reactions",
        "tr_reactions_set_guild_id",
        "CREATE TRIGGER tr_reactions_set_guild_id BEFORE INSERT OR UPDATE OF target_type, target_id ON reactions FOR EACH ROW EXECUTE FUNCTION fn_reactions_set_guild_id()",
    ),
    (
        "recent_views",
        "tr_recent_views_set_guild_id",
        "CREATE TRIGGER tr_recent_views_set_guild_id BEFORE INSERT OR UPDATE OF entity_type, entity_id ON recent_views FOR EACH ROW EXECUTE FUNCTION fn_recent_views_set_guild_id()",
    ),
    (
        "relationships",
        "set_guild_id",
        "CREATE TRIGGER set_guild_id BEFORE INSERT OR UPDATE ON relationships FOR EACH ROW EXECUTE FUNCTION fn_relationships_set_guild_id()",
    ),
    (
        "task_assignees",
        "tr_task_assignees_set_guild_id",
        "CREATE TRIGGER tr_task_assignees_set_guild_id BEFORE INSERT OR UPDATE OF task_id ON task_assignees FOR EACH ROW EXECUTE FUNCTION fn_task_assignees_set_guild_id()",
    ),
    (
        "task_statuses",
        "tr_task_statuses_set_guild_id",
        "CREATE TRIGGER tr_task_statuses_set_guild_id BEFORE INSERT OR UPDATE OF project_id ON task_statuses FOR EACH ROW EXECUTE FUNCTION fn_task_statuses_set_guild_id()",
    ),
    (
        "tasks",
        "tr_tasks_set_guild_id",
        "CREATE TRIGGER tr_tasks_set_guild_id BEFORE INSERT OR UPDATE OF project_id ON tasks FOR EACH ROW EXECUTE FUNCTION fn_tasks_set_guild_id()",
    ),
)

#: Indexes over the column (constraint-backed ones are restored with their
#: constraint instead).
_INDEXES: tuple[tuple[str, str], ...] = (
    (
        "ix_calendar_events_guild_id",
        "CREATE INDEX ix_calendar_events_guild_id ON calendar_events USING btree (guild_id)",
    ),
    (
        "ix_calendars_guild_id",
        "CREATE INDEX ix_calendars_guild_id ON calendars USING btree (guild_id)",
    ),
    (
        "ix_counter_groups_guild_id",
        "CREATE INDEX ix_counter_groups_guild_id ON counter_groups USING btree (guild_id)",
    ),
    (
        "ix_counters_guild_id",
        "CREATE INDEX ix_counters_guild_id ON counters USING btree (guild_id)",
    ),
    (
        "ix_dashboards_guild_id",
        "CREATE INDEX ix_dashboards_guild_id ON dashboards USING btree (guild_id)",
    ),
    (
        "ix_documents_guild_id",
        "CREATE INDEX ix_documents_guild_id ON documents USING btree (guild_id)",
    ),
    (
        "ix_export_jobs_guild_id",
        "CREATE INDEX ix_export_jobs_guild_id ON export_jobs USING btree (guild_id)",
    ),
    (
        "ix_galleries_guild_id",
        "CREATE INDEX ix_galleries_guild_id ON galleries USING btree (guild_id)",
    ),
    (
        "ix_gallery_images_guild_id",
        "CREATE INDEX ix_gallery_images_guild_id ON gallery_images USING btree (guild_id)",
    ),
    (
        "ix_guild_ai_connections_guild_id",
        "CREATE INDEX ix_guild_ai_connections_guild_id ON guild_ai_connections USING btree (guild_id)",
    ),
    (
        "ix_guild_ai_member_keys_guild_id",
        "CREATE INDEX ix_guild_ai_member_keys_guild_id ON guild_ai_member_keys USING btree (guild_id)",
    ),
    (
        "ix_guild_ai_member_prefs_guild_id",
        "CREATE INDEX ix_guild_ai_member_prefs_guild_id ON guild_ai_member_prefs USING btree (guild_id)",
    ),
    (
        "ix_guild_app_user_connections_guild_id",
        "CREATE INDEX ix_guild_app_user_connections_guild_id ON guild_app_user_connections USING btree (guild_id)",
    ),
    (
        "ix_guild_app_user_delegations_guild_id",
        "CREATE INDEX ix_guild_app_user_delegations_guild_id ON guild_app_user_delegations USING btree (guild_id)",
    ),
    (
        "ix_guild_apps_guild_id",
        "CREATE INDEX ix_guild_apps_guild_id ON guild_apps USING btree (guild_id)",
    ),
    (
        "ix_import_jobs_guild_id",
        "CREATE INDEX ix_import_jobs_guild_id ON import_jobs USING btree (guild_id)",
    ),
    (
        "ix_initiative_members_guild_id",
        "CREATE INDEX ix_initiative_members_guild_id ON initiative_members USING btree (guild_id)",
    ),
    (
        "ix_initiatives_guild_id",
        "CREATE INDEX ix_initiatives_guild_id ON initiatives USING btree (guild_id)",
    ),
    (
        "ix_posts_guild_id",
        "CREATE INDEX ix_posts_guild_id ON posts USING btree (guild_id)",
    ),
    (
        "ix_project_favorites_guild_id",
        "CREATE INDEX ix_project_favorites_guild_id ON project_favorites USING btree (guild_id)",
    ),
    (
        "ix_project_orders_guild_id",
        "CREATE INDEX ix_project_orders_guild_id ON project_orders USING btree (guild_id)",
    ),
    (
        "ix_projects_guild_id",
        "CREATE INDEX ix_projects_guild_id ON projects USING btree (guild_id)",
    ),
    (
        "ix_queue_items_guild_id",
        "CREATE INDEX ix_queue_items_guild_id ON queue_items USING btree (guild_id)",
    ),
    (
        "ix_queues_guild_id",
        "CREATE INDEX ix_queues_guild_id ON queues USING btree (guild_id)",
    ),
    (
        "ix_recent_views_guild_id",
        "CREATE INDEX ix_recent_views_guild_id ON recent_views USING btree (guild_id)",
    ),
    (
        "ix_resource_grants_guild_id",
        "CREATE INDEX ix_resource_grants_guild_id ON resource_grants USING btree (guild_id)",
    ),
    (
        "ix_tags_guild_id",
        "CREATE INDEX ix_tags_guild_id ON tags USING btree (guild_id)",
    ),
    (
        "ix_tags_guild_name_unique",
        "CREATE UNIQUE INDEX ix_tags_guild_name_unique ON tags USING btree (guild_id, lower((name)::text))",
    ),
    (
        "ix_task_assignees_guild_id",
        "CREATE INDEX ix_task_assignees_guild_id ON task_assignees USING btree (guild_id)",
    ),
    (
        "ix_task_statuses_guild_id",
        "CREATE INDEX ix_task_statuses_guild_id ON task_statuses USING btree (guild_id)",
    ),
    (
        "ix_tasks_guild_id",
        "CREATE INDEX ix_tasks_guild_id ON tasks USING btree (guild_id)",
    ),
    (
        "ix_uploads_guild_id",
        "CREATE INDEX ix_uploads_guild_id ON uploads USING btree (guild_id)",
    ),
    (
        "ix_webhook_subscriptions_dispatch",
        "CREATE INDEX ix_webhook_subscriptions_dispatch ON webhook_subscriptions USING btree (guild_id, initiative_id) WHERE (active = true)",
    ),
    (
        "ix_webhook_subscriptions_guild_id",
        "CREATE INDEX ix_webhook_subscriptions_guild_id ON webhook_subscriptions USING btree (guild_id)",
    ),
    (
        "ix_wiki_pages_guild_id",
        "CREATE INDEX ix_wiki_pages_guild_id ON wiki_pages USING btree (guild_id)",
    ),
    (
        "ix_wikis_guild_id",
        "CREATE INDEX ix_wikis_guild_id ON wikis USING btree (guild_id)",
    ),
    (
        "uq_initiatives_guild_default",
        "CREATE UNIQUE INDEX uq_initiatives_guild_default ON initiatives USING btree (guild_id) WHERE is_default",
    ),
    (
        "uq_initiatives_guild_name",
        "CREATE UNIQUE INDEX uq_initiatives_guild_name ON initiatives USING btree (guild_id, lower((name)::text))",
    ),
)

#: The two unique constraints naming it.
_UNIQUES: tuple[tuple[str, str, str], ...] = (
    ("guild_apps", "guild_apps_unique_listing", "UNIQUE (guild_id, listing_uid)"),
    ("guild_settings", "guild_settings_guild_id_key", "UNIQUE (guild_id)"),
)

#: Foreign keys to ``public.guilds``. Template-only: provisioning never copied
#: them into a guild schema, so the downgrade restores them there alone.
_FKS: tuple[tuple[str, str, str], ...] = (
    (
        "calendars",
        "calendars_guild_id_fkey",
        "FOREIGN KEY (guild_id) REFERENCES guilds(id)",
    ),
    (
        "dashboards",
        "dashboards_guild_id_fkey",
        "FOREIGN KEY (guild_id) REFERENCES guilds(id)",
    ),
    (
        "export_jobs",
        "export_jobs_guild_id_fkey",
        "FOREIGN KEY (guild_id) REFERENCES guilds(id)",
    ),
    (
        "galleries",
        "galleries_guild_id_fkey",
        "FOREIGN KEY (guild_id) REFERENCES guilds(id)",
    ),
    (
        "gallery_image_versions",
        "gallery_image_versions_guild_id_fkey",
        "FOREIGN KEY (guild_id) REFERENCES guilds(id)",
    ),
    (
        "gallery_images",
        "gallery_images_guild_id_fkey",
        "FOREIGN KEY (guild_id) REFERENCES guilds(id)",
    ),
    (
        "guild_ai_connections",
        "guild_ai_connections_guild_id_fkey",
        "FOREIGN KEY (guild_id) REFERENCES guilds(id)",
    ),
    (
        "guild_ai_member_keys",
        "guild_ai_member_keys_guild_id_fkey",
        "FOREIGN KEY (guild_id) REFERENCES guilds(id)",
    ),
    (
        "guild_ai_member_prefs",
        "guild_ai_member_prefs_guild_id_fkey",
        "FOREIGN KEY (guild_id) REFERENCES guilds(id)",
    ),
    (
        "guild_app_user_connections",
        "guild_app_user_connections_guild_id_fkey",
        "FOREIGN KEY (guild_id) REFERENCES guilds(id)",
    ),
    (
        "guild_app_user_delegations",
        "guild_app_user_delegations_guild_id_fkey",
        "FOREIGN KEY (guild_id) REFERENCES guilds(id)",
    ),
    (
        "guild_apps",
        "guild_apps_guild_id_fkey",
        "FOREIGN KEY (guild_id) REFERENCES guilds(id)",
    ),
    (
        "import_jobs",
        "import_jobs_guild_id_fkey",
        "FOREIGN KEY (guild_id) REFERENCES guilds(id)",
    ),
    (
        "moderation_reports",
        "moderation_reports_guild_id_fkey",
        "FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE",
    ),
    ("posts", "posts_guild_id_fkey", "FOREIGN KEY (guild_id) REFERENCES guilds(id)"),
    (
        "project_filter_presets",
        "project_filter_presets_guild_id_fkey",
        "FOREIGN KEY (guild_id) REFERENCES guilds(id)",
    ),
    (
        "wiki_pages",
        "wiki_pages_guild_id_fkey",
        "FOREIGN KEY (guild_id) REFERENCES guilds(id)",
    ),
    ("wikis", "wikis_guild_id_fkey", "FOREIGN KEY (guild_id) REFERENCES guilds(id)"),
)

#: The shared functions behind the triggers, dropped once in ``public``.
#: ``fn_project_documents_set_guild_id`` backs a table that no longer exists.
_FUNCTIONS: tuple[tuple[str, str], ...] = (
    (
        "fn_comments_set_guild_id",
        "CREATE OR REPLACE FUNCTION public.fn_comments_set_guild_id()\n RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n        BEGIN\n            IF NEW.guild_id IS NULL OR\n               (TG_OP = 'UPDATE' AND (OLD.task_id IS DISTINCT FROM NEW.task_id\n                    OR OLD.wiki_page_id IS DISTINCT FROM NEW.wiki_page_id\n                    OR OLD.project_id IS DISTINCT FROM NEW.project_id\n                    OR OLD.document_id IS DISTINCT FROM NEW.document_id\n                    OR OLD.queue_id IS DISTINCT FROM NEW.queue_id\n                    OR OLD.counter_group_id IS DISTINCT FROM NEW.counter_group_id\n                    OR OLD.calendar_id IS DISTINCT FROM NEW.calendar_id\n                    OR OLD.dashboard_id IS DISTINCT FROM NEW.dashboard_id\n                    OR OLD.post_id IS DISTINCT FROM NEW.post_id\n                    OR OLD.gallery_id IS DISTINCT FROM NEW.gallery_id\n                    OR OLD.wiki_id IS DISTINCT FROM NEW.wiki_id)) THEN\n                IF NEW.task_id IS NOT NULL THEN\n                    SELECT guild_id INTO NEW.guild_id FROM tasks WHERE id = NEW.task_id;\n                ELSIF NEW.wiki_page_id IS NOT NULL THEN\n                    SELECT guild_id INTO NEW.guild_id FROM wiki_pages WHERE id = NEW.wiki_page_id;\n                ELSIF NEW.project_id IS NOT NULL THEN\n                    SELECT guild_id INTO NEW.guild_id FROM projects WHERE id = NEW.project_id;\n                ELSIF NEW.document_id IS NOT NULL THEN\n                    SELECT guild_id INTO NEW.guild_id FROM documents WHERE id = NEW.document_id;\n                ELSIF NEW.queue_id IS NOT NULL THEN\n                    SELECT guild_id INTO NEW.guild_id FROM queues WHERE id = NEW.queue_id;\n                ELSIF NEW.counter_group_id IS NOT NULL THEN\n                    SELECT guild_id INTO NEW.guild_id FROM counter_groups WHERE id = NEW.counter_group_id;\n                ELSIF NEW.calendar_id IS NOT NULL THEN\n                    SELECT guild_id INTO NEW.guild_id FROM calendars WHERE id = NEW.calendar_id;\n                ELSIF NEW.dashboard_id IS NOT NULL THEN\n                    SELECT guild_id INTO NEW.guild_id FROM dashboards WHERE id = NEW.dashboard_id;\n                ELSIF NEW.post_id IS NOT NULL THEN\n                    SELECT guild_id INTO NEW.guild_id FROM posts WHERE id = NEW.post_id;\n                ELSIF NEW.gallery_id IS NOT NULL THEN\n                    SELECT guild_id INTO NEW.guild_id FROM galleries WHERE id = NEW.gallery_id;\n                ELSIF NEW.wiki_id IS NOT NULL THEN\n                    SELECT guild_id INTO NEW.guild_id FROM wikis WHERE id = NEW.wiki_id;\n                END IF;\n            END IF;\n            RETURN NEW;\n        END;\n        $function$\n",
    ),
    (
        "fn_documents_set_guild_id",
        "CREATE OR REPLACE FUNCTION public.fn_documents_set_guild_id()\n RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n        BEGIN\n            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.initiative_id IS DISTINCT FROM NEW.initiative_id) THEN\n                SELECT guild_id INTO NEW.guild_id FROM initiatives WHERE id = NEW.initiative_id;\n            END IF;\n            RETURN NEW;\n        END;\n        $function$\n",
    ),
    (
        "fn_initiative_members_set_guild_id",
        "CREATE OR REPLACE FUNCTION public.fn_initiative_members_set_guild_id()\n RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n        BEGIN\n            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.initiative_id IS DISTINCT FROM NEW.initiative_id) THEN\n                SELECT guild_id INTO NEW.guild_id FROM initiatives WHERE id = NEW.initiative_id;\n            END IF;\n            RETURN NEW;\n        END;\n        $function$\n",
    ),
    (
        "fn_project_documents_set_guild_id",
        "CREATE OR REPLACE FUNCTION public.fn_project_documents_set_guild_id()\n RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n        BEGIN\n            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.project_id IS DISTINCT FROM NEW.project_id) THEN\n                SELECT guild_id INTO NEW.guild_id FROM projects WHERE id = NEW.project_id;\n            END IF;\n            RETURN NEW;\n        END;\n        $function$\n",
    ),
    (
        "fn_project_favorites_set_guild_id",
        "CREATE OR REPLACE FUNCTION public.fn_project_favorites_set_guild_id()\n RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n        BEGIN\n            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.project_id IS DISTINCT FROM NEW.project_id) THEN\n                SELECT guild_id INTO NEW.guild_id FROM projects WHERE id = NEW.project_id;\n            END IF;\n            RETURN NEW;\n        END;\n        $function$\n",
    ),
    (
        "fn_project_filter_presets_set_guild_id",
        "CREATE OR REPLACE FUNCTION public.fn_project_filter_presets_set_guild_id()\n RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\nBEGIN\n    IF NEW.guild_id IS NULL\n       OR (TG_OP = 'UPDATE' AND OLD.project_id IS DISTINCT FROM NEW.project_id) THEN\n        SELECT guild_id INTO NEW.guild_id FROM projects WHERE id = NEW.project_id;\n    END IF;\n    RETURN NEW;\nEND;\n$function$\n",
    ),
    (
        "fn_project_orders_set_guild_id",
        "CREATE OR REPLACE FUNCTION public.fn_project_orders_set_guild_id()\n RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n        BEGIN\n            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.project_id IS DISTINCT FROM NEW.project_id) THEN\n                SELECT guild_id INTO NEW.guild_id FROM projects WHERE id = NEW.project_id;\n            END IF;\n            RETURN NEW;\n        END;\n        $function$\n",
    ),
    (
        "fn_projects_set_guild_id",
        "CREATE OR REPLACE FUNCTION public.fn_projects_set_guild_id()\n RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n        BEGIN\n            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.initiative_id IS DISTINCT FROM NEW.initiative_id) THEN\n                SELECT guild_id INTO NEW.guild_id FROM initiatives WHERE id = NEW.initiative_id;\n            END IF;\n            RETURN NEW;\n        END;\n        $function$\n",
    ),
    (
        "fn_reactions_set_guild_id",
        "CREATE OR REPLACE FUNCTION public.fn_reactions_set_guild_id()\n RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n        BEGIN\n            IF NEW.guild_id IS NULL OR\n               (TG_OP = 'UPDATE' AND (OLD.target_type IS DISTINCT FROM NEW.target_type\n                    OR OLD.target_id IS DISTINCT FROM NEW.target_id)) THEN\n                IF NEW.target_type = 'comment' THEN\n                    SELECT guild_id INTO NEW.guild_id FROM comments WHERE id = NEW.target_id;\n                END IF;\n            END IF;\n            RETURN NEW;\n        END;\n        $function$\n",
    ),
    (
        "fn_recent_views_set_guild_id",
        "CREATE OR REPLACE FUNCTION public.fn_recent_views_set_guild_id()\n RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n        BEGIN\n            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND (\n                OLD.entity_type IS DISTINCT FROM NEW.entity_type\n                OR OLD.entity_id IS DISTINCT FROM NEW.entity_id\n            )) THEN\n                CASE NEW.entity_type\n                    WHEN 'project' THEN\n                        SELECT guild_id INTO NEW.guild_id FROM projects\n                        WHERE id = NEW.entity_id;\n                    WHEN 'document' THEN\n                        SELECT guild_id INTO NEW.guild_id FROM documents\n                        WHERE id = NEW.entity_id;\n                    WHEN 'queue' THEN\n                        SELECT guild_id INTO NEW.guild_id FROM queues\n                        WHERE id = NEW.entity_id;\n                    WHEN 'counter_group' THEN\n                        SELECT guild_id INTO NEW.guild_id FROM counter_groups\n                        WHERE id = NEW.entity_id;\n                    WHEN 'calendar' THEN\n                        SELECT guild_id INTO NEW.guild_id FROM calendars\n                        WHERE id = NEW.entity_id;\n                    WHEN 'dashboard' THEN\n                        SELECT guild_id INTO NEW.guild_id FROM dashboards\n                        WHERE id = NEW.entity_id;\n                    WHEN 'post' THEN\n                        SELECT guild_id INTO NEW.guild_id FROM posts\n                        WHERE id = NEW.entity_id;\n                    WHEN 'gallery' THEN\n                        SELECT guild_id INTO NEW.guild_id FROM galleries\n                        WHERE id = NEW.entity_id;\n                    WHEN 'wiki' THEN\n                        SELECT guild_id INTO NEW.guild_id FROM wikis\n                        WHERE id = NEW.entity_id;\n                    ELSE\n                        RAISE EXCEPTION\n                            'fn_recent_views_set_guild_id has no arm for entity_type %',\n                            NEW.entity_type;\n                END CASE;\n            END IF;\n            RETURN NEW;\n        END;\n        $function$\n",
    ),
    (
        "fn_relationships_set_guild_id",
        "CREATE OR REPLACE FUNCTION public.fn_relationships_set_guild_id()\n RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n        BEGIN\n            IF NEW.guild_id IS NULL THEN\n                CASE NEW.source_type\n                    WHEN 'calendar' THEN\n                        SELECT guild_id INTO NEW.guild_id FROM calendars\n                        WHERE id = NEW.source_id;\n                    WHEN 'calendar_event' THEN\n                        SELECT guild_id INTO NEW.guild_id FROM calendar_events\n                        WHERE id = NEW.source_id;\n                    WHEN 'counter' THEN\n                        SELECT guild_id INTO NEW.guild_id FROM counters\n                        WHERE id = NEW.source_id;\n                    WHEN 'counter_group' THEN\n                        SELECT guild_id INTO NEW.guild_id FROM counter_groups\n                        WHERE id = NEW.source_id;\n                    WHEN 'dashboard' THEN\n                        SELECT guild_id INTO NEW.guild_id FROM dashboards\n                        WHERE id = NEW.source_id;\n                    WHEN 'document' THEN\n                        SELECT guild_id INTO NEW.guild_id FROM documents\n                        WHERE id = NEW.source_id;\n                    WHEN 'gallery' THEN\n                        SELECT guild_id INTO NEW.guild_id FROM galleries\n                        WHERE id = NEW.source_id;\n                    WHEN 'gallery_image' THEN\n                        SELECT guild_id INTO NEW.guild_id FROM gallery_images\n                        WHERE id = NEW.source_id;\n                    WHEN 'post' THEN\n                        SELECT guild_id INTO NEW.guild_id FROM posts\n                        WHERE id = NEW.source_id;\n                    WHEN 'project' THEN\n                        SELECT guild_id INTO NEW.guild_id FROM projects\n                        WHERE id = NEW.source_id;\n                    WHEN 'queue' THEN\n                        SELECT guild_id INTO NEW.guild_id FROM queues\n                        WHERE id = NEW.source_id;\n                    WHEN 'queue_item' THEN\n                        SELECT guild_id INTO NEW.guild_id FROM queue_items\n                        WHERE id = NEW.source_id;\n                    WHEN 'tag' THEN\n                        SELECT guild_id INTO NEW.guild_id FROM tags\n                        WHERE id = NEW.source_id;\n                    WHEN 'task' THEN\n                        SELECT guild_id INTO NEW.guild_id FROM tasks\n                        WHERE id = NEW.source_id;\n                    WHEN 'wiki' THEN\n                        SELECT guild_id INTO NEW.guild_id FROM wikis\n                        WHERE id = NEW.source_id;\n                    WHEN 'wiki_page' THEN\n                        SELECT guild_id INTO NEW.guild_id FROM wiki_pages\n                        WHERE id = NEW.source_id;\n                    ELSE\n                        RAISE EXCEPTION\n                            'fn_relationships_set_guild_id has no arm for source_type %',\n                            NEW.source_type;\n                END CASE;\n            END IF;\n            RETURN NEW;\n        END;\n        $function$\n",
    ),
    (
        "fn_task_assignees_set_guild_id",
        "CREATE OR REPLACE FUNCTION public.fn_task_assignees_set_guild_id()\n RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n        BEGIN\n            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.task_id IS DISTINCT FROM NEW.task_id) THEN\n                SELECT guild_id INTO NEW.guild_id FROM tasks WHERE id = NEW.task_id;\n            END IF;\n            RETURN NEW;\n        END;\n        $function$\n",
    ),
    (
        "fn_task_statuses_set_guild_id",
        "CREATE OR REPLACE FUNCTION public.fn_task_statuses_set_guild_id()\n RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n        BEGIN\n            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.project_id IS DISTINCT FROM NEW.project_id) THEN\n                SELECT guild_id INTO NEW.guild_id FROM projects WHERE id = NEW.project_id;\n            END IF;\n            RETURN NEW;\n        END;\n        $function$\n",
    ),
    (
        "fn_tasks_set_guild_id",
        "CREATE OR REPLACE FUNCTION public.fn_tasks_set_guild_id()\n RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n        BEGIN\n            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.project_id IS DISTINCT FROM NEW.project_id) THEN\n                SELECT guild_id INTO NEW.guild_id FROM projects WHERE id = NEW.project_id;\n            END IF;\n            RETURN NEW;\n        END;\n        $function$\n",
    ),
)

#: What replaces the five constraints that folded the column in.
_REPLACEMENTS: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_initiatives_name"
    " ON initiatives (lower(name))",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_initiatives_default"
    " ON initiatives (is_default) WHERE is_default",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_tags_name_unique ON tags (lower(name))",
    "CREATE UNIQUE INDEX IF NOT EXISTS guild_settings_single_row"
    " ON guild_settings ((true))",
    "CREATE INDEX IF NOT EXISTS ix_webhook_subscriptions_dispatch"
    " ON webhook_subscriptions (initiative_id) WHERE (active = true)",
)

_REPLACEMENT_NAMES: tuple[str, ...] = (
    "uq_initiatives_name",
    "uq_initiatives_default",
    "ix_tags_name_unique",
    "guild_settings_single_row",
    "ix_webhook_subscriptions_dispatch",
)

_ADD_LISTING_UNIQUE = (
    "ALTER TABLE guild_apps ADD CONSTRAINT guild_apps_unique_listing"
    " UNIQUE (listing_uid)"
)


#: The freeze guards, switched off and back on around the downgrade's carry.
#: They refuse an ordinary edit to a row under an archived parent, which is what
#: restoring a column on every row would otherwise be. Switched off rather than
#: removed, and per trigger by name rather than ``DISABLE TRIGGER USER``: the
#: same tables carry the authorship and capture triggers, which must keep
#: running.
_SET_FREEZE_TRIGGERS = """
DO $$
DECLARE row record;
BEGIN
    FOR row IN
        SELECT c.relname AS tbl, tg.tgname AS trg
          FROM pg_trigger tg
          JOIN pg_class c ON c.oid = tg.tgrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = current_schema()
           AND NOT tg.tgisinternal
           AND tg.tgname LIKE '%_frozen_%'
    LOOP
        EXECUTE format('ALTER TABLE %I {action} TRIGGER %I', row.tbl, row.trg);
    END LOOP;
END $$;
"""


def _schema_id(schema: str) -> int | None:
    """The community id a schema name carries, or None for the template."""
    match = re.fullmatch(r"guild_([0-9]+)", schema)
    return int(match.group(1)) if match else None


def upgrade() -> None:
    connection = op.get_bind()
    for schema in guild_schema_names(connection):
        connection.execute(
            sa.text("SELECT set_config('search_path', :sp, true)"),
            {"sp": f'"{schema}", public'},
        )
        for table, trigger, _ in _TRIGGERS:
            connection.execute(
                sa.text(f'DROP TRIGGER IF EXISTS "{trigger}" ON "{table}"')
            )
        # The column takes its indexes, its unique constraints and the
        # template's foreign keys with it.
        for table, _ in _TABLES:
            connection.execute(
                sa.text(f'ALTER TABLE "{table}" DROP COLUMN IF EXISTS guild_id')
            )
        for statement in _REPLACEMENTS:
            connection.execute(sa.text(statement))
        connection.execute(
            sa.text(
                "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint"
                " WHERE conname = 'guild_apps_unique_listing'"
                " AND connamespace = current_schema()::regnamespace)"
                f" THEN {_ADD_LISTING_UNIQUE}; END IF; END $$;"
            )
        )
    connection.execute(sa.text("SET LOCAL search_path = public"))
    for name, _ in _FUNCTIONS:
        connection.execute(sa.text(f"DROP FUNCTION IF EXISTS public.{name}()"))


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("SET LOCAL search_path = public"))
    for _, definition in _FUNCTIONS:
        connection.execute(sa.text(definition))

    for schema in guild_schema_names(connection):
        connection.execute(
            sa.text("SELECT set_config('search_path', :sp, true)"),
            {"sp": f'"{schema}", public'},
        )
        connection.execute(sa.text(_SET_FREEZE_TRIGGERS.format(action="DISABLE")))
        connection.execute(
            sa.text(
                'ALTER TABLE guild_apps DROP CONSTRAINT IF EXISTS "guild_apps_unique_listing"'
            )
        )
        for name in _REPLACEMENT_NAMES:
            connection.execute(sa.text(f'DROP INDEX IF EXISTS "{name}"'))

        guild_id = _schema_id(schema)
        for table, not_null in _TABLES:
            connection.execute(
                sa.text(
                    f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS guild_id integer'
                )
            )
            # The carry runs as the table's owner, and most of these force row
            # level security on it, whose policies read request settings a
            # migration has no value for. The force is lifted for the write and
            # restored whatever happens, so a guild is never left without it.
            forced = connection.execute(
                sa.text(
                    "SELECT relforcerowsecurity FROM pg_class c"
                    " JOIN pg_namespace n ON n.oid = c.relnamespace"
                    " WHERE n.nspname = current_schema() AND c.relname = :t"
                ),
                {"t": table},
            ).scalar()
            if forced:
                connection.execute(
                    sa.text(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
                )
            try:
                # The schema name is the answer, which is the point of the
                # change. The template holds no rows, so it carries nothing.
                if guild_id is not None:
                    connection.execute(
                        sa.text(f'UPDATE "{table}" SET guild_id = :gid'),
                        {"gid": guild_id},
                    )
            finally:
                if forced:
                    connection.execute(
                        sa.text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
                    )
            if not_null:
                # A row left without one here would be a carry that reached
                # nothing, so this is the assertion as well as the rule.
                connection.execute(
                    sa.text(f'ALTER TABLE "{table}" ALTER COLUMN guild_id SET NOT NULL')
                )
        for table, name, definition in _UNIQUES:
            connection.execute(
                sa.text(
                    f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint"
                    f" WHERE conname = '{name}'"
                    f" AND connamespace = current_schema()::regnamespace)"
                    f' THEN ALTER TABLE "{table}" ADD CONSTRAINT "{name}" {definition};'
                    f" END IF; END $$;"
                )
            )
        for _, definition in _INDEXES:
            connection.execute(
                sa.text(
                    definition.replace(
                        "CREATE INDEX", "CREATE INDEX IF NOT EXISTS", 1
                    ).replace(
                        "CREATE UNIQUE INDEX", "CREATE UNIQUE INDEX IF NOT EXISTS", 1
                    )
                )
            )
        if schema == "guild_template":
            for table, name, definition in _FKS:
                connection.execute(
                    sa.text(
                        f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint"
                        f" WHERE conname = '{name}'"
                        f" AND connamespace = current_schema()::regnamespace)"
                        f' THEN ALTER TABLE "{table}" ADD CONSTRAINT "{name}" {definition};'
                        f" END IF; END $$;"
                    )
                )
        for _, _, definition in _TRIGGERS:
            connection.execute(
                sa.text(
                    definition.replace("CREATE TRIGGER", "CREATE OR REPLACE TRIGGER", 1)
                )
            )
        connection.execute(sa.text(_SET_FREEZE_TRIGGERS.format(action="ENABLE")))
    connection.execute(sa.text("SET LOCAL search_path = public"))
