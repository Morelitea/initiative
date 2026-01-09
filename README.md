# Initiative

A self-hosted, multi-tenant project management platform built for teams that need workspace isolation, granular permissions, and rich collaboration features.

<img width="2264" height="1317" alt="initiative screenshot" src="https://github.com/user-attachments/assets/da060ad0-5562-44e7-8c52-3a5e1d696f96" />

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
- **Switch contexts seamlessly**: Join multiple guilds and move between them instantly
- **Guild invitations**: Share invitation links with optional expiry dates and usage limits
- **Per-guild administration**: Guild admins manage their workspace without platform-wide access
- **Controlled creation**: Optionally restrict guild creation for hosted deployments

### Organized Project Hierarchy

- **Initiatives group related work**: Bundle projects and documents under a common initiative
- **Shared team access**: Initiative membership automatically grants access to all projects within
- **Custom project boards**: Drag-and-drop Kanban boards with customizable task statuses
- **Color-coded organization**: Visual distinction with initiative-specific colors

### Flexible Permission Model

- **4-layer access control**: Granular permissions cascade from platform to guild to initiative to project
- **Initiative project managers**: Designated team members control initiative access and project creation
- **Project-level overrides**: Grant explicit write access to specific users beyond initiative membership
- **Independent guild administration**: Guild admins manage their workspace without affecting other guilds

### Rich Task Management

- **Kanban boards**: Custom task statuses organized into backlog, todo, in-progress, and done categories
- **Priority levels**: Low, medium, high, and urgent priorities with visual indicators
- **Flexible scheduling**: Start dates, due dates, and recurring tasks
- **Subtasks**: Break down complex work with completion tracking
- **Multiple assignees**: Assign tasks to multiple team members
- **My Tasks dashboard**: Personal view with filtering by status, priority, and date

### Collaborative Documents

- **Rich text editing**: Full-featured documents with JSONB storage for flexibility
- **Link to projects**: Attach documents to multiple projects for cross-referencing
- **Independent permissions**: Control document access separately from project permissions
- **Document templates**: Create reusable document templates for common workflows
- **Threaded comments**: Discuss documents with team members using nested comments

### Authentication & Security

- **JWT-based authentication**: Secure, stateless token-based auth
- **OpenID Connect (OIDC) SSO**: Integrate with enterprise identity providers
- **Email verification**: Confirm user email addresses before account activation
- **API keys**: Secure headless integrations with service accounts

### Notifications & Activity

- **Real-time updates**: WebSocket-based live updates for collaborative work
- **Task notifications**: Get notified when assigned to tasks or when tasks are updated
- **Overdue task digests**: Configurable email digests for overdue tasks
- **Notification preferences**: Control which notifications you receive and when
- **Activity tracking**: Recently viewed projects and favorites for quick access

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

| Variable                   | Description                                   | Example                                                    |
| -------------------------- | --------------------------------------------- | ---------------------------------------------------------- |
| `DATABASE_URL`             | PostgreSQL connection string                  | `postgresql+asyncpg://user:pass@localhost:5432/initiative` |
| `SECRET_KEY`               | JWT signing key (use a secure random string)  | `your-secret-key-here`                                     |
| `APP_URL`                  | Public base URL (required for OIDC callbacks) | `https://initiative.example.com`                           |
| `DISABLE_GUILD_CREATION`   | Restrict guild creation to super admin only   | `true` or `false`                                          |
| `FIRST_SUPERUSER_EMAIL`    | Bootstrap admin email                         | `admin@example.com`                                        |
| `FIRST_SUPERUSER_PASSWORD` | Bootstrap admin password                      | `secure-password`                                          |
| `SMTP_HOST`                | SMTP server hostname                          | `smtp.gmail.com`                                           |
| `SMTP_PORT`                | SMTP server port                              | `587`                                                      |
| `SMTP_USERNAME`            | SMTP authentication username                  | `your-email@gmail.com`                                     |
| `SMTP_PASSWORD`            | SMTP authentication password                  | `your-app-password`                                        |
| `SMTP_FROM_ADDRESS`        | Email sender address                          | `Initiative <noreply@example.com>`                         |

See `backend/.env.example` for a complete list of configuration options.

---

## Documentation & Resources

- **Development Guidelines**: [AGENTS.md](AGENTS.md) - Repository workflow, issue tracking with bd (beads), coding standards
- **Docker Images**: [morelitea/initiative on Docker Hub](https://hub.docker.com/r/morelitea/initiative)
- **API Documentation**: Available at `/api/v1/docs` when running (interactive Swagger UI)
- **Version Management**: Uses semantic versioning with `VERSION` file as single source of truth

---

## Contributing

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

See repository for license information.
