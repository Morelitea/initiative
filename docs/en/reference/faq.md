---
icon: lucide/circle-help
---

# Frequently asked questions

Short answers to the things people ask most. Each links to the fuller explanation.

## Getting in

### I didn't get my verification or password-reset email.

Wait a few minutes and check your spam folder. If it still hasn't arrived, the server may not have email set up — ask your administrator. Reset links also expire after a while, so request a fresh one if yours is old. See [Signing in](../getting-started/signing-in.md).

### I don't see a "Create guild" button.

Some servers turn off guild creation on purpose, so people join through invites instead. Ask an administrator to invite you, or to create a guild for you. See [Your first guild](../getting-started/your-first-guild.md).

### My invite link says it's no longer valid.

Invite links can be set to expire or to allow a limited number of uses. Ask whoever sent it for a fresh one.

## Finding things

### I can't find a project or document I know exists.

Two likely reasons: you're in a **different guild** (check the switcher at the top of the sidebar), or it hasn't been **shared** with you. The fastest way to look is search — press ++cmd+k++ / ++ctrl+k++ and type its name. See [Search & shortcuts](../guides/search-and-shortcuts.md).

### Why does a link to something give "not found" when I know it's there?

If you're not a member of the initiative it lives in, Initiative hides it completely — so a direct link shows "not found" rather than "access denied." Ask to be added to the initiative. See [Sharing & access](../sharing/index.md).

## Tasks and projects

### Can a task have more than one person on it?

Yes — tasks can have several assignees. See [Projects & tasks](../guides/projects-and-tasks.md).

### I moved a task to another project and its status changed.

That's expected. Projects can have their own statuses, so a moved task restarts at **Backlog** in its new home. Just set the new status.

### How do I clean up finished tasks without deleting them?

**Archive** them. There's a one-click "Archive done tasks," and you can filter to show archived tasks again later. Nothing is lost.

### I deleted something by accident.

Check the **Trash** (in Guild settings, or your personal Trash for your own items). Deleted things wait there for a while before being removed for good. See [Working with guilds](../guides/guilds.md#trash-and-retention).

## Account and notifications

### Why are my due dates or reminders off by a few hours?

Your **timezone** is probably wrong. Fix it in **User settings → Profile**. See [Profile & preferences](../account/profile-and-preferences.md).

### I'm getting too many (or too few) emails.

Tune them per category in **User settings → Notifications** — each has its own email and mobile toggle. The in-app bell always works regardless. See [Notifications](../guides/notifications.md).

### How do I leave a group?

Open the guild switcher and choose **Leave guild**. If you're the last admin, promote someone else first. See [Working with guilds](../guides/guilds.md#leaving-a-guild).

### What's the difference between deactivating and deleting my account?

**Deactivating** is reversible — you're switched off but your data is kept. **Deleting** is permanent, and you choose whether your past contributions are anonymized or fully removed. See [Profile & preferences](../account/profile-and-preferences.md#closing-your-account).

## Privacy and data

### Can other groups on the same server see our stuff?

No. Each guild's data is isolated at the database level — other groups can't reach it. See [How your data is kept separate](../security/how-your-data-is-kept-separate.md).

### Can an administrator read our private initiative?

A **guild admin** can see everything in their own guild — that's part of running it. Platform staff on a hosted service can only get in through **temporary, recorded** access, never a standing back door. See [Platform roles](../admin/platform-roles.md).

### Where is my data stored?

Wherever your server runs — Initiative is self-hosted, so your group controls the location. See [Data & compliance](../security/data-and-compliance.md).

### Can I get my data out?

Yes. Export projects to a portable file, spreadsheets to CSV/Excel, and calendars to `.ics`. See [Data & compliance](../security/data-and-compliance.md#getting-your-data-out).

## For administrators

### How do I update to a new version?

Back up, then `docker compose pull` and `docker compose up -d`. Migrations run automatically. See [Backups & updates](../admin/backups-and-updates.md).

### What do I need to back up?

The database and the uploads — together and regularly — plus keep your `SECRET_KEY` safe so a restore can decrypt. See [Backups & updates](../admin/backups-and-updates.md).

### Can I connect our company login?

Yes — Initiative supports single sign-on (OIDC), including mapping your provider's groups to guilds and roles. See [Single sign-on](../admin/single-sign-on.md).
