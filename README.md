# Initiative

A self-hosted, multi-tenant project management platform built for teams that need workspace isolation, granular permissions, and rich collaboration features.

🚨 This project hasn't yet reached a stable release (v1.0.0). The API can and probably will change between minor releases. 🚨

<img width="2264" height="1315" alt="initiative screenshot" src="https://github.com/user-attachments/assets/c2c6b9c8-3f6f-4d17-a1ba-9338c033674d" />

---

## What is Initiative?

Initiative is a production-ready project management platform that goes beyond simple task tracking. It's designed for organizations that need:

- **Multi-tenant workspaces (guilds)** with true data isolation between teams
- **Hierarchical organization** through initiatives that group related projects and documents
- **Flexible permissions** with 4-layer access control (Platform → Guild → Initiative → Project)
- **Rich collaboration** combining Kanban-style task management with collaborative documents
- **Self-hosted deployment** with Docker, giving you full control over your data

Whether you're managing a single team or multiple client workspaces, Initiative provides the structure and security features to scale with your needs.

---

## Key Features

### Multi-Tenant Workspaces (Guilds)

- **Workspace isolation**: Each guild operates independently with its own teams, projects, and data
- **Database-level security**: PostgreSQL Row Level Security (RLS) enforces guild boundaries at the database layer, preventing cross-guild data access even in the event of application bugs
- **Switch contexts seamlessly**: Join multiple guilds and move between them instantly
- **Guild invitations**: Share invitation links with optional expiry dates and usage limits
- **Per-guild administration**: Guild admins manage their workspace without platform-wide access
- **Controlled creation**: Optionally restrict guild creation for hosted deployments

**Guild settings:**
<img width="1905" height="1050" alt="Guild settings" src="https://github.com/user-attachments/assets/656b7d08-0a91-48be-868c-29f545a32165" />

### Organized Project Hierarchy

- **Initiatives group related work**: Bundle projects and documents under a common initiative
- **Shared team access**: Initiative membership automatically grants access to all projects within
- **Custom project boards**: Drag-and-drop Kanban boards with customizable task statuses
- **Color-coded organization**: Visual distinction with initiative-specific colors

**Initiatives page:**
<img width="1905" height="1049" alt="Initiatives page" src="https://github.com/user-attachments/assets/3ea4f727-4f84-4e75-b860-a5bb17cb9e49" />

### Flexible Permission Model

- **4-layer access control**: Permissions cascade from platform to guild to initiative to resource
- **Initiative roles**: Custom roles with configurable feature access (view/create projects, view/create docs)
- **Project permissions**: Discretionary access control with owner, write, and read levels per user
- **Document permissions**: Independent access control separate from projects, with owner/write/read levels
- **Independent guild administration**: Guild admins manage their workspace without affecting other guilds

**Initiative role permissions:**
<img width="1920" height="1050" alt="Initiative role permissions" src="https://github.com/user-attachments/assets/10b90a79-4fa2-444a-9d97-29cbb8b58d63" />

### Rich Task Management

- **Kanban boards**: Custom task statuses organized into backlog, todo, in-progress, and done categories
- **Priority levels**: Low, medium, high, and urgent priorities with visual indicators
- **Flexible scheduling**: Start dates, due dates, and recurring tasks
- **Subtasks**: Break down complex work with completion tracking
- **Multiple assignees**: Assign tasks to multiple team members
- **My Tasks dashboard**: Personal view with filtering by status, priority, and date

**Project Kanban view (Table, Kanban, Calendar, and Gantt views supported):**
<img width="1905" height="1050" alt="Project Kanban view" src="https://github.com/user-attachments/assets/26d169c7-0415-4ea8-b81d-bd1b8f9a0576" />

**Task details:**
<img width="1905" height="1050" alt="Task details" src="https://github.com/user-attachments/assets/cdea8e20-a157-48cb-b5bb-2fdd1f5d5228" />

### Collaborative Documents

- **Rich text editing**: Full-featured documents with JSONB storage for flexibility
- **Live collaboration**: Collaborate on documents in real time between multiple users
- **Link to projects**: Attach documents to multiple projects for cross-referencing
- **Independent permissions**: Control document access separately from project permissions
- **Document templates**: Create reusable document templates for common workflows
- **Threaded comments**: Discuss documents with team members using nested comments

**Document editor:**
<img width="1905" height="1050" alt="Document editor" src="https://github.com/user-attachments/assets/b7118ed4-01c1-4ac5-b6b7-c1185455e2a2" />

### Authentication & Security

- **JWT-based authentication**: Secure, stateless token-based auth
- **OpenID Connect (OIDC) SSO**: Integrate with enterprise identity providers
- **Email verification**: Confirm user email addresses before account activation
- **API keys**: Secure headless integrations with service accounts

