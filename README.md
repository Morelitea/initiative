# Initiative

A self-hosted project management platform designed for friend groups, gaming communities, and small teams who want an intuitive way to organize projects, share documents, and track tasks — without the complexity of enterprise tools.

> **Pre-release software** — this project hasn't reached v1.0.0 yet. The API may change between minor releases.

<img width="2264" height="1315" alt="initiative screenshot" src="https://github.com/user-attachments/assets/c2c6b9c8-3f6f-4d17-a1ba-9338c033674d" />

---

## What is Initiative?

Initiative is project management for people who don't want to think about project management. It's built for groups that need to coordinate work, share information, and stay on the same page — whether you're running a tabletop campaign, organizing a community event, or managing a small team.

- **Guilds** keep each group's data completely separate — run multiple communities from one instance
- **Initiatives** organize related projects and documents so nothing gets lost
- **Drag-and-drop boards** make task tracking visual and immediate
- **Collaborative documents** let your team write and edit together in real time
- **Simple sharing** — control who sees what without needing a degree in access management
- **Self-hosted with Docker** — your data stays on your hardware

---

## Key Features

### Guilds

Each guild is a completely separate workspace — your D&D group and your work team never see each other's data, even on the same server.

- **True data isolation**: PostgreSQL Row Level Security enforces guild boundaries at the database layer
- **Switch between guilds instantly**: Join multiple guilds and move between them with one click
- **Invite links**: Share links with optional expiry dates and usage limits
- **Controlled creation**: Optionally restrict guild creation for hosted deployments

**Guild settings:**
<img width="1905" height="1050" alt="Guild settings" src="https://github.com/user-attachments/assets/656b7d08-0a91-48be-868c-29f545a32165" />

### Initiatives & Projects

Initiatives group related projects and documents together — think of them as folders for an entire effort (a campaign, an event, a product).

- **Everything in one place**: Bundle projects, documents, and team members under a single initiative
- **Automatic scoping**: Members only see initiatives they belong to
- **Custom project boards**: Drag-and-drop Kanban boards with customizable task statuses
- **Color-coded organization**: Visual distinction with initiative-specific colors

**Initiatives page:**
<img width="1905" height="1049" alt="Initiatives page" src="https://github.com/user-attachments/assets/3ea4f727-4f84-4e75-b860-a5bb17cb9e49" />

### Simple Sharing & Permissions

Sharing is straightforward: add people to a guild, add them to an initiative, then choose who can see or edit each project and document. No complicated admin panels required.

- **Initiative roles**: Create roles like "player" or "DM" with different feature access
- **Project & document sharing**: Set owner, write, or read access per user or per role
- **Role-based grants**: Share with an entire role at once instead of adding people one by one

For details on how access control is enforced under the hood, see [SECURITY.md](SECURITY.md).

**Initiative role permissions:**
<img width="1920" height="1080" alt="Initiative role permissions" src="https://github.com/user-attachments/assets/5ee163da-207a-4f57-a95c-659f423eb688" />

**Project/Document access control:**
<img width="1920" height="1079" alt="Project DAC permissions" src="https://github.com/user-attachments/assets/135a733e-3a2b-4cbc-aa66-b1eaf6234d75" />

### Rich Task Management

- **Multiple views**: Table, Kanban, Calendar, and Gantt with row virtualization for large datasets
- **Priority levels**: Low, medium, high, and urgent with visual indicators
- **Flexible scheduling**: Start dates, due dates, and recurring tasks
- **Subtasks**: Break down complex work with completion tracking
- **Multiple assignees**: Assign tasks to multiple team members
- **Server-side pagination & sorting**: Multi-column sort with advanced filtering
- **My Tasks dashboard**: Personal cross-guild view with date grouping and timezone support

**Project Kanban view (Table, Kanban, Calendar, and Gantt views supported):**
<img width="1905" height="1050" alt="Project Kanban view" src="https://github.com/user-attachments/assets/26d169c7-0415-4ea8-b81d-bd1b8f9a0576" />

**Task details:**
<img width="1905" height="1050" alt="Task details" src="https://github.com/user-attachments/assets/cdea8e20-a157-48cb-b5bb-2fdd1f5d5228" />

### Collaborative Documents

