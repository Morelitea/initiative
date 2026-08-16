from fastapi import APIRouter

# Endpoints are organized by the kind of data they touch (they must never mix —
# this mirrors the tenant/ vs platform/ split in models/, schemas/, services/):
#   platform_endpoints/  — public-schema tables (auth, users, guilds, settings,
#                          …); not tied to a single guild.
#   tenant_endpoints/    — per-guild-schema tables (projects, tasks, documents,
#                          …), including the cross-guild "my" aggregates that read
#                          them — the one place tenant data is read without a
#                          single guild context (see /me routes below).
#   app_service_endpoints/ — the channels an external app service calls back on.
#                          Split by CALLER rather than by data: no user is
#                          resolved, the caller is established from a request
#                          signature, and which guild it may reach follows from
#                          that.
from app.api.v1 import app_service_endpoints
from app.api.v1.tenant_endpoints import (
    ai_settings,
    app_data,
    attachments,
    webhooks,
    calendar_entries,
    calendar_events,
    calendars,
    dashboards,
    guild_apps,
    collaboration,
    comments,
    counters,
    documents,
    events,
    exports,
    imports,
    initiatives,
    me_ai,
    me_trash,
    projects,
    property_definitions,
    queues,
    recents,
    resource_grants,
    storage,
    tags,
    task_statuses,
    tasks,
    tools,
    trash,
)
from app.api.v1.platform_endpoints import (
    access_grants,
    admin,
    ai_settings as platform_ai_settings,
    app_platform,
    app_services,
    auth,
    auth_providers,
    billing,
    config,
    guild_auth_providers,
    guilds,
    marketplace,
    native,
    notifications,
    push,
    settings,
    user_view_preferences,
    users,
    version,
)

api_router = APIRouter()