**User security settings:**
<img width="1904" height="1050" alt="image" src="https://github.com/user-attachments/assets/4a1e3f34-fb00-4d07-adfb-bbdbcaec5a61" />

### Notifications & Activity

- **Real-time updates**: WebSocket-based live updates for collaborative work
- **Task notifications**: Get notified when assigned to tasks or when tasks are updated
- **Overdue task digests**: Configurable email digests for overdue tasks
- **Notification preferences**: Control which notifications you receive and when
- **Activity tracking**: Recently viewed projects and favorites for quick access

### AI Integration

- **Bring Your Own Key (BYOK)**: Configure your own API keys for AI providers
- **Multiple providers**: Support for OpenAI, Anthropic, Ollama, and OpenAI-compatible APIs
- **Hierarchical settings**: Platform, guild, and user-level AI configuration with override controls
- **AI-powered task creation**: Generate task descriptions and subtasks using AI
- **Smart suggestions**: Auto-generate subtask breakdowns from task titles and descriptions

### Production Features

- **SMTP email**: Configurable email server for transactional emails and notifications
- **Branding customization**: Customize colors, labels, and branding elements
- **Timezone support**: Per-user timezone settings for accurate date/time display
- **Project archiving**: Move completed projects to archive without deletion
- **Comprehensive admin controls**: Platform-wide settings for superusers

---

## Quick Start

### Using Docker Compose (Recommended)

The fastest way to get Initiative running:

```bash
# 1. Copy the example configuration
cp docker-compose.example.yml docker-compose.yml

# 2. Edit configuration (set a secure SECRET_KEY)
nano docker-compose.yml

# 3. Start the application
docker-compose up -d

# 4. Access Initiative at http://localhost:8173
```

