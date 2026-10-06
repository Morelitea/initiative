---
icon: lucide/package
---

# Installation

The recommended way to run Initiative is **Docker Compose**. It brings up the app and its PostgreSQL database together, sorts the database setup out for you, and is the path the project actually supports and tests — which matters when something goes sideways at 11pm.

Would rather not run a server at all? Completely fair. A paid hosted service is coming — see [Self-host or let us host it](../self-host-or-hosted.md).

## Before you start

A machine (yours, or a cloud box) with:

- **Docker** and **Docker Compose** installed.
- A way to reach it in a browser — `localhost` for a try-out, a domain name for real use.

## Quick start

```bash
# 1. Download the example compose file
curl -O https://raw.githubusercontent.com/Morelitea/initiative/main/docker-compose.example.yml
cp docker-compose.example.yml docker-compose.yml

# 2. Edit configuration — set a strong SECRET_KEY and POSTGRES_PASSWORD
nano docker-compose.yml

# 3. Start it
docker compose up -d

# 4. Open http://localhost:8173 — the first person to register becomes the owner
```

The example file ships **PostgreSQL 17** and sensible defaults already wired together, so it works as-is once you set a `SECRET_KEY` and a `POSTGRES_PASSWORD`. It refuses to start without either. Initiative listens on port **8173** by default.

!!! warning "Choose both secrets once, and keep them"
    Make **`SECRET_KEY`** and **`POSTGRES_PASSWORD`** strong and unique. `openssl rand -hex 32` makes a good one of each.

    PostgreSQL reads **`POSTGRES_PASSWORD`** only when it first creates the database. Changing it afterwards doesn't change the password, it just stops Initiative connecting.

    The `SECRET_KEY` signs sessions *and* encrypts sensitive data. Keep it somewhere safe, and don't change it casually later on a whim — doing so invalidates existing sessions and every encrypted value.

## Where your data lives

Two things need to persist across restarts and upgrades:

- **The database** — your projects, tasks, comments, and so on.
- **Uploaded files** — mounted at `/app/uploads` in the container.

The example compose file sets up volumes for both. Make sure those volumes live somewhere your [backups](backups-and-updates.md) will capture.

## The database connection

One URL, connecting as the database's owner:

```yaml
DATABASE_URL: postgresql+asyncpg://initiative:<password>@db:5432/initiative
```

That's the user and password you gave PostgreSQL when you set it up. In the example compose file they're `POSTGRES_USER` and `POSTGRES_PASSWORD`, already wired in.

You don't have to know anything else about it. At startup Initiative uses that connection to set up three smaller logins of its own, then serves every request on those. Each one can do only its own job, which is how the separation described in [How your data is kept separate](../security/how-your-data-is-kept-separate.md) is enforced by the database itself.

??? techspec "The three logins"
    | Login | Used for |
    |---|---|
    | `app_provisioner` | Migrations and creating community spaces. Not a superuser. |
    | `app_user` | Every request. Row-level security applies to it. |
    | `app_admin` | Background jobs and startup seeding. |

    Their passwords are derived from `SECRET_KEY` and set again on every start. Rotating `SECRET_KEY` (with `PREVIOUS_SECRET_KEY`, as `backend/.env.example` describes) rotates them too, with nothing else to do. The owner connection is closed before Initiative serves anything.

    The owner also installs the search index's match operator, which is marked `LEAKPROOF`. Only a PostgreSQL superuser may declare that. The example compose file's owner is one; if yours isn't, everything else still works, search just reads more of its index to get there, and Initiative says so at startup.

### Naming the logins yourself

Some setups need to know the logins in advance: a connection pooler such as PgBouncer with its own user list, a managed PostgreSQL service, or a DBA who'd rather Initiative never held the owner's password. For those, give the three connections directly:

| Variable | Connects as |
|---|---|
| `DATABASE_URL` | `app_provisioner` |
| `DATABASE_URL_APP` | `app_user` |
| `DATABASE_URL_ADMIN` | `app_admin` |
| `DATABASE_URL_BOOTSTRAP` | the database owner (optional) |

Set `DATABASE_URL_APP` and `DATABASE_URL_ADMIN` and Initiative reads `DATABASE_URL` as the provisioner. With `DATABASE_URL_BOOTSTRAP` it creates the three logins with the passwords in their URLs, on every start. Without it, Initiative only checks they exist and names anything missing. To create them by hand, print the SQL and run it as the owner:

```bash
docker compose exec -T initiative python -m app.db.bootstrap --print-sql
```

To go back to one URL, point `DATABASE_URL` at the owner, delete the other three, and restart.

## Running as a specific user (PUID / PGID)

The container **starts as root** so it can create its runtime user and fix file ownership on the uploads volume, then drops privileges and runs the app unprivileged (UID/GID `1000:1000` by default).

To run as a different user — for example, to match the account that owns the uploads folder on a NAS — set **`PUID`** and **`PGID`**.

!!! warning "Don't override the container's user directly"
    Don't add a Docker `user:` (Compose) or `--user` (run) override — that starts the entrypoint as non-root and it can't create the runtime user, failing with `fatal: Only root may add a user or group to the system`. Use `PUID`/`PGID` instead. (Setting them to `0`/root is rejected.)

## Docker images

Published images run on `linux/amd64` and `linux/arm64`. Pick a tag by how you feel about surprises:

| Tag | Moves to | Suits you if |
|---|---|---|
| `latest` | every release, the day it ships | you like new things, and you'll say something when one bites |
| `stable` | a release we have promoted by hand, after it was out at least three days with no open regression reported against it | you would rather somebody else found it first |
| `0.53`, `0` | the newest release in that line | you want fixes without choosing each one |
| `0.53.3` | nowhere, ever | you upgrade when you decide to, and not a minute before |

The example compose file uses `latest`. To follow `stable`, change its `image:` line to `morelitea/initiative:stable`, then:

```bash
docker compose pull && docker compose up -d
```

Three days is the least a release waits, not a timer: `stable` moves when we promote the next release that qualifies, so it can sit on one version for a while. A release with a security fix can reach it sooner. And `stable` only works because people run `latest`: a bug report with the **Version** filled in is exactly what holds a release back from it.

### Checking an image is ours

You never have to. But every image is signed by the workflow that built it, and carries a list of everything inside it (an SBOM) and a record of how it was built. If your setup checks images before running them, this is the check, using [cosign](https://docs.sigstore.dev/cosign/system_config/installation/):

```bash
cosign verify morelitea/initiative:stable \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp '^https://github\.com/Morelitea/initiative/\.github/workflows/docker-image\.yml@refs/(heads/(main|release/v.+)|tags/v.+)$'
```

It passes only for an image our release workflow built from a release branch or tag. Images from `dev` are signed as well, from `refs/heads/dev`, which this deliberately doesn't accept.

To read the SBOM:

```bash
docker buildx imagetools inspect morelitea/initiative:stable --format '{{ json .SBOM }}'
```

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