# ---------------------------------------------------------------------------
# Top-level routes: unauthenticated, user-scoped, admin, and cross-guild.
# These do NOT take a guild path segment.
# ---------------------------------------------------------------------------
api_router.include_router(version.router, tags=["version"])
api_router.include_router(native.router, tags=["native"])
api_router.include_router(config.router, tags=["config"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(guilds.router, prefix="/guilds", tags=["guilds"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
# The marketplace catalog is platform-addressed: one shared surface, globally
# unique ids, and no tenant data — so it takes no guild segment. Installing is
# guild-scoped and lives on the tool routers.
api_router.include_router(
    marketplace.router, prefix="/marketplace", tags=["marketplace"]
)
api_router.include_router(push.router, prefix="/push", tags=["push"])
# Platform / app-wide config (owner-only) and cross-guild PAM management — NOT
# guild-scoped (AdminSessionDep / capability-gated), so they stay top-level.
api_router.include_router(
    access_grants.router, prefix="/access-grants", tags=["access-grants"]
)
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
# Deployment-level app service wiring (apps.manage — owner). Platform-addressed
# like the catalog: a registration belongs to the deployment, never to a guild.
api_router.include_router(
    app_services.router, prefix="/app-services", tags=["app-services"]
)
# Public: apps verify the context JWTs we send them against this key set. No
# credential, because requiring one to fetch a verification key is circular.
api_router.include_router(
    app_platform.router, prefix="/app-platform", tags=["app-platform"]
)
# The other half of that wiring: what a registered app service may call back on.
# Authenticated by request signature against its registration's shared secret —
# no user, no session, no guild in a header. The guild each call operates in is
# named in the path and re-checked against the caller's own installs.
api_router.include_router(
    app_service_endpoints.router, prefix="/app-service", tags=["app-service"]
)
api_router.include_router(
    auth_providers.router, prefix="/settings/auth/providers", tags=["auth-providers"]
)
api_router.include_router(
    guild_auth_providers.router, prefix="/guilds", tags=["guild-auth-providers"]
)
# Service-to-service endpoints for the external billing service.
api_router.include_router(billing.router, prefix="/billing", tags=["billing"])
api_router.include_router(
    platform_ai_settings.platform_router, prefix="/settings", tags=["ai-settings"]
)
# Notifications are user-scoped (cross-guild) — not under /g.
api_router.include_router(
    notifications.router, prefix="/notifications", tags=["notifications"]
)
# Recents tabs bar is cross-guild (GET list). The addressed delete lives under
# the guild router below.
api_router.include_router(recents.router, prefix="/recents", tags=["recents"])
api_router.include_router(
    user_view_preferences.router,
    prefix="/user-view-preferences",
    tags=["user-view-preferences"],
)

# ---------------------------------------------------------------------------
# Guild-scoped routes: everything that resolves a single guild's data lives
# under /g/{guild_id}. The guild is taken from the path (see
# deps.get_guild_membership); a guild-scoped router mounted outside this prefix
# fails at startup (missing path param) — a useful guard.
# ---------------------------------------------------------------------------
guild_router = APIRouter(prefix="/g/{guild_id}")
guild_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
guild_router.include_router(projects.router, prefix="/projects", tags=["projects"])
guild_router.include_router(task_statuses.router, tags=["task-statuses"])
guild_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
guild_router.include_router(tasks.subtasks_router, tags=["subtasks"])
guild_router.include_router(comments.router, prefix="/comments", tags=["comments"])
# Guild-scoped AI config (guild/user levels). Platform AI config is top-level.
guild_router.include_router(
    ai_settings.router, prefix="/settings", tags=["ai-settings"]
)
guild_router.include_router(
    initiatives.router, prefix="/initiatives", tags=["initiatives"]
)
guild_router.include_router(documents.router, prefix="/documents", tags=["documents"])
guild_router.include_router(
    attachments.router, prefix="/attachments", tags=["attachments"]
)
guild_router.include_router(exports.router, prefix="/exports", tags=["exports"])
guild_router.include_router(imports.router, prefix="/imports", tags=["imports"])
guild_router.include_router(queues.router, prefix="/queues", tags=["queues"])
guild_router.include_router(
    counters.router, prefix="/counter-groups", tags=["counters"]
)
guild_router.include_router(calendars.router, prefix="/calendars", tags=["calendars"])
guild_router.include_router(
    dashboards.router, prefix="/dashboards", tags=["dashboards"]
)
# Apps installed at guild scope. Every member reads them (the sidebar needs to
# know what is there); installing and removing are guild-admin actions.
#
# The data plane is included FIRST so its literal ``/apps/widget-catalog`` wins
# the match against ``/apps/{app_id}`` below — the same ordering rule the
# dashboards router uses for its own widget catalog.
guild_router.include_router(app_data.router, prefix="/apps", tags=["apps"])
guild_router.include_router(guild_apps.router, prefix="/apps", tags=["apps"])
# The same installs reached from inside one initiative. Its own router because
# the initiative leads the path: it is what the request is scoped to.
guild_router.include_router(guild_apps.initiative_router, tags=["apps"])
guild_router.include_router(
    calendar_events.router, prefix="/calendar-events", tags=["calendar-events"]
)
# Aggregate view: events + task markers in one request (calendar surfaces).
guild_router.include_router(
    calendar_entries.router, prefix="/calendar-entries", tags=["calendar-entries"]
)
guild_router.include_router(
    resource_grants.router, prefix="/resource-grants", tags=["resource-grants"]
)
guild_router.include_router(storage.router, prefix="/storage", tags=["storage"])
guild_router.include_router(tags.router, prefix="/tags", tags=["tags"])
# Generic per-tool surfaces addressed by the Tool enum ({tool} path param).
guild_router.include_router(tools.router, prefix="/tools", tags=["tools"])
guild_router.include_router(
    property_definitions.router,
    prefix="/property-definitions",
    tags=["property-definitions"],
)
guild_router.include_router(trash.router, prefix="/trash", tags=["trash"])
# Guild member management (guild-admin). The /me/* + platform user endpoints
# stay top-level on users.router.
guild_router.include_router(users.guild_router, prefix="/users", tags=["users"])
# Recents: the addressed DELETE is guild-scoped (the cross-guild GET list stays
# top-level — fully separate endpoints, see recents.py).
guild_router.include_router(recents.guild_router, prefix="/recents", tags=["recents"])
# WebSockets (guild-scoped). Mounting under /g fixes the URL shape now; the
# handlers are rewired to read the path guild in a follow-up step.
guild_router.include_router(events.router, prefix="/events", tags=["events"])
guild_router.include_router(
    collaboration.router, prefix="/collaboration", tags=["collaboration"]
)
api_router.include_router(guild_router)

# ---------------------------------------------------------------------------
# Cross-guild "my X" aggregates for the personal/multi-guild pages. User-scoped
# (no guild context); each routes per the user's member guilds. Tagged per
# DOMAIN so Orval generates each hook into its existing domain file.
# ---------------------------------------------------------------------------
me_router = APIRouter(prefix="/me")
me_router.include_router(tasks.me_router, tags=["tasks"])
me_router.include_router(documents.me_router, tags=["documents"])
me_router.include_router(projects.me_router, tags=["projects"])
me_router.include_router(calendars.me_router, tags=["calendars"])
me_router.include_router(calendar_events.me_router, tags=["calendar-events"])
me_router.include_router(calendar_entries.me_router, tags=["calendar-entries"])
me_router.include_router(me_trash.me_router, tags=["trash"])
me_router.include_router(me_ai.me_router, tags=["ai-settings"])
me_router.include_router(users.me_router, tags=["users"])
api_router.include_router(me_router)
