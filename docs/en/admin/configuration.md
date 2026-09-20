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
| `APP_URL` | Your public base URL. Needed for single-sign-on callbacks and correct links. Passkeys are bound to its host: change the host and every passkey registered stops answering, so people sign in another way and add new ones. | — |

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

Someone who answers "not old enough yet" keeps that answer, so the question isn't asked until it comes out right. The usual cause is a mistyped year; support staff and above can reset it from the [operator dashboard](platform-roles.md#managing-platform-users).

### What new accounts can be reached at

Direct messages are off by default: every account is created on the **Private** policy, meaning nobody can even ask to message them until the person opens it up. The starting policy sits under the same **Settings → Platform → Community** tab.

It's read **once**, when an account is made. Changing it opens no existing account and closes none either — people who already have a setting keep it. See [Who can reach you](../guides/messages.md#who-can-reach-you).

### How long people stay signed in

Two different things, and it's worth keeping them apart.

A session ends on its own when nobody uses it — that's the inactivity window, and it slides forward every time the app is opened. Somebody who uses Initiative every day never reaches it.

The other one is the **absolute** limit: the longest anybody may go before signing in again, no matter how much they use it. Nothing slides it. It's blank by default, meaning there isn't one — a server you run for a club is not answering to an auditor — and it lives in **Settings → Platform → Security**, in hours.

!!! warning "Set it longer than the inactivity window"
    Set it shorter and it becomes the *only* thing ending a session: the inactivity window can never be reached first, so everybody gets signed out on a timer whether they're using the app or not. That may be exactly what you want. It's just rarely what somebody means to do.

Web sessions already open keep the terms they were opened under and pick up the new one next time those people sign in.

!!! warning "The app on a phone is different"
    A phone holds a longer-lived credential, and the new limit is written into the ones already issued — measured from when that person last signed in. So somebody whose phone signed in three days ago, on a deployment that has just set twelve hours, is signed out at once and asked for their password again. Shortening the number, or turning on a community's twelve-hour switch, can therefore sign phones out immediately. Lengthening the number, or clearing it, signs nobody out — and a phone that is still signed in goes back to the longer window from its next renewal. A phone that was already signed out stays signed out: it has to sign in again, which is the point.

**A community can hold itself to a stricter one.** Where you've [let a community configure its own sign-in](single-sign-on.md#letting-a-community-use-a-provider), the switch is theirs rather than yours: under that community's own **Settings → Security**, and it's twelve hours — the figure HIPAA and NIST both land on. Its members then sign in again on that schedule whatever your own number says, and being in two such communities is still twelve hours, not six.

### Requiring two-factor authentication

By default nobody has to have [two-factor authentication](../account/two-factor-authentication.md) — anybody can set it up, and nobody is nagged. **Settings → Platform → Security** lets you change that, in two sizes:

| Who you ask | What it means |
|---|---|
| **People with a platform role** | Support, moderators, operators and owners. The people who can see across the whole server rather than just their own communities. |
| **Everybody** | Every account here. Communities stop being offered the question, because it's already answered for their members. |

Either one counts an authenticator app **or** a passkey — whichever somebody has, they're covered. So is somebody whose single sign-on did the second factor on the way in, even if they have nothing set up here.

Nobody is signed out. The next time somebody this covers opens the app they're asked to set one up, where they stand, and carry on once they have.

!!! warning "Personal API keys and the app on a phone stop first"
    Neither can type in a code, so for anybody this covers they stop working until that person sets a factor up — and start working again the moment they do. If you turn this on for everybody, expect a scripted integration or two to go quiet for as long as it takes its owner to spend a minute on their Security page.

    The page tells you how many people don't have a factor yet before you save, which is a reasonable proxy for how much of that you're about to cause.

Two things the page will stop you doing, both for the same reason: you can't require a factor while you haven't got one yourself, and you can't withdraw the authenticator app and passkeys from the [ways in](single-sign-on.md) while a requirement is standing. Lower the requirement first, then withdraw.

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

## Logs

Two streams come out of the container, and they are for different readers.

**Standard error** is the application talking: what it checked at start-up, what it repaired, anything it thinks you should know. `LOG_LEVEL` says how much. It's `INFO` unless you set it; `WARNING` if you would rather only hear about trouble; `DEBUG` when you are chasing something and want all of it.

**Standard output** is the audit stream: one JSON object per line, one line per recorded action — who did what, to which account or community, when — and nothing else on that stream. Every line carries `"stream": "audit"`, so a collector can route these and nothing else, and `"service": "initiative"`, so where the billing and automation services ship the same kind of line about the same community, a reader can tell whose it is. Whatever already ships your container's logs carries it, and a log platform reads it as records rather than text.

That is where the record is kept, searched and alerted on. A filter on `event_type` is an alert; `guild_id` is on every line about a community. `LOG_LEVEL` has no say over any of it.

**Every line says which request it came from.** A `context` block carries the id that request is known by, the network address it arrived from, and what the browser or app called itself. The same id goes back to the caller as an `X-Request-Id` header, and behind a reverse proxy an id the proxy has already assigned is kept rather than replaced — so one request has one name in your proxy's log, your application log and the audit stream alike. People appear as account ids; no line holds a password, a key, an email address or anybody's name.

**Somebody visiting a community they don't belong to is recorded request by request.** Support access and emergency break-glass both work by a grant, and while one is live every single request made under it is a line of its own — the route, the method, the answer, and which grant allowed it. Knowing an operator held the keys for an hour is not the same as knowing what they opened, and this is the difference.

**What stays on the box.** Docker holds a container's output in a file that keeps growing until you say how much to keep. The example compose file says the last 50 MB per container, in five files it rotates through. Treat that as a buffer rather than the record: if the audit stream matters to you, ship it somewhere durable and let the buffer cover the stretch when the shipper is down.

## After changing settings

Most settings are read at startup, so **restart the container** after editing them:

```bash
docker compose up -d
```

## Related

- [Single sign-on](single-sign-on.md) · [Email](email.md) · [Push notifications](push-notifications.md) · [Object storage](object-storage.md) · [Publishing your own listings](publishing-listings.md)
- [Platform roles](platform-roles.md) — who can change in-app platform settings.
