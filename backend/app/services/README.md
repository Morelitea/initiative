# `app/services/` — business logic, split by tenancy boundary

Services hold the domain logic behind the API. They mirror the **schema-per-guild**
boundary (see [`models/`](../models/README.md)). The split is by **the data a
service primarily reads/writes**, so it's obvious whether logic touches per-guild
content or shared/platform data.

| Location | Operates on | Session it runs under | Examples |
|---|---|---|---|
| `tenant/` | per-guild content (`guild_<id>` schemas) | `RLSSessionDep` under `/g/{guild_id}/…` | documents, tasks (statuses), queues, counters, calendar_events, comments, initiatives, properties, project import/export, soft_delete, trash_purge, webhook dispatch/subscriptions |
| `platform/` | shared/public-schema tables | `UserSessionDep` / `AdminSessionDep` (no guild) | users, guilds, access_grants, api_keys, app_settings, push/user tokens, user_notifications, ws_auth |
| *root* (here) | **both sides** — cross-cutting infra | varies / called by both | `rls`, `membership`, `permissions`, `realtime`, `stream_authz`, `email`, `notifications`, `cross_guild`, `ai_settings`, `ai_generation`, `background_tasks`, `soft-delete filters`, `captcha`, `hibp`, … |

## The rule for the root

**Root = "serves both tenant and platform, or is pure infrastructure."** It is the
deliberate home for code that legitimately bridges the boundary:

- `cross_guild.py` powers the `/me/*` aggregates — the **one** sanctioned way to
  read a user's tenant data across guilds (still per-guild-routed under the hood).
- `notifications.py` reads guild content but writes the **public** `Notification`
  inbox; `ai_settings.py` resolves the platform→guild→user config cascade.
- `rls` / `membership` / `permissions` are the shared enforcement layer both sides
  call.

When you add a service, ask **"what data does it own?"** Touches only guild content
→ `tenant/`. Touches only public/platform tables → `platform/`. Genuinely both, or
it's transport/auth/infra → keep it at the root (don't invent a guild context just
to file it). Never give root code standing access to a guild schema without a guild
context — that's the boundary this layout exists to protect.
