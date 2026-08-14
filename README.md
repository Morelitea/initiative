# Initiative

Collaborative project management for people who never wanted to become project managers — small groups, small businesses, event coordinators, clubs, families, and anyone else who needs to organize work with other people.

> **Pre-release software** — this project hasn't reached v1.0.0 yet. The API may change between minor releases.

<img width="2264" height="1315" alt="initiative screenshot" src="https://github.com/user-attachments/assets/c2c6b9c8-3f6f-4d17-a1ba-9338c033674d" />

---

## What is Initiative?

Most project management software assumes you've already learned project management. Initiative doesn't. You can be productive on day one knowing exactly one thing: a **board with tasks on it**. Everything else waits until you need it.

That matters because the people doing the coordinating usually aren't specialists. They're the owner of a five-person business who can't justify hiring a coordinator. The person running the neighborhood fundraiser. The parent keeping a household's plans in one place. The volunteer who ended up with the spreadsheet.

Initiative is built on three ideas:

- **It grows with you.** Start with one board. Add a calendar when you start scheduling, a document when you start writing things down, a dashboard when you start reporting. Nothing you haven't asked for gets in your way.
- **You decide exactly who sees what.** Each group's data sits in its own database schema, and the layers inside it are enforced by the database itself — not just hidden in the interface. Someone who isn't part of an effort doesn't see a locked door; they see nothing at all.
- **The tools come from the community.** The exact thing your group needs usually already exists, because someone with the same problem built it. Dashboards and apps are installed from a marketplace, not commissioned from a developer — and whoever runs your Initiative decides which ones it offers.

And it's built in the open — publicly, with contributions and feedback shaping what gets made.

---

## Key Features

### Guilds — your group's own space

A **guild** is one organization's space: a business, a club, a committee, a household. Everything that group works on lives inside it, and guilds never see each other — even on the same server.

- **A structural boundary, not a filter**: every guild gets its **own PostgreSQL schema**, provisioned when the guild is created. A request is routed into one guild's schema and cannot address another's tables at all
- **Layered inside that**: within the schema, Row Level Security enforces the initiative, role, and sharing layers on every statement — so the boundary between two efforts in the *same* guild is a database boundary too
- **Belong to as many as you like**: your work team and your volunteer committee are two guilds, one click apart
- **Invite links**: share a link with an optional expiry date and usage limit
- **Controlled creation**: optionally restrict who can create guilds

**Guild settings:**
<img width="1905" height="1050" alt="Guild settings" src="https://github.com/user-attachments/assets/656b7d08-0a91-48be-868c-29f545a32165" />

### Initiatives — one effort at a time

An **initiative** gathers everything belonging to a single effort: a product launch, a spring event, a client, a season. Projects, documents, calendars, and dashboards all live inside one.

This is also the privacy boundary that matters most day to day. **If someone isn't in an initiative, its contents don't exist for them** — not greyed out, not "access denied," simply not there.

- **Everything for one effort in one place**: projects, documents, tools, and the people involved
- **Add only who belongs**: the summer event team never sees the spring event's budget
- **Custom boards**: drag-and-drop Kanban with statuses you define
- **Color-coded**: tell your efforts apart at a glance

**Initiatives page:**
<img width="1905" height="1049" alt="Initiatives page" src="https://github.com/user-attachments/assets/3ea4f727-4f84-4e75-b860-a5bb17cb9e49" />

### Sharing that reads like a sentence

Add someone to the guild. Add them to the initiative. Give them a role. Share the specific things they need. Each step narrows the last, and you can stop at any of them.

- **Initiative roles**: bundle permissions into roles that match how your group actually works — "Coordinator," "Volunteer," "Client"
- **Per-item sharing**: give view, edit, or owner access on a single project or document
- **Share with a role**: hand access to a whole role at once instead of one person at a time
- **Bulk edits**: select several items in a list and change who can reach them in one step

For how these boundaries are enforced under the hood, see [SECURITY.md](SECURITY.md).

**Initiative role permissions:**
<img width="1920" height="1080" alt="Initiative role permissions" src="https://github.com/user-attachments/assets/5ee163da-207a-4f57-a95c-659f423eb688" />

**Project/Document access control:**
<img width="1920" height="1079" alt="Project DAC permissions" src="https://github.com/user-attachments/assets/135a733e-3a2b-4cbc-aa66-b1eaf6234d75" />

### Tasks, seen the way you think

The same work, shown however makes sense to you — a list, a board, or a calendar. No one has to adopt someone else's way of looking at it.

- **Multiple views**: Table, Kanban, and Calendar, with row virtualization for large datasets
- **Priority levels**: low, medium, high, and urgent with visual indicators
- **Flexible scheduling**: start dates, due dates, and recurring tasks
- **Subtasks**: break down bigger work with completion tracking
- **Multiple assignees**: several people on one task, each finishing their own part
- **Server-side pagination & sorting**: multi-column sort with advanced filtering
- **My Tasks**: your own work from every guild, in one place

