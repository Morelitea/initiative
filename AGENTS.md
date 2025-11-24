# Repository Guidelines

## Project Structure & Module Organization

`backend/` hosts the FastAPI service; routers sit in `app/api`, config in `core`, persistence helpers in `db`, domain models in `models`, payloads in `schemas`, and business logic in `services`, with `main.py` as the uvicorn entry point. `frontend/src` stays feature-first (`api`, `components`, `features`, `pages`, `hooks`, `lib`, `types`). Dockerfiles plus the root `docker-compose.yml` wire Postgres, backend, and the nginx React build.

## Build, Test, and Development Commands

- `cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt` — install runtime deps.
- `cd backend && poetry install` — optional, but grabs dev tools (pytest, Ruff) defined in `pyproject.toml`.
- `cd backend && uvicorn app.main:app --reload` — run the API on http://localhost:8000.
- `cd backend && alembic upgrade head` — apply the latest database migrations (or run `python -m app.db.init_db` to migrate plus seed defaults).
- `cd backend && alembic revision --autogenerate -m "desc"` — generate a migration after SQLModel changes.
- `cd frontend && npm install && npm run dev` — launch the Vite dev server (uses `VITE_API_URL`, defaults to `http://localhost:8000/api/v1`).
- `docker-compose up --build` — start Postgres 17, backend, and the nginx SPA.
- `cd backend && pytest` / `ruff check app` and `cd frontend && npm run lint` — run tests and linters.

## Coding Style & Naming Conventions

Python uses 4-space indentation, full type hints, `snake_case` modules/functions, and `PascalCase` SQLModel or schema classes; keep routing thin and push validation to `schemas` and `services`. React components are `PascalCase` files, hooks follow the `useThing` convention, and shared helpers live in `frontend/src/lib` or `api`. Ruff and ESLint must pass before opening a PR.

## Testing Guidelines

Write Pytest suites under `backend/tests`, exercising API routers with `httpx.AsyncClient` fixtures and covering RBAC, JWT flows, and initiative visibility rules. For new UI logic, add Vitest + Testing Library specs under the relevant feature folder (or `frontend/src/__tests__`); prioritize coverage for auth, project CRUD, and optimistic updates.

## Commit & Pull Request Guidelines

History favors short, lower-case subjects (e.g., `mvp wip 1`), so keep the first line imperative, ≤50 chars, and use additional lines for detail. Separate backend, frontend, and infra changes when practical. PRs must describe the problem, list notable changes, call out schema or env updates, and attach screenshots/GIFs for UI tweaks plus the exact commands you ran for testing.

## Security & Configuration Tips

Copy `backend/.env.example`, set `DATABASE_URL`, `SECRET_KEY`, `AUTO_APPROVED_EMAIL_DOMAINS`, and optional `FIRST_SUPERUSER_*`, then run `alembic upgrade head` (or `python -m app.db.init_db`) so the schema is current and default settings/SUs are seeded. The SPA reads `VITE_API_URL`; align it with the reverse-proxy host in every environment. If enabling OIDC, ensure `APP_URL` is publicly reachable so computed callback URLs stay valid.
