from fastapi import APIRouter

from app.api.v1.endpoints import admin, attachments, auth, comments, documents, events, guilds, imports, initiatives, notifications, projects, settings, task_statuses, tasks, users, version

api_router = APIRouter()
api_router.include_router(version.router, tags=["version"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(guilds.router, prefix="/guilds", tags=["guilds"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(task_statuses.router, tags=["task-statuses"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(tasks.subtasks_router, tags=["subtasks"])
api_router.include_router(comments.router, prefix="/comments", tags=["comments"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(initiatives.router, prefix="/initiatives", tags=["initiatives"])
api_router.include_router(events.router, prefix="/events", tags=["events"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(attachments.router, prefix="/attachments", tags=["attachments"])
api_router.include_router(imports.router, prefix="/imports", tags=["imports"])
