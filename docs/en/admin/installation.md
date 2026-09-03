---
icon: lucide/package
---

# Installation

The recommended way to run Initiative is **Docker Compose**. It brings up the app and its PostgreSQL database together, handles the database setup for you, and is the path the project actually supports and tests.

Would rather not run a server? A paid hosted service is coming — see [Self-host or let us host it](../self-host-or-hosted.md).

## Before you start

A machine (yours, or a cloud box) with:

- **Docker** and **Docker Compose** installed.
- A way to reach it in a browser — `localhost` for a try-out, a domain name for real use.

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

## The database connections

Initiative runs on **three** PostgreSQL roles and won't start without a connection string for each. They work as a set — this is how least-privilege is enforced at the database level (see [How your data is kept separate](../security/how-your-data-is-kept-separate.md)).

| Variable | Connects as | Purpose |
|---|---|---|
| `DATABASE_URL` | `app_provisioner` | Runs migrations and creates community spaces. Not a superuser. |
| `DATABASE_URL_APP` | `app_user` | The everyday, security-enforced connection for normal requests. |
| `DATABASE_URL_ADMIN` | `app_admin` | Background jobs and startup seeding. |

A fourth connection creates those three:

| Variable | Connects as | Purpose |
|---|---|---|
| `DATABASE_URL_BOOTSTRAP` | the database owner | Creates the three roles, hands them the schema, and installs the search index's match operator. |

At startup Initiative opens the bootstrap connection, applies those prerequisites, and closes it. Every request afterwards runs on the three roles above. The password you put in each URL is the password that role gets, and the bootstrap runs on every start — so changing one and restarting is how you rotate it.

The example compose file wires all four together, so `docker compose up` works with no SQL to run by hand.

**Once you're running, you can remove `DATABASE_URL_BOOTSTRAP`.** Initiative then checks those prerequisites at startup instead of applying them, and names anything missing. If you point Initiative at a database you provision elsewhere — a managed PostgreSQL service, a Kubernetes operator, a DBA who owns the cluster — leave it unset and apply the SQL yourself:

```bash
docker compose exec -T initiative python -m app.db.bootstrap --print-sql
```

One part of that SQL needs a PostgreSQL superuser: the search index's match operator is marked `LEAKPROOF`, which only a superuser may declare. If your database owner isn't one, everything else still applies and search works — it just reads more of its index to do it, and Initiative says so at startup.

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
