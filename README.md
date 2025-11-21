# Pour Priority

A full-stack project management application built with a FastAPI backend, PostgreSQL 17 storage, and a Vite + React frontend that communicates via React Query. The system ships with role-based permissions, JWT authentication, and a Docker-first story for self-hosting.

## Stack

- **Backend:** FastAPI, SQLModel, async SQLAlchemy engine (asyncpg), OAuth2 password flow (JWT), and PostgreSQL 17
- **Frontend:** Vite, React 18, TypeScript, React Router, React Query, Axios
- **Infrastructure:** Dockerfiles for backend/frontend + `docker-compose` with Postgres 17

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL 17 (or run the provided Docker Compose stack)

### Backend setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # update secrets + Postgres DSN
uvicorn app.main:app --reload
```

Key environment variables (see `.env.example`):

- `DATABASE_URL` – e.g., `postgresql+asyncpg://pour_priority:pour_priority@localhost:5432/pour_priority`
- `SECRET_KEY` – random string for JWT signing
- `AUTO_APPROVED_EMAIL_DOMAINS` – comma-separated list of email domains that should be activated automatically on signup
- `APP_URL` – public base URL for the app; used to derive OIDC callback URLs (e.g., `https://app.example.com`)
- `FIRST_SUPERUSER_*` – optional bootstrap admin created via `python -m app.db.init_db`

### Frontend setup

```bash
cd frontend
npm install
npm run dev
```

Expose the API URL to the frontend by setting `VITE_API_URL` (defaults to `http://localhost:8000/api/v1`).

### Docker Compose (recommended for local Postgres 17)

```bash
docker-compose up --build
```

Services:

- `db` – PostgreSQL 17 with a persistent volume
- `backend` – FastAPI app served on `http://localhost:8000`
- `frontend` – Static React build served via nginx on `http://localhost:5173`

## Application Features

### Authentication & Authorization

- User registration + OAuth2 password flow for login
- Admin approval queue for new accounts, with optional email-domain allowlist for automatic activation
- JWT-based `Authorization: Bearer ...` headers
- Global roles (`admin`, `project_manager`, `member`) enforced through dependency guards
- Project-level roles (`admin`, `project_manager`, `member`) for finer-grained control over task/project mutations
- Team-owned projects restrict visibility/editing to members of the owning team (admins can override)

### Backend Domain

- Users with hashed passwords, audit timestamps, and relationships to projects/tasks
- Projects with membership tables and cascading deletes for tasks/memberships
- Configurable project read/write role lists so owners can decide which project roles can view or edit each board
- Teams with many-to-many membership, plus team-owned projects that scope access to team members
- Project archiving with dedicated Archive view; only users with write access can archive/unarchive projects, keeping active boards focused
- Tasks tied to projects with status + priority enums for Kanban-style workflows
- Async Postgres engine, session dependency injection, and startup hook that auto-creates tables

### Frontend Experience

- Auth context with persistent JWT tokens and guarded routes
- React Query hooks for projects/tasks CRUD, with optimistic invalidations
- Simple project board UI + task status transitions, plus gated project creation for managers/admins
- Admin-only settings + user management screens for approval queues, allowlists, role changes, password resets, account deletion, team management, and OIDC configuration

### Teams

- Admins can create, edit, delete, and manage team membership from the Settings → Teams tab
- Projects can be assigned to a team; only members of that team (plus admins/owners) can read or write the project, and role-based permissions still apply within the team
- Team-owned projects automatically surface team membership details in the project view, and project assignment can be updated from the project detail page (admins only)

### OIDC

- Configure OpenID Connect providers via Settings → Auth (admins only); fields include discovery URL, client credentials, redirect URIs, and scopes
- When enabled, the login screen shows a “Continue with Single Sign-On” button that starts the OIDC flow against the configured provider
- Successful OIDC logins create/activate users automatically and redirect back to `${APP_URL}/oidc/callback` with a JWT token for the SPA to store
- Redirect URIs are derived automatically from `APP_URL`: `${APP_URL}/api/v1/auth/oidc/callback` for the provider callback and `${APP_URL}/oidc/callback` for the frontend

## Next Steps

- Add migration tooling (Alembic) for production schema changes
- Extend project membership management UI
- Harden Docker images with multi-stage builds / non-root users and add CI workflows
