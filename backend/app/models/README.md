# `app/models/` — SQLModel tables, split by tenancy boundary

We use **schema-per-guild** multi-tenancy. This is a **hard database-layer
boundary**: guild content lives in per-guild Postgres schemas (`guild_<id>`) that
our infra deploys in isolated namespaces, while identity/platform data lives in
`public`. There is **no cross-guild context at runtime** — the only exception is
the `/me/*` "my X" pages, which aggregate a user's *own* tenant data across their
guilds.

The folders make that boundary visible. **Put every new `table=True` model in the
folder that matches where its table lives** — never at the root.

| Folder | Schema | Holds | Source of truth |
|---|---|---|---|
| `tenant/` | per-guild `guild_<id>` | projects, tasks, documents, queues, counters, calendar, tags, comments, initiatives, uploads, webhooks, resource grants, … | tables in `GUILD_SCOPED_TABLES` |
| `platform/` | `public` | users, guilds, memberships, invites, app settings, access grants, notifications, OIDC, API keys, push/user tokens, view preferences | tables in `SHARED_TABLES` |
| *root* (here) | — | `_mixins.py` and other table-less helpers shared by both | n/a |

> **"Guild" is overloaded.** The `Guild` entity itself (the tenant roster) is a
> **`public`/`platform`** table — it lives in `platform/guild.py`, *not* `tenant/`.
> "tenant" = the per-guild content schema; "platform" = the shared public schema.

## Authoritative classification

This directory only *mirrors* the classification — it is **not** a second copy of
it. The single source of truth is:

- [`app/db/tenancy.py`](../db/tenancy.py) — `SHARED_TABLES` vs `GUILD_SCOPED_TABLES`
- [`app/db/initiative_rls.py`](../db/initiative_rls.py) — which guild tables are
  initiative-scoped (carry the `initiative_member_*` RLS policies)

[`layout_test.py`](layout_test.py) fails CI if a model file's folder disagrees with
`tenancy.py`, so the tree can never silently drift. When you add a table, classify
it in `tenancy.py` / `initiative_rls.py` (see the root `CLAUDE.md`
"Adding or changing tables"), then drop the model in the matching folder.
