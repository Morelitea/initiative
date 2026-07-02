---
icon: lucide/sliders-horizontal
---

# Configuration

Initiative is configured with **environment variables** (set in your `docker-compose.yml`, a `.env` file, or your container environment). This page covers the settings you're most likely to touch. For the complete list, see `backend/.env.example` in the source.

!!! tip "Some things are configured in the app, not here"
    A few areas — email, single sign-on, branding colors, and AI — can be set up from the **Settings → Platform** screens in the running app, by the [owner](platform-roles.md). Those pages are friendlier than environment variables and are covered on their own pages. Environment variables are mainly for the foundational settings below.

## Essential settings

| Variable | What it does | Default |
|---|---|---|
| `SECRET_KEY` | Signs sessions **and** encrypts sensitive stored data. Set a strong, unique value and keep it safe. | *required* |
| `DATABASE_URL` | Provisioning connection — migrations and guild/role creation (`app_provisioner`, not a superuser). | *required* |
| `DATABASE_URL_APP` | Security-enforced connection for normal requests (`app_user`). | *required* |
| `DATABASE_URL_ADMIN` | Connection for migrations and background jobs (`app_admin`). | *required* |
| `APP_URL` | Your public base URL. Needed for single-sign-on callbacks and correct links. | — |

See [Installation](installation.md#the-three-database-connections) for how the three database URLs work together.

## Who can sign up

| Variable | What it does | Default |
|---|---|---|
| `ENABLE_PUBLIC_REGISTRATION` | Allow people to register without an invite link. Set `false` for invite-only. | `true` |
| `DISABLE_GUILD_CREATION` | Stop regular users from creating new guilds (they must be invited to one). | `false` |
| `AUTO_APPROVED_EMAIL_DOMAINS` | Email domains whose sign-ups are approved automatically; others wait for manual approval. | — |

These three together let you run anything from a fully open community server to a locked-down, invite-only, single-organization deployment.

## Running behind a reverse proxy

For any real deployment you'll put Initiative behind a reverse proxy that handles HTTPS.

| Variable | What it does | Default |
|---|---|---|
| `BEHIND_PROXY` | Trust `X-Forwarded-*` headers from your proxy (so client IPs and HTTPS are detected correctly). | `false` |
| `FORWARDED_ALLOW_IPS` | Which proxy IPs to trust when `BEHIND_PROXY=true`. | `*` |

!!! warning "Only enable proxy trust behind an actual proxy"
    Turning on `BEHIND_PROXY` when Initiative is directly exposed would let clients spoof their address. Enable it only when a trusted proxy sits in front.

## Keeping bots out (captcha)

To protect open registration from automated sign-ups, you can require a captcha:

| Variable | What it does |
|---|---|
| `CAPTCHA_PROVIDER` | `hcaptcha`, `turnstile`, or `recaptcha` (v2). Unset disables the captcha. |
| `CAPTCHA_SITE_KEY` | The public key used to show the widget. |
| `CAPTCHA_SECRET_KEY` | The server-side key used to verify responses. |

## AI assistant access (MCP)

| Variable | What it does | Default |
|---|---|---|
| `ENABLE_MCP` | Expose the in-app MCP server (at `<APP_URL>/api/v1/mcp/`) so AI assistants can work with data on a user's behalf, bound by that user's API key and access rules. | `false` |

Leave it off unless you want that surface. See [API keys & integrations](../account/api-keys-and-integrations.md) for how users connect.

## File storage and push notifications

These have their own pages:

- **File storage** — keep uploads on local disk (default) or use S3-compatible object storage. See [Object storage](object-storage.md).
- **Mobile push** — enable Firebase Cloud Messaging. See [Push notifications](push-notifications.md).

## Mobile app version floor

There's a setting (`MIN_NATIVE_VERSION`, tracked in the source) that records the minimum native mobile-app version the current web bundle requires. You rarely touch it by hand — it's part of how the mobile app updates safely over the air. It's mentioned here only so you know what it is if you see it. See [Backups & updates](backups-and-updates.md).

## After changing settings

Most settings are read at startup, so **restart the container** after editing them:

```bash
docker compose up -d
```

## Related

- [Single sign-on](single-sign-on.md) · [Email](email.md) · [Push notifications](push-notifications.md) · [Object storage](object-storage.md)
- [Platform roles](platform-roles.md) — who can change in-app platform settings.
