---
icon: lucide/package
---

# Installation

The recommended way to run Initiative is with **Docker Compose**. It brings up the application and its PostgreSQL database together, handles the database setup for you, and is the same path the project supports and tests.

## Before you start

You'll need a machine (your own, or a cloud server) with:

- **Docker** and **Docker Compose** installed.
- A way to reach it in a browser — `localhost` for trying it out, or a domain name for real use.

## Quick start

```bash
# 1. Download the example compose file
curl -O https://raw.githubusercontent.com/Morelitea/initiative/main/docker-compose.example.yml
cp docker-compose.example.yml docker-compose.yml

# 2. Edit configuration — set a strong SECRET_KEY (and change the default DB passwords)
nano docker-compose.yml

# 3. Start it
docker compose up -d

# 4. Open http://localhost:8173 — the first person to register becomes the owner
```

The example file ships **PostgreSQL 17** and sensible defaults already wired together, so it works as-is once you set a `SECRET_KEY`. Initiative listens on port **8173** by default.

!!! warning "Change the secrets before going live"
    At a minimum, set a strong, unique **`SECRET_KEY`** and change the default **database passwords**. The `SECRET_KEY` signs sessions *and* encrypts sensitive data — keep it safe, and don't change it casually later (doing so invalidates existing sessions and encrypted values).

## Where your data lives

Two things need to persist across restarts and upgrades:

- **The database** — your projects, tasks, documents, and so on.
- **Uploaded files** — mounted at `/app/uploads` in the container.

The example compose file sets up volumes for both. Make sure those volumes live somewhere your [backups](backups-and-updates.md) will capture.

## The three database connections

Initiative connects to PostgreSQL with **three** connection strings, and it won't start without all three. They work as a set — this is part of how Initiative enforces least-privilege at the database level (see [How your data is kept separate](../security/how-your-data-is-kept-separate.md)).

| Variable | Connects as | Purpose |
|---|---|---|
| `DATABASE_URL` | a superuser | Runs migrations once at startup and **auto-creates** the two roles below. |
| `DATABASE_URL_APP` | `app_user` | The everyday, security-enforced connection for normal requests. |
| `DATABASE_URL_ADMIN` | `app_admin` | Migrations and background jobs. |

The superuser URL bootstraps the roles; the password you put in each `APP`/`ADMIN` URL becomes that role's password. The example compose file wires all three together with matching credentials, so the default path just works. If you write your own compose file or use `docker run`, you must set all three.

## Running as a specific user (PUID / PGID)

The container **starts as root** so it can create its runtime user and fix file ownership on the uploads volume, then drops privileges and runs the app unprivileged (UID/GID `1000:1000` by default).

To run as a different user — for example, to match the account that owns the uploads folder on a NAS — set **`PUID`** and **`PGID`**.

!!! warning "Don't override the container's user directly"
    Don't add a Docker `user:` (Compose) or `--user` (run) override — that starts the entrypoint as non-root and it can't create the runtime user, failing with `fatal: Only root may add a user or group to the system`. Use `PUID`/`PGID` instead. (Setting them to `0`/root is rejected.)

## Docker images

Published images are multi-architecture (`linux/amd64` and `linux/arm64`):

```bash
docker pull morelitea/initiative:latest    # most recent release
docker pull morelitea/initiative:0.53       # pin to a minor version
```

Tags follow the version number, so you can pin to `latest`, a major (`0`), a minor (`0.53`), or an exact patch (`0.53.3`).

## First-time setup checklist

Once it's running:

- [ ] **Register the first account** — it becomes the [owner](platform-roles.md).
- [ ] Put Initiative behind **HTTPS** for any real use (a reverse proxy such as Caddy, Traefik, or nginx).
- [ ] Set **`APP_URL`** to your public address (needed for single sign-on and links). See [Configuration](configuration.md).
- [ ] Configure **email** so invites and reminders can be sent. See [Email](email.md).
- [ ] Set up **[backups](backups-and-updates.md)**.

## Next

- [Configuration](configuration.md) — the full list of settings.
- [Backups & updates](backups-and-updates.md) — keep your data safe and your server current.
