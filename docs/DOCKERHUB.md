# Initiative

Self-hosted project management for friend groups, gaming communities, and small teams — projects, documents, and task boards without the complexity of enterprise tools.

> **Pre-release software** — this project hasn't reached v1.0.0 yet. The API may change between minor releases.

- **Guilds** keep each group's data completely separate, enforced by PostgreSQL Row Level Security
- **Initiatives & projects** organize related work, documents, and members
- **Drag-and-drop boards** plus Table, Calendar, and Gantt views
- **Collaborative documents** with real-time multi-user editing
- **Email/password or OIDC SSO**, optional AI integrations, i18n, and mobile push

Full feature list, screenshots, and security architecture: **[github.com/Morelitea/initiative](https://github.com/Morelitea/initiative)**.

## Supported tags

- `latest` — the most recent release
- `MAJOR`, `MAJOR.MINOR`, `MAJOR.MINOR.PATCH` — pin to a version (e.g. `0`, `0.49`, `0.49.9`)

Images are multi-arch: `linux/amd64` and `linux/arm64`.

## Quick start (Docker Compose)

```bash
# 1. Download the example compose file
curl -O https://raw.githubusercontent.com/Morelitea/initiative/main/docker-compose.example.yml
cp docker-compose.example.yml docker-compose.yml

# 2. Edit configuration — set a secure SECRET_KEY (and change the default DB passwords)
nano docker-compose.yml

# 3. Start
docker compose up -d

# 4. Open http://localhost:8173 — the first user to register becomes the platform admin
```

The example compose file ships Postgres 17 and all required settings pre-wired, so it works as-is once you set `SECRET_KEY`.

## Database connections (required)

Initiative needs **three** PostgreSQL connection strings, and the container will not start without all of them (`DATABASE_URL_APP` and `DATABASE_URL_ADMIN` have no defaults):

| Variable | Role | Purpose |
|---|---|---|
| `DATABASE_URL` | superuser | Runs migrations and **auto-creates** the two roles below at startup |
| `DATABASE_URL_APP` | `app_user` | RLS-enforced connection for normal request traffic |
| `DATABASE_URL_ADMIN` | `app_admin` (`BYPASSRLS`) | Migrations and background jobs |

The superuser URL bootstraps the roles; the password in each `APP`/`ADMIN` URL is the password that role is created with. If you write your own compose file or use `docker run`, set all three.

## Running as a non-root user (PUID/PGID)

The container **starts as root** so its entrypoint can create the runtime user, fix ownership on the uploads volume, then drop privileges with `gosu`. The app process itself runs unprivileged — default UID/GID `1000:1000`.

To run as a different UID/GID (e.g. to match a NAS user that owns the uploads volume), set the **`PUID`/`PGID`** environment variables. **Do not** add a Docker `user:` (Compose) or `--user` (run) override — that starts the entrypoint as non-root and fails with `fatal: Only root may add a user or group to the system`.

## Volumes & ports

- `/app/uploads` — uploaded files and documents; mount a volume to persist them
- Exposes port **8173** (HTTP)

## Key environment variables

A trimmed set — see the [full list](https://github.com/Morelitea/initiative#key-environment-variables) and [`backend/.env.example`](https://github.com/Morelitea/initiative/blob/main/backend/.env.example).

| Variable | Description | Default |
|---|---|---|
| `SECRET_KEY` | JWT signing and encryption key | Required |
| `APP_URL` | Public base URL (required for OIDC callbacks) | — |
| `DISABLE_GUILD_CREATION` | Restrict guild creation to super admin | `false` |
| `ENABLE_PUBLIC_REGISTRATION` | Allow registration without an invite | `true` |
| `BEHIND_PROXY` | Trust `X-Forwarded-For` headers | `false` |
| `PUID` / `PGID` | UID/GID the app runs as | `1000` / `1000` |

## Links

- **Source & full docs:** https://github.com/Morelitea/initiative
- **Changelog:** https://github.com/Morelitea/initiative/blob/main/CHANGELOG.md
- **Security & vulnerability reporting:** https://github.com/Morelitea/initiative/blob/main/SECURITY.md
- **License:** [AGPL-3.0](https://github.com/Morelitea/initiative/blob/main/LICENSE)
