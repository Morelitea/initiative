# Initiative

A full-stack project management application built with a FastAPI backend, PostgreSQL 17 storage, and a Vite + React frontend that communicates via React Query. The system ships with role-based permissions, JWT authentication, and a Docker-first story for self-hosting.

## Stack

- **Backend:** FastAPI, SQLModel, async SQLAlchemy engine (asyncpg), Alembic migrations, OAuth2 password flow (JWT), and PostgreSQL 17
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
# Run the latest DB migrations (optional if you use init_db, but recommended)
alembic upgrade head

# Start the API
# Optionally explore the API docs at http://localhost:8000/api/v1/docs
uvicorn app.main:app --reload
```

Key environment variables (see `.env.example`):

- `DATABASE_URL` – e.g., `postgresql+asyncpg://initiative:initiative@localhost:5432/initiative`
- `SECRET_KEY` – random string for JWT signing
- `AUTO_APPROVED_EMAIL_DOMAINS` – comma-separated list of email domains that should be activated automatically on signup
- `APP_URL` – public base URL for the app; used to derive OIDC callback URLs (e.g., `https://app.example.com`)
- `FIRST_SUPERUSER_*` – optional bootstrap admin created via `python -m app.db.init_db`
- `SMTP_HOST` / `SMTP_PORT` / `SMTP_SECURE` / `SMTP_REJECT_UNAUTHORIZED` – SMTP server connection details used for transactional email
- `SMTP_USERNAME` / `SMTP_PASSWORD` – credentials for the SMTP relay (leave blank for anonymous)
- `SMTP_FROM_ADDRESS` – display + email address used as the `From` header, e.g. `Initiative <no-reply@example.com>`
- `SMTP_TEST_RECIPIENT` – optional default inbox for the “Send test email” button in Settings → Email

### Database migrations

Alembic handles schema changes. Run these from `backend/`:

- `alembic upgrade head` – apply migrations to the current database
- `alembic revision --autogenerate -m "describe change"` – generate a migration from model diffs
- `python -m app.db.init_db` – run migrations, ensure default app settings exist, and optionally create the superuser

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
- JWT-based `Authorization: Bearer ...` headers plus built-in Swagger UI at `/api/v1/docs` (supports JWTs or admin API keys)
- Admin API keys that can be generated from Settings → API Keys and supplied via `Authorization: Bearer <key>` for headless integrations
- Global roles are limited to `admin` and `member`, while initiative-scoped roles (`project_manager`, `member`) determine who can manage initiatives, invite teammates, and create projects. Admins automatically have full read/write access everywhere.
- Initiative membership grants implicit read access to every project in that initiative. Initiative project managers can grant extra write overrides on specific projects via the `project_permissions` table, so access flows Admin → Initiative PM → explicit project write override → initiative member read.
- Initiative-owned projects restrict visibility/editing to members of the owning initiative (admins can override)

### Backend Domain

- Users with hashed passwords, audit timestamps, and relationships to projects/tasks
- Projects belong to initiatives and cascade deletes into related tasks/permissions
- Explicit project write overrides live in the `project_permissions` table (levels `owner`/`write`), while initiative membership handles read access
- Initiatives with many-to-many membership, plus initiative-owned projects that scope access to initiative members
- Project archiving with dedicated Archive view; only users with write access can archive/unarchive projects, keeping active boards focused
- Tasks tied to projects with status + priority enums for Kanban-style workflows
- Async Postgres engine, session dependency injection, and startup hook that auto-creates tables

### Frontend Experience

- Auth context with persistent JWT tokens and guarded routes
- React Query hooks for projects/tasks CRUD, with optimistic invalidations
- Simple project board UI + task status transitions, plus gated project creation for managers/admins
- Admin-only settings + user management screens for approval queues, allowlists, role changes, password resets, account deletion, initiative management, OIDC configuration, and API key management

### Initiatives

- Admins can create, edit, delete, and manage initiative membership from the Settings → Initiatives tab
- Projects can be assigned to an initiative; only members of that initiative (plus admins/owners) can read or write the project, and role-based permissions still apply within the initiative
- Initiative-owned projects automatically surface initiative membership details in the project view, and project assignment can be updated from the project detail page (admins only)
- A non-deletable “Default Initiative” is created atomically when the first admin account is provisioned so that every project always belongs to an initiative.
- Every initiative must retain at least one project manager—creators are promoted automatically, and the API blocks demotions/deletions that would remove the final PM until someone else is assigned.
- Initiative members inherit read access to all initiative projects, while admins and initiative PMs control project creation plus per-project write overrides for specific members.

### OIDC

- Configure OpenID Connect providers via Settings → Auth (admins only); fields include discovery URL, client credentials, redirect URIs, and scopes
- When enabled, the login screen shows a “Continue with Single Sign-On” button that starts the OIDC flow against the configured provider
- Successful OIDC logins create/activate users automatically and redirect back to `${APP_URL}/oidc/callback` with a JWT token for the SPA to store
- Redirect URIs are derived automatically from `APP_URL`: `${APP_URL}/api/v1/auth/oidc/callback` for the provider callback and `${APP_URL}/oidc/callback` for the frontend

## Next Steps

- Extend project membership management UI
- Harden Docker images with multi-stage builds / non-root users and add CI workflows
