from fastapi import APIRouter

# Endpoints are organized by the kind of data they touch (they must never mix):
#   public_endpoints/  — platform / public-schema tables (auth, users, guilds,
#                        settings, …); not tied to a single guild.
#   guild_endpoints/   — per-guild-schema tables (projects, tasks, documents, …),
#                        including the cross-guild "my" aggregates that read them.
from app.api.v1.guild_endpoints import (
    ai_settings,
    attachments,
    auto_subscriptions,
    calendar_events,
    collaboration,
    comments,
    counters,
    documents,
    events,
    imports,
    initiatives,
    me_trash,
    projects,
    property_definitions,
    queues,
    recents,
    tags,
    task_statuses,
    tasks,
    trash,
)
from app.api.v1.public_endpoints import (
    access_grants,
    admin,
    auth,
    config,
    guilds,
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
api_router.include_router(push.router, prefix="/push", tags=["push"])
# Platform / app-wide config (owner-only) and cross-guild PAM management — NOT
# guild-scoped (AdminSessionDep / capability-gated), so they stay top-level.
api_router.include_router(
    access_grants.router, prefix="/access-grants", tags=["access-grants"]
)
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(
    ai_settings.platform_router, prefix="/settings", tags=["ai-settings"]
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
guild_router.include_router(auto_subscriptions.router, prefix="/auto", tags=["auto"])
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
guild_router.include_router(imports.router, prefix="/imports", tags=["imports"])
guild_router.include_router(queues.router, prefix="/queues", tags=["queues"])
guild_router.include_router(
    counters.router, prefix="/counter-groups", tags=["counters"]
)
guild_router.include_router(
    calendar_events.router, prefix="/calendar-events", tags=["calendar-events"]
)
guild_router.include_router(tags.router, prefix="/tags", tags=["tags"])
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
me_router.include_router(calendar_events.me_router, tags=["calendar-events"])
me_router.include_router(me_trash.me_router, tags=["trash"])
me_router.include_router(users.me_router, tags=["users"])
api_router.include_router(me_router)
