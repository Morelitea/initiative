from fastapi import APIRouter

from app.api.v1.endpoints import auth, events, projects, settings, tasks, teams, users

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(teams.router, prefix="/teams", tags=["teams"])
api_router.include_router(events.router, prefix="/events", tags=["events"])
