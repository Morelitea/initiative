---
icon: lucide/activity
---

# How it runs

Most of the time you will never need this page. Initiative starts, repairs what it can, and gets on with it.

It's here for the three moments when that isn't what happened: the upgrade that took longer than you expected, the start that refused, and the day you decide one container isn't enough any more.

## What a start actually does

Every start, not just the first one:

1. **Applies the prerequisites its own logins can't create** — the three database roles, and the search index's match operator. From `DATABASE_URL_BOOTSTRAP` if you've set it, otherwise it checks them and names anything missing. See [Installation](installation.md#the-database-connections).
2. **Runs any migrations the database hasn't had yet.**
3. **Brings every community's own database space up to the current shape** — new tables, columns, indexes, grants.
4. **Checks its own wiring**, repairs what is repairable, and stops if something is not.
5. **Creates the first owner**, on a genuinely empty database.

Steps 2 and 3 are why **the first start after an upgrade takes longer than a restart does**, sometimes by minutes on a server with a lot of communities. It is doing schema work, once. The start after that is quick again.

Communities are stamped with the shape they were last built to, and a start skips the ones already current — so the cost is proportional to what changed, not to how many communities you have. If you ever need to sweep every one of them regardless, set **`FORCE_GUILD_BACKFILL=true`** for a single start and then take it back out.

!!! warning "Don't interrupt the first start after an upgrade"
    Let it finish. The log names each step as it reaches it, and signs off the community rebuild with how many it rebuilt and how many were already current.

    One community that can't be rebuilt is logged by name and skipped, rather than taking the whole start down with it — so a warning naming a community id is the thing to go and look at, not a reason nobody can sign in.

## When it refuses to start

It stops rather than starting wrong, and it tells you which of these it is. All three print the fix.

| It says | What happened |
|---|---|
| The main database connection is a superuser | `DATABASE_URL` is the least-privilege `app_provisioner` login, and the rules described in [How your data is kept separate](../security/how-your-data-is-kept-separate.md) are written around it being exactly that. Point it at that role. If you're mid-migration and need the old wiring to boot meanwhile, **`ALLOW_PRIVILEGED_DATABASE_UNTIL`** takes an absolute UTC date and keeps it starting until then — saying so, loudly, every time. It's a deadline to fix it by, not a setting to keep. |
| A connected login is missing privileges | Usually a restored backup or a hand-created role: the login exists but the grants that came with it didn't. It prints the exact `GRANT` statements to run. |
| The database predates v0.53.5 | Its migration history no longer exists in this chain. It prints the upgrade path rather than letting the migration tool fail obscurely. |

And two it will warn about but carry on through:

- **Two of the three connections sharing one login.** It works. The three are separate on purpose — each is its own trust surface — so the warning names the split it would rather have, and then gets on with starting.
- **The search match operator missing**, because declaring it needs a superuser and your database owner isn't one. Search still works. It reads more of its index to do it.

## Running more than one

Initiative expects to run as several worker processes, and scales out to more than one container without anything else to install.

The piece that usually forces a broker — one worker needs to nudge a browser attached to a different worker — rides **PostgreSQL's own `LISTEN`/`NOTIFY`** instead. No Redis, no queue, no extra port, no second credential to rotate. The nudge carries no content: it says "this changed", and the browser re-asks through the ordinary access rules.

Two consequences worth knowing before you build around it:

- **That listener holds its own connection**, deliberately apart from the pools. If you put a connection pooler in front of the database, it needs a connection that survives — a transaction-mode pool can't carry `LISTEN`. Give it a session-mode route, or leave the app's own connection direct.
- **A nudge reaches whoever is listening at that moment.** There's no replay for a worker that was restarting, which is why nothing load-bearing depends on one.

Give every replica the same `SECRET_KEY` and the same database. They'll sort the rest out between themselves, including which one creates the first owner on an empty database.

## What's worth watching

- **Disk**, for the uploads volume and the database. The one that fills first is usually uploads.
- **The start after an upgrade**, once, to see it finish.
- **A [backup](backups-and-updates.md) actually coming back**, on something that isn't your live server.

## Related

- [Installation](installation.md) — the four database connections and what each is for.
- [Configuration](configuration.md) — the settings behind all of this.
- [Backups & updates](backups-and-updates.md) — upgrading safely.
- [How your data is kept separate](../security/how-your-data-is-kept-separate.md) — what the database is enforcing while all this runs.