**Project Kanban view (Table, Kanban, and Calendar views supported):**
<img width="1905" height="1050" alt="Project Kanban view" src="https://github.com/user-attachments/assets/26d169c7-0415-4ea8-b81d-bd1b8f9a0576" />

**Task details:**
<img width="1905" height="1050" alt="Task details" src="https://github.com/user-attachments/assets/cdea8e20-a157-48cb-b5bb-2fdd1f5d5228" />

### Documents you write together

- **Rich text editing**: full-featured editor with JSONB storage
- **Spreadsheets**: formulas, number formats, frozen headers, CSV/XLSX import and export
- **Whiteboards**: a free-form Excalidraw canvas for diagrams and visual planning, with live multiplayer cursors and PNG/SVG export
- **Live collaboration**: real-time multi-user editing over WebSocket
- **File documents**: upload PDFs, DOCX, and more, with permission-gated downloads
- **Templates**: save a starting point and reuse it
- **Threaded comments**: discuss in place, in nested threads

**Document editor:**
<img width="1905" height="1050" alt="Document editor" src="https://github.com/user-attachments/assets/b7118ed4-01c1-4ac5-b6b7-c1185455e2a2" />

### Tools you add when you need them

Each initiative can turn on extra tools — none of them are in your way until you ask for them:

- **Calendar & events** — schedule things, invite people, collect RSVPs, send reminders
- **Queues** — track whose turn it is, for rotations, rosters, and running orders
- **Counters** — track numbers that go up and down: scores, tallies, budgets
- **Dashboards** — a canvas of charts, numbers, and timelines built from your own data

### A marketplace of ready-made tools

The dashboards and apps your group needs are usually the ones another group already needed. Initiative ships a **marketplace**: browse a listing, add it to an initiative or your guild, rename it, and it's yours. Every listing shows who published it, and updates are opt-in.

**Every marketplace is curated.** A deployment offers the listings that ship with Initiative, plus the ones its **platform owner has added and approved** — nothing appears in your marketplace that the person running your server didn't put there. If you self-host, that person is you.

- **Dashboards** — add a ready-made reporting canvas to an initiative
- **Apps** — add something the whole guild shares; only guild admins can install them
- **Sandboxed** — marketplace widgets run in an isolated runtime with no access to your credentials or the page around them
- **Curate your own** — point Initiative at a directory of listing files and those listings appear alongside the built-ins, with no fork and no rebuild. Anyone can write one; what reaches your marketplace is your call (see [Publishing your own listings](docs/en/admin/publishing-listings.md))

### Command Center

Press `Cmd+K` / `Ctrl+K` to jump to any project, task, document, or page with fuzzy search. Also available from the sidebar, or a 3-finger tap on mobile.

### Authentication

- **Email & password** or **OpenID Connect (OIDC) SSO** — connect the identity provider you already use
- **OIDC claim-to-role mapping**: assign guild and initiative memberships automatically from provider claims
- **Encryption at rest** for sensitive data — see [SECURITY.md](SECURITY.md) for the full architecture

### Notifications

- **Real-time updates**: WebSocket-based live updates for collaborative work
- **Per-channel preferences**: independent email and mobile push toggles per category
- **Overdue task digests**: configurable email digests
- **Mobile push**: Firebase Cloud Messaging for iOS and Android

### AI Integration

- **Bring Your Own Key (BYOK)**: configure keys for OpenAI, Anthropic, Ollama, or OpenAI-compatible APIs
- **Hierarchical settings**: platform, guild, and user-level configuration with override controls
- **AI-assisted work**: generate task descriptions, subtasks, and document summaries

### Internationalization

- Full i18n support with a namespace per feature area
- English, Spanish, German, and French locales included (community translations welcome)
- Locale-aware AI content generation

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

### Current status

Most core features are implemented and in use:

- Task management across Kanban, Table, and Calendar views
- Collaborative documents — rich text, spreadsheets, and whiteboards — with real-time editing
- Calendars, queues, counters, and dashboards
- A curated marketplace of ready-made dashboards and apps
- Notifications and BYOK AI integration
- Self-hosted via Docker, with multi-guild support

### Focus for upcoming iterations

- **Iterate and polish** — debugging, UX refinements, accessibility
- **Stability** — standardized testing across the board, CI/CD improvements
- **Build your own add-on apps** — a published template for building and hosting an app of your own, so a self-hoster can extend Initiative the same way we do
- **A richer marketplace** — more listings, and apps that connect Initiative securely to the other tools your group already uses
- **More templates** and improved API endpoints for integrations

### Long-term

- The app in this repository is the whole app, and stays AGPL-licensed.
- Some add-on apps are built to run as hosted services rather than inside the container, and are distributed separately. The app template above is how you build your own on the same footing.
- Initiative stays aimed at small groups, small businesses, and communities — not at enterprises with a dedicated PMO.

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