Also configure env variables according to your preferences, see [Key Environment Variables](./README.md#key-environment-variables)

**What's included:**

- PostgreSQL 17 database with persistent storage
- FastAPI backend with automatic migrations
- React frontend served via FastAPI
- Health checks and automatic restarts
- Volume mounts for persistent uploads

**First-time setup:**

- The first user to register will be prompted to create an account
- Configure SMTP settings in the admin panel to enable email notifications
- Create your first guild and start inviting team members

---

## Technology Stack

**Backend:**

- FastAPI (async Python web framework)
- SQLModel + SQLAlchemy (ORM with async support)
- PostgreSQL 17 (with JSONB for flexible document storage)
- Alembic (database migrations)
- asyncpg (high-performance Postgres driver)

**Frontend:**

- React 18 with TypeScript
- Vite (fast build tool and dev server)
- React Query (@tanstack/react-query) for data fetching and caching
- Tailwind CSS for styling
- Shadcn/ui for accessible components
- dnd-kit for drag-and-drop interactions

**Mobile:**

- Capacitor (native iOS and Android apps)
- Push notifications support
- Safe area handling for edge-to-edge displays

**Infrastructure:**

- Docker and Docker Compose
- GitHub Actions (automated multi-arch builds)

---

## Manual Development Setup

For local development without Docker:

### Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL 17

### Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and set DATABASE_URL, SECRET_KEY, and other variables

# Run migrations and seed defaults
alembic upgrade head
# Or use: python -m app.db.init_db

# Start the API server
uvicorn app.main:app --reload
# API available at http://localhost:8000
# API docs at http://localhost:8000/api/v1/docs
```

### Frontend Setup

```bash
cd frontend

# Install dependencies
pnpm install

# Configure API URL (optional, defaults to http://localhost:8000/api/v1)
echo "VITE_API_URL=http://localhost:8000/api/v1" > .env

# Start development server
pnpm dev
# Frontend available at http://localhost:5173
```

### Mobile App Development

Run the backend so that Capacitor apps can connect to it:

```bash
cd backend

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The frontend includes Capacitor for native iOS and Android apps:

```bash
cd frontend

# Build the web app first
pnpm build:capacitor

# Sync web assets to native projects
npx cap sync

# Open in Android Studio
npx cap open android

# Open in Xcode (macOS only)
npx cap open ios
```

**Requirements:**

- Android: Android Studio with SDK installed
- iOS: Xcode on macOS

The mobile app connects to your Initiative server URL configured during build. In the android emulator the local backend will be available at http://10.0.0.2:8000

### Database Migrations

When modifying SQLModel classes:

```bash
cd backend

# Generate migration from model changes
alembic revision --autogenerate -m "Description of changes"

# Apply pending migrations
alembic upgrade head
```

For detailed development guidelines, coding standards, and workflow, see [AGENTS.md](AGENTS.md).

---

## Configuration

### Key Environment Variables

| Variable                     | Description                                                   | Default  | Example                                                        |
| ---------------------------- | ------------------------------------------------------------- | -------- | -------------------------------------------------------------- |
| `DATABASE_URL`               | PostgreSQL connection string                                  | -        | `postgresql+asyncpg://user:pass@localhost:5432/initiative`     |
| `DATABASE_URL_ADMIN`         | Superuser connection for migrations (required for RLS setup)  | -        | `postgresql+asyncpg://postgres:pass@localhost:5432/initiative` |
| `SECRET_KEY`                 | JWT signing key (use a secure random string)                  | Required | `your-secret-key-here`                                         |
| `APP_URL`                    | Public base URL (required for OIDC callbacks)                 | -        | `https://initiative.example.com`                               |
| `DISABLE_GUILD_CREATION`     | Restrict guild creation to super admin only                   | `false`  | `true` or `false`                                              |
| `ENABLE_PUBLIC_REGISTRATION` | Allow public registration without invite link                 | `true`   | `true` or `false`                                              |
| `BEHIND_PROXY`               | Trust X-Forwarded-For headers (behind nginx/load balancer)    | `false`  | `true` or `false`                                              |
| `FIRST_SUPERUSER_EMAIL`      | Bootstrap admin email                                         | -        | `admin@example.com`                                            |
| `FIRST_SUPERUSER_PASSWORD`   | Bootstrap admin password                                      | -        | `secure-password`                                              |
| `SMTP_HOST`                  | SMTP server hostname                                          | -        | `smtp.gmail.com`                                               |
| `SMTP_PORT`                  | SMTP server port                                              | `587`    | `587`                                                          |
| `SMTP_USERNAME`              | SMTP authentication username                                  | -        | `your-email@gmail.com`                                         |
| `SMTP_PASSWORD`              | SMTP authentication password                                  | -        | `your-app-password`                                            |
| `SMTP_FROM_ADDRESS`          | Email sender address                                          | -        | `Initiative <noreply@example.com>`                             |
| `FCM_ENABLED`                | Enable Firebase Cloud Messaging for mobile push notifications | `false`  | `true` or `false`                                              |
| `FCM_PROJECT_ID`             | Firebase project ID                                           | -        | `my-project-id`                                                |
| `FCM_APPLICATION_ID`         | Firebase app ID from google-services.json                     | -        | `1:123456:android:abc123`                                      |
| `FCM_API_KEY`                | Firebase Web API key (from Firebase Console)                  | -        | `AIzaSy...`                                                    |
| `FCM_SENDER_ID`              | FCM sender ID (project_number from google-services.json)      | -        | `123456789`                                                    |
| `FCM_SERVICE_ACCOUNT_JSON`   | Service account JSON for backend (minified, keep secure)      | -        | `{"type":"service_account",...}`                               |

For detailed Firebase/FCM setup instructions, see [docs/FIREBASE_SETUP.md](docs/FIREBASE_SETUP.md).

See `backend/.env.example` for a complete list of configuration options.

---

## Documentation & Resources

- **Development Guidelines**: [AGENTS.md](AGENTS.md) - Repository workflow, issue tracking with bd (beads), coding standards
- **Docker Images**: [morelitea/initiative on Docker Hub](https://hub.docker.com/r/morelitea/initiative)
- **API Documentation**: Available at `/api/v1/docs` when running (interactive Swagger UI)
- **Version Management**: Uses semantic versioning with `VERSION` file as single source of truth

---

## Contributing

By contributing to this project, you agree to the terms of the
[Contributor License Agreement](./CLA.md).

This project uses **bd (beads)** for issue tracking:

```bash
# Check for available issues
bd ready --json

# Claim and start work
bd update <issue-id> --status in_progress

# Close when complete
bd close <issue-id> --reason "Completed"
```

Development workflow:

- Pre-commit hooks enforce linting (Ruff for Python, ESLint for TypeScript)
- See [AGENTS.md](AGENTS.md) for detailed contribution guidelines
- Commit messages should be concise and descriptive

---

## Deployment

### Using Docker Hub Images

Initiative is published to Docker Hub with automated builds:

```bash
# Pull latest version
docker pull morelitea/initiative:latest

# Pull specific version
docker pull morelitea/initiative:0.6.3
```

Images support both `linux/amd64` and `linux/arm64` architectures.

### Version Management

Bump versions using the included script:

```bash
./scripts/bump-version.sh
```

This will:

1. Update the VERSION file
2. Create a git commit and tag
3. Trigger automated Docker builds when pushed

### Automated Builds

Pushing version tags (e.g., `v0.6.3`) triggers GitHub Actions to:

- Build multi-arch Docker images
- Tag as `latest`, `0`, `0.6`, and `0.6.3`
- Push to Docker Hub

---

## License

This project is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).

You are free to use, modify, and self-host this software. If you offer it to users
over a network, you must also make the complete corresponding source code available
to those users, as required by the AGPL.

Commercial licenses are available for organizations that wish to use this software
without AGPL obligations.
