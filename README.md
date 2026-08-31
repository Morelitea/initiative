# Initiative

[![User Guide](https://img.shields.io/badge/📖_User_Guide-Learn_how_to_use_Initiative-6f42c1?style=for-the-badge)](https://morelitea.github.io/initiative/)

[![CI](https://github.com/Morelitea/initiative/actions/workflows/ci.yml/badge.svg)](https://github.com/Morelitea/initiative/actions/workflows/ci.yml)
[![Latest Release](https://img.shields.io/github/v/release/Morelitea/initiative?sort=semver)](https://github.com/Morelitea/initiative/releases)
[![License](https://img.shields.io/github/license/Morelitea/initiative)](https://github.com/Morelitea/initiative/blob/main/LICENSE)
[![Docker](https://img.shields.io/docker/v/morelitea/initiative?sort=semver\&label=Docker)](https://hub.docker.com/r/morelitea/initiative)



> **Pre-release software** — this project hasn't reached v1.0.0 yet. The API may change between minor releases.

<img width="2264" height="1315" alt="initiative screenshot" src="https://github.com/user-attachments/assets/c2c6b9c8-3f6f-4d17-a1ba-9338c033674d" />

---

## What is Initiative?

**Initiative is a shared workspace for organizing the things a group needs to get done.** Projects, tasks, documents, calendars, and other tools all live together, so you don't have to stitch your work across a dozen different apps.

It's designed for **small businesses, clubs, committees, event teams, families, and other groups** that need to coordinate work without becoming project-management experts.

Start with a board and a few tasks. As your needs grow, add the tools you need — and leave everything else out of the way.

Initiative also gives you fine-grained control over **who can see and change your work**, and a marketplace lets you add ready-made apps and dashboards built by other groups.

**It's project management that starts simple and grows with you.**

---

## Quick Start

### Docker Compose (Recommended)

```bash
# 1. Download the example compose file
curl -O https://raw.githubusercontent.com/Morelitea/initiative/main/docker-compose.example.yml
cp docker-compose.example.yml docker-compose.yml

# 2. Edit configuration — set a secure SECRET_KEY at minimum
nano docker-compose.yml

# 3. Start the application
docker-compose up -d

# 4. Access Initiative at http://localhost:8173
```

**What's included:**

- PostgreSQL 17 with persistent storage and Row Level Security
- Automatic database role creation and migrations
- React frontend served via FastAPI
- Health checks and automatic restarts

**First-time setup:**

1. The first user to register becomes the platform owner
2. Configure SMTP in the admin panel to enable email notifications
3. Create your first guild and start inviting people

See [Key Environment Variables](#key-environment-variables) for full configuration options.

> [!CAUTION]
> **Do not use `dev` images for production or customer deployments.** `dev` contains experimental work that may not make it into a stable release. Use `latest` or a tagged release from `main`.

### Docker Hub Images

```bash
docker pull morelitea/initiative:latest    # latest release
docker pull morelitea/initiative:0.32      # specific minor
```

Images support `linux/amd64` and `linux/arm64` architectures.

---

## Configuration

### Key Environment Variables

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | Provisioning PostgreSQL connection (migrations, guild/role creation; not a superuser) | Required |
| `DATABASE_URL_APP` | RLS-enforced connection (`app_user` role) | Required |
| `DATABASE_URL_ADMIN` | Admin connection for background jobs (`app_admin` role) | Required |
| `SECRET_KEY` | JWT signing and encryption key | Required |
| `APP_URL` | Public base URL (required for OIDC callbacks) | - |
| `DISABLE_GUILD_CREATION` | Restrict guild creation to super admin | `false` |
| `ENABLE_PUBLIC_REGISTRATION` | Allow registration without invite link | `true` |
| `ENABLE_MCP` | Mount the in-app MCP server at `/api/v1/mcp/` for AI assistants (see [MCP Server](#mcp-server)) | `false` |
| `MARKETPLACE_EXTRA_CATALOG_DIR` | Directory of your own marketplace listing files (see [Publishing your own listings](docs/en/admin/publishing-listings.md)) | - |
| `CAPTCHA_PROVIDER` | Captcha vendor for registration: `hcaptcha`, `turnstile`, or `recaptcha` (v2 only). Unset / unrecognised disables the gate | - |
| `CAPTCHA_SITE_KEY` | Public key sent to the SPA to render the widget | - |
| `CAPTCHA_SECRET_KEY` | Server-side key for the provider's siteverify endpoint | - |
| `BEHIND_PROXY` | Trust `X-Forwarded-For` headers | `false` |
| `FORWARDED_ALLOW_IPS` | Trusted proxy IPs (when `BEHIND_PROXY=true`) | `*` |
| `FIRST_OWNER_EMAIL` | Bootstrap owner email (legacy `FIRST_SUPERUSER_EMAIL` accepted) | - |
| `FIRST_OWNER_PASSWORD` | Bootstrap owner password (legacy `FIRST_SUPERUSER_PASSWORD` accepted) | - |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_PASSWORD` | SMTP server configuration | - |
| `SMTP_FROM_ADDRESS` | Email sender address | - |
| `FCM_ENABLED` | Enable Firebase Cloud Messaging | `false` |
| `PUID` | UID the container runs as (for rootless/NAS setups) | `1000` |
| `PGID` | GID the container runs as (for rootless/NAS setups) | `1000` |

For FCM setup, see [docs/en/admin/push-notifications.md](docs/en/admin/push-notifications.md). For a complete list of options, see `backend/.env.example`.

### Database connections

Initiative needs **three** PostgreSQL connection strings, and the container will not start without all of them (`DATABASE_URL_APP` and `DATABASE_URL_ADMIN` have no defaults — a missing one aborts startup with a config validation error). They work as a set:

- **`DATABASE_URL`** — the **provisioning role** (`app_provisioner`): runs migrations and creates/removes guild schemas, and **auto-creates the two roles below**. It is deliberately *not* a superuser — the example compose file creates `app_provisioner` automatically when the database volume is first initialized, and the app warns at boot if this URL connects as a superuser (existing installs: run `backend/scripts/create-provisioner.sql` once to switch).
- **`DATABASE_URL_APP`** — connects as `app_user`. The password in this URL is the password the `app_user` role is created/updated with.
- **`DATABASE_URL_ADMIN`** — connects as `app_admin`, the system role for background jobs and startup seeding. Likewise, its password seeds that role.

In other words, the provisioning URL bootstraps the roles, while the `APP`/`ADMIN` URLs both *define* those roles' passwords and are what the running app actually uses. The [example compose file](docker-compose.example.yml) wires all three together with matching credentials, so the default `docker-compose up` path works as-is. If you write your own compose file or use `docker run`, set all three.

### Running as a non-root user (PUID/PGID)

The container **starts as root** so its entrypoint can create the runtime user, fix ownership on the uploads volume, and then drop privileges with `gosu`. The main uvicorn process runs unprivileged — by default UID/GID `1000:1000` with no Linux capabilities.

To run as a different UID/GID (for example, to match the NAS user that owns the `uploads` volume), set the **`PUID`/`PGID`** environment variables. **Do not** add a Docker `user:` (Compose) or `--user` (run) override — that starts the entrypoint as non-root, so it can't create the user and fails with `fatal: Only root may add a user or group to the system`. `PUID`/`PGID` is the supported knob; `0` (root) is rejected.

---

## MCP Server

Initiative ships an optional, in-app [MCP](https://modelcontextprotocol.io/) server so MCP-compatible AI assistants (such as [Claude Code](https://claude.com/claude-code)) can work with your data on your behalf. It is **route-backed**: every tool call runs through the real API with your authentication and the same Row-Level-Security access rules as the app, so a tool can only ever reach data *you* can reach — scoped per guild and initiative. It is **off by default**.

### Enable it

Set `ENABLE_MCP=true` (in `.env` or your container environment) and restart — the endpoint is mounted at startup:

```
ENABLE_MCP=true
```

The server is then served at **`/api/v1/mcp/`** (note the trailing slash) on your deployment's public host — i.e. **`<APP_URL>/api/v1/mcp/`**, using the same `APP_URL` you set in `.env`. (For local testing that's `http://localhost:8173/api/v1/mcp/`; `localhost` is for testing only, not your launched URL.) Because it is in-app, it ships in the Docker image — flipping the env var is all a deployer needs. Leave it off where you don't want the surface; it is gated at the infra level, not by a UI toggle.

### Connect a client (Claude Code example)

1. **Mint a personal API key** in **Settings → Security**. Tick **Read-only** for read access only (recommended for most uses); pin it to a **single guild** to limit its blast radius. A full-access key is required only if you want the write tools.
2. **Register the server:**

   ```bash
   claude mcp add --transport http initiative \
     https://your-host/api/v1/mcp/ \
     --header "Authorization: Bearer ppk_your_key_here"
   ```

3. **Use it** — ask your assistant things like *"list my projects in Initiative"* or *"add a task to the Auth project."* Write actions are confirmed by the client before they run.

### What it can access

The surface is curated and **default-deny** — only the following are exposed. Everything else (documents, queues, counters, calendar, tags, members, admin, auth, settings, deletes, bulk operations, and AI generation) is **not**.

**Reads** (any API key):

| Tool | Endpoint |
|---|---|
| List / read projects (+ activity, favorites, export) | `GET /g/{guild}/projects…` |
| List / read tasks and subtasks | `GET /g/{guild}/tasks…` |
| List / read initiatives (+ members, roles, your permissions) | `GET /g/{guild}/initiatives…` |
| Your projects / tasks across all guilds | `GET /me/projects`, `GET /me/tasks` |

**Writes** (full-access key only — a read-only key is rejected with `403`; each is confirmed in the client):

| Tool | Endpoint |
|---|---|
| Create a task | `POST /g/{guild}/tasks/` |
| Edit a task | `PATCH /g/{guild}/tasks/{id}` |
| Move a task | `POST /g/{guild}/tasks/{id}/move` |
| Add a comment | `POST /g/{guild}/comments/` |

### Security notes

- **Least privilege:** prefer a **read-only**, **single-guild** API key. A read-only key cannot invoke the write tools.
- **No ambient access:** the tools carry no standing privilege — each call authenticates as the key's user and is scoped by RLS, exactly like a normal request.
- **Revocable:** delete the key in **Settings → Security** at any time; a password reset also revokes it.

---

## How we build

Initiative is developed in public. The issues, the pull requests, the design discussions, and the mistakes are all here in the open, and the roadmap moves in response to what people actually ask for.

Two commitments shape the work:

- **Nobody should need a course to use this.** If a feature can't be explained in a sentence to someone who has never used project management software, it isn't finished.
- **People think differently, and the software should meet them there.** The same work can be read as a board, a table, a calendar, or a timeline. Keyboard navigation, screen-reader labels, light and dark themes, plain-language documentation, and full localization are part of building a feature, not a follow-up to it.

Improvements to the [help site](docs/en/index.md) are as welcome as improvements to the code.

---

## Roadmap

### Where we are

Initiative is already a full-featured workspace for groups:

* **Tasks** across Kanban, Table, and Calendar views
* **Documents** including rich text, spreadsheets, and whiteboards with real-time collaboration
* **Calendars, queues, counters, and dashboards**
* A curated **marketplace** of ready-made apps and dashboards
* **Notifications** and BYOK AI integration
* **Self-hosting** with Docker and support for multiple guilds

### What's next

**🧩 More apps, more possibilities**
We're continuing to build the marketplace and the ecosystem around it — more dashboards, more useful apps, and better ways for groups to build and share their own.

**🌎 A more connected community**
Initiative is becoming more than a place for private work. We're adding **public content, user profiles, and community features** that make it possible to discover what other people and groups are building.

**✨ Polish everything**
Accessibility, UX improvements, performance, testing, and the countless little things that make Initiative nicer to use.

**🔌 Connect to the rest of your world**
Better APIs, integrations, templates, and apps that securely connect Initiative to the tools your group already uses.

### Where we're headed

Initiative is an **open platform for small groups and communities** — not another enterprise PM suite.

The core application stays **AGPL-licensed and open source**. Apps can be built and distributed independently, whether they're hosted inside Initiative or run as separate services.

**Build something useful. Share it. Find something someone else built. Make Initiative your own.**

---

## Technology Stack

| Layer | Technologies |
|---|---|
| **Backend** | FastAPI, SQLModel + SQLAlchemy, PostgreSQL 17, Alembic, asyncpg |
| **Frontend** | React 19, TypeScript, Vite, React Query, Tailwind CSS, shadcn/ui, dnd-kit |
| **Mobile** | Capacitor (iOS and Android), Firebase push notifications |
| **Infrastructure** | Docker, GitHub Actions (multi-arch builds), Dependabot |

---

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for full development setup, testing, code style, and how to submit pull requests.

**Quick start**: Open the project in VS Code and run **Tasks: Run Task** > **`dev:setup`** from the Command Palette. This starts Postgres, runs migrations, seeds test data, and launches both servers. Login with `admin@example.com` / `changeme`.

---

## Documentation

- **[Help site](docs/en/index.md)** — guides for everyone using Initiative, plus the administrator handbook
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — Development setup, testing, code style, submitting PRs
- **[SECURITY.md](SECURITY.md)** — Security philosophy and vulnerability reporting
- **[CHANGELOG.md](CHANGELOG.md)** — Release history
- **[Docker Hub](https://hub.docker.com/r/morelitea/initiative)** — Published images
- **API docs** — Available at `/api/v1/docs` when running (Swagger UI)

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for details. PRs must target the `dev` branch.

By contributing, you agree to the terms of the [Contributor License Agreement](./CLA.md).

## Security

See [SECURITY.md](SECURITY.md) for our security philosophy and how to report vulnerabilities.

---

## License

This project is source-available under the [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0). Copyright is retained by the project maintainers, who reserve all commercial rights.
