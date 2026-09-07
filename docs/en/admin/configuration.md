---
icon: lucide/sliders-horizontal
---

# Configuration

Initiative is configured with **environment variables**, set in your `docker-compose.yml`, a `.env` file, or your container environment. This page covers what you're most likely to touch; the complete list is `backend/.env.example` in the source.

!!! tip "Some things are configured in the app, not here"
    Email, single sign-on, branding colors and AI are all set up from **Settings → Platform** in the running app, by the [owner](platform-roles.md) — friendlier than environment variables, and covered on their own pages. Environment variables are for the foundational settings below.

## Essential settings

| Variable | What it does | Default |
|---|---|---|
| `SECRET_KEY` | Signs sessions **and** encrypts sensitive stored data. Set a strong, unique value and keep it safe. | *required* |
| `DATABASE_URL` | Provisioning connection — migrations and community/role creation (`app_provisioner`, not a superuser). | *required* |
| `DATABASE_URL_APP` | Security-enforced connection for normal requests (`app_user`). | *required* |
| `DATABASE_URL_ADMIN` | Connection for migrations and background jobs (`app_admin`). | *required* |
| `APP_URL` | Your public base URL. Needed for single-sign-on callbacks and correct links. | — |

See [Installation](installation.md#the-database-connections) for how the database URLs work together.

## Who can sign up

| Variable | What it does | Default |
|---|---|---|
| `ENABLE_PUBLIC_REGISTRATION` | Allow people to register without an invite link. Set `false` for invite-only. | `true` |
| `DISABLE_GUILD_CREATION` | Stop regular users from creating new communities (they must be invited to one). | `false` |

Between them, you can run anything from a wide-open public server to a locked-down, invite-only, one-organization deployment.

### The community directory

Communities can also list themselves publicly, so people find and join them without an invite. That whole feature is **off** until you turn it on, from **Settings → Platform → Community** as the [owner](platform-roles.md).

While it's off there is nothing to browse, nobody can join a community without an invite, and the listing control doesn't appear in community settings at all. Turning it off again later hides the directory rather than un-listing anyone: switch it back on and the same communities are there.

Listing is then each community admin's own decision: they pick the community's categories and certify that it holds no adult or illegal content. Initiative refuses to list a community with room for only a single member. See [Listing your community](../guides/communities.md#listing-your-community-admins).

### Asking members their age

Because a listed community is open to people its members haven't met, Initiative asks anyone joining one to confirm they're **13 or older**, once. The date of birth they give is used to work out the answer and then discarded — the account records only that they answered — and only the parts of Initiative open to strangers ask at all. See [Finding a community to join](../guides/communities.md#finding-a-community-to-join).

The question sits under the same **Settings → Platform → Community** tab, as **Ask members to confirm they are 13 or older**, and is on by default. Turn it off only on a deployment where you already know every account belongs to an adult — Initiative asks you to confirm that, because nobody is asked again afterwards, including people who join a listed community later.

Someone who answers "not old enough yet" keeps that answer, so the question isn't asked until it comes out right. The usual cause is a mistyped year; support staff and above can reset it from the [admin dashboard](platform-roles.md#managing-platform-users).

### What new accounts can be reached at

Direct messages are off by default: every account is created on the **Private** policy, meaning nobody can even ask to message them until the person opens it up. The starting policy sits under the same **Settings → Platform → Community** tab.

It's read **once**, when an account is made. Changing it opens no existing account and closes none either — people who already have a setting keep it. See [Who can reach you](../guides/messages.md#who-can-reach-you).

## Running behind a reverse proxy

For any real deployment you'll put Initiative behind a reverse proxy that handles HTTPS.

| Variable | What it does | Default |
|---|---|---|
| `BEHIND_PROXY` | Trust `X-Forwarded-*` headers from your proxy (so client IPs and HTTPS are detected correctly). | `false` |
| `FORWARDED_ALLOW_IPS` | Which proxy IPs to trust when `BEHIND_PROXY=true`. | `*` |

!!! warning "Only enable proxy trust behind an actual proxy"
    `BEHIND_PROXY` tells Initiative to believe the `X-Forwarded-*` headers it receives. Only turn it on when a trusted proxy is the one setting them.

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

## Your own marketplace listings

| Variable | What it does | Default |
|---|---|---|
| `MARKETPLACE_EXTRA_CATALOG_DIR` | A directory of listing files this server publishes as its own. Mount a folder there and its listings appear in your marketplace beside the built-in ones. Unset means no directory is read. | — |

See [Publishing your own listings](publishing-listings.md).

## File storage and push notifications

These have their own pages:

- **File storage** — keep uploads on local disk (default) or use S3-compatible object storage. See [Object storage](object-storage.md).
- **Mobile push** — enable Firebase Cloud Messaging. See [Push notifications](push-notifications.md).

## Mobile app version floor

`MIN_NATIVE_VERSION` (tracked in the source) records the minimum native mobile-app version the current web bundle needs. You rarely touch it by hand — it's part of how the mobile app updates safely over the air. Mentioned here only so it isn't a mystery if you spot it. See [Backups & updates](backups-and-updates.md).

## After changing settings

Most settings are read at startup, so **restart the container** after editing them:

```bash
docker compose up -d
```

## Related

- [Single sign-on](single-sign-on.md) · [Email](email.md) · [Push notifications](push-notifications.md) · [Object storage](object-storage.md) · [Publishing your own listings](publishing-listings.md)
- [Platform roles](platform-roles.md) — who can change in-app platform settings.
