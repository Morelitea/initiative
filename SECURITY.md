# Security Policy

## Our Approach

Initiative follows a principle of least privilege — every user should only have access to the minimum data required for their role. Despite being built for casual groups and small teams, we take data isolation seriously. Your gaming group's campaign notes shouldn't be visible to another group on the same instance.

This philosophy is enforced at multiple layers:

### Database-Level Isolation (Row Level Security)

PostgreSQL Row Level Security (RLS) enforces access boundaries at the database layer, not just in application code. Even if an application bug bypasses a check, the database itself prevents unauthorized data access.

- **Guild isolation**: Users can only see data in guilds they belong to. This is the primary tenancy boundary — each guild's data is invisible to other guilds.
- **Initiative isolation**: A second restrictive RLS layer ensures users can only see data within initiatives they are members of, providing isolation between teams within the same guild. Guild admins and superadmins bypass this layer when needed for administration.

### Discretionary Access Control (DAC)

Within an already-secured initiative, teams can fine-tune who sees what using project and document permissions:

- **Owner, write, and read levels** per user or per initiative role
- **Independent per-resource** — projects and documents have separate permission tables, so access to one doesn't imply access to another

DAC is enforced through application-level permission checks (database rows), not through database policies. RLS guarantees the security boundary; DAC lets teams decide exactly who sees what within that boundary.

### Separated Database Roles

- **`app_user`** — Used for all user-facing API queries. This role has no `BYPASSRLS` privilege, so RLS policies are always enforced.
- **`app_admin`** — Used for migrations, startup seeding, and background jobs. Has `BYPASSRLS` for administrative operations.

### Authentication

- **HttpOnly cookie sessions**: Web sessions use `SameSite=Lax` cookies instead of `localStorage`, eliminating XSS token theft risk. Native (Capacitor) apps use device tokens stored in secure platform storage.
- **OpenID Connect (OIDC) SSO**: Enterprise identity provider integration with PKCE support and automatic claim-to-role mapping.
- **Encryption at rest**: Sensitive fields (AI API keys, OIDC secrets, SMTP passwords, email addresses) are encrypted using Fernet (AES-128-CBC) derived from `SECRET_KEY`.
- **Minimal token scope**: JWTs carry only the claims needed for authentication; guild and role context is resolved server-side per request.

When contributing, treat any path where a user could access data outside their scope as a security issue, not a bug.

## Supported Versions

| Version | Supported |
| ------- | --------- |
| latest  | Yes       |

We recommend always running the latest release. This project hasn't reached a stable v1.0.0 yet, so only the latest version receives fixes.

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly. **Do not open a public GitHub issue.**

### How to Report

Email **security@morelitea.com** with:

- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (optional)

### What to Expect

- Acknowledgment within 48 hours
- An estimated timeline for a fix
- Notification when the vulnerability is resolved
- Credit in the release notes (unless you prefer to remain anonymous)

## Scope

This policy covers:

- Backend API (`backend/`)
- Frontend SPA (`frontend/`)
- Docker configuration and deployment scripts
- GitHub Actions workflows

Third-party dependencies are out of scope, but we appreciate reports about vulnerable transitive dependencies.