- **Rich text editing**: Full-featured editor with JSONB storage
- **Live collaboration**: Real-time multi-user editing via WebSocket
- **File documents**: Upload and manage PDFs, DOCX, and other file types with permission-gated downloads
- **Document templates**: Create reusable templates for common workflows
- **Threaded comments**: Discuss documents with nested comment threads

**Document editor:**
<img width="1905" height="1050" alt="Document editor" src="https://github.com/user-attachments/assets/b7118ed4-01c1-4ac5-b6b7-c1185455e2a2" />

### Command Center

Press `Cmd+K` / `Ctrl+K` to instantly navigate to projects, tasks, documents, and pages with fuzzy search. Available via sidebar shortcut or 3-finger tap on mobile.

### Authentication

- **Email & password** or **OpenID Connect (OIDC) SSO** — connect your existing identity provider
- **OIDC claim-to-role mapping**: Automatically assign guild and initiative memberships from identity provider claims
- **Encryption at rest** for sensitive data — see [SECURITY.md](SECURITY.md) for the full security architecture

### Notifications

- **Real-time updates**: WebSocket-based live updates for collaborative work
- **Per-channel preferences**: Independent email and mobile push toggles per notification category
- **Overdue task digests**: Configurable email digests for overdue tasks
- **Mobile push**: Firebase Cloud Messaging support for iOS and Android

### AI Integration

- **Bring Your Own Key (BYOK)**: Configure API keys for OpenAI, Anthropic, Ollama, or OpenAI-compatible APIs
- **Hierarchical settings**: Platform, guild, and user-level AI configuration with override controls
- **AI-powered tasks**: Generate task descriptions, subtasks, and document summaries

### Internationalization

- Full i18n support with 16 translation namespaces
- English and Spanish locales included (community translations welcome)
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

1. The first user to register becomes the platform admin
2. Configure SMTP in the admin panel to enable email notifications
3. Create your first guild and start inviting team members

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
| `DATABASE_URL` | Superuser PostgreSQL connection (migrations, role creation) | Required |
| `DATABASE_URL_APP` | RLS-enforced connection (`app_user` role) | Required |
| `DATABASE_URL_ADMIN` | Admin connection for background jobs (`app_admin` role) | Required |
| `SECRET_KEY` | JWT signing and encryption key | Required |
| `APP_URL` | Public base URL (required for OIDC callbacks) | - |
| `DISABLE_GUILD_CREATION` | Restrict guild creation to super admin | `false` |
| `ENABLE_PUBLIC_REGISTRATION` | Allow registration without invite link | `true` |
| `BEHIND_PROXY` | Trust `X-Forwarded-For` headers | `false` |
| `FORWARDED_ALLOW_IPS` | Trusted proxy IPs (when `BEHIND_PROXY=true`) | `*` |
| `FIRST_SUPERUSER_EMAIL` | Bootstrap admin email | - |
| `FIRST_SUPERUSER_PASSWORD` | Bootstrap admin password | - |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_PASSWORD` | SMTP server configuration | - |
| `SMTP_FROM_ADDRESS` | Email sender address | - |
| `FCM_ENABLED` | Enable Firebase Cloud Messaging | `false` |
| `PUID` | UID the container runs as (for rootless/NAS setups) | `1000` |
| `PGID` | GID the container runs as (for rootless/NAS setups) | `1000` |

For FCM setup, see [docs/FIREBASE_SETUP.md](docs/FIREBASE_SETUP.md). For a complete list of options, see `backend/.env.example`.

---

## Technology Stack

| Layer | Technologies |
|---|---|
| **Backend** | FastAPI, SQLModel + SQLAlchemy, PostgreSQL 17, Alembic, asyncpg |
| **Frontend** | React 18, TypeScript, Vite, React Query, Tailwind CSS, shadcn/ui, dnd-kit |
| **Mobile** | Capacitor (iOS and Android), Firebase push notifications |
| **Infrastructure** | Docker, GitHub Actions (multi-arch builds), Dependabot |

---

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for full development setup, testing, code style, and how to submit pull requests.

**Quick start**: Open the project in VS Code and run **Tasks: Run Task** > **`dev:setup`** from the Command Palette. This starts Postgres, runs migrations, seeds test data, and launches both servers. Login with `admin@example.com` / `changeme`.

---

## Documentation

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
