# Security Policy

## Our Approach

Initiative follows a principle of least privilege — every user should only have access to the minimum data required for their role. This philosophy is enforced at multiple layers:

- **PostgreSQL Row Level Security (RLS)**: Guild-level data isolation is enforced at the database layer, not just in application code. Even if an application bug bypasses a check, the database itself prevents cross-guild data access.
- **Layered permissions**: Access is scoped through four levels — platform, guild, initiative, and resource — so that each boundary narrows what a user can see and do.
- **Separated database roles**: User-facing queries run through a restricted `app_user` role that cannot bypass RLS. Administrative operations use a separate `app_admin` role only where necessary.
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
