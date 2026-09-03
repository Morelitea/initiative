---
icon: lucide/circle-help
---

# Frequently asked questions

Short answers to the things people ask most. Each links to the fuller explanation.

## Starting out

### Do I need to know project management to use Initiative?

No. A project is a board, a task is a to-do on it, and that's enough to run real work. Everything else — roles, tools, dashboards, apps — is there when a need for it turns up, and stays out of the way until then. See [Getting started](../getting-started/index.md).

### There's a lot here. Where do I actually begin?

Make a community, open the **Default Initiative** it comes with, and create one project. Add tasks. That's a working setup. Come back for the rest when something feels missing. See [Your first community](../getting-started/your-first-community.md).

### Can I add tools that aren't built in?

Yes — the **marketplace** has ready-made dashboards and apps. Adding one takes a couple of clicks, and no code. What's on offer is what ships with Initiative plus what your platform owner has approved, so if something you want isn't there, they're who to ask. See [Apps & the marketplace](../guides/apps-and-marketplace.md).

## Getting in

### I didn't get my verification or password-reset email.

Wait a few minutes and check your spam folder. If it still hasn't arrived, the server may not have email set up — ask your administrator. Reset links also expire after a while, so request a fresh one if yours is old. See [Signing in](../getting-started/signing-in.md).

### I don't see a "Create community" button.

Some servers turn off community creation on purpose, so people join through invites instead. Ask an administrator to invite you, or to create a community for you. See [Your first community](../getting-started/your-first-community.md).

### My invite link says it's no longer valid.

Invite links can be set to expire or to allow a limited number of uses. Ask whoever sent it for a fresh one.

## Finding things

### I can't find a project or document I know exists.

Two likely reasons: you're in a **different community** (check the **community rail** down the far-left edge), or it hasn't been **shared** with you. The fastest way to look is search — press ++cmd+k++ / ++ctrl+k++ and type its name. See [Search & shortcuts](../guides/search-and-shortcuts.md).

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

Check the **Trash** (in Community settings, or your personal Trash for your own items). Deleted things wait there for a while before being removed for good. See [Working with communities](../guides/communities.md#trash-and-retention).

## Account and notifications

### Why are my due dates or reminders off by a few hours?

Your **timezone** is probably wrong. Fix it in **User settings → Interface**. See [Profile & preferences](../account/profile-and-preferences.md).

### I'm getting too many (or too few) emails.

Tune them per category in **User settings → Notifications** — each has its own email and mobile toggle. The in-app bell always works regardless. See [Notifications](../guides/notifications.md).

### How do I leave a group?

On the **community rail**, open the community's menu and choose **Leave community**. If you're the last admin, promote someone else first. See [Working with communities](../guides/communities.md#leaving-a-community).

### What's the difference between deactivating and deleting my account?

**Deactivating** is reversible — you're switched off but your data is kept. **Deleting** is permanent, and you choose whether your past contributions are anonymized or fully removed. See [Profile & preferences](../account/profile-and-preferences.md#closing-your-account).

## Privacy and data

### Can everyone in my community see everything in it?

No. Being in a community doesn't give you its contents — an **initiative** is only visible to the people added to it, and individual projects and documents can be narrowed further still. The one exception is a **community admin**, who can see everything in their own community. See [Sharing & access](../sharing/index.md).

### How do I keep something visible to just two or three people?

Put it in an initiative with only those people in it. That's the strongest everyday boundary and it needs no configuration — everyone else simply doesn't have it. To narrow within an initiative, share the specific project or document. See [Sharing projects & documents](../sharing/sharing-projects-and-documents.md).

### Can other groups on the same server see our stuff?

No. Each community's data is isolated at the database level — other groups can't reach it. See [How your data is kept separate](../security/how-your-data-is-kept-separate.md).

### Can an administrator read our private initiative?

A **community admin** can see everything in their own community — that's part of running it. Platform staff on a hosted service can only get in through **temporary, recorded** access, never a standing back door. See [Platform roles](../admin/platform-roles.md).

### I'm a community admin. Why doesn't my sidebar list every initiative?

Because navigation follows what you're *in*, not what you may reach. Your sidebar and the community front page show the initiatives you've joined, then the ones on offer — the same view everyone else gets — so a community with a hundred initiatives doesn't bury the three you work in. Your authority is unchanged: open any initiative and you see all of it. To keep one to hand, join it from the community front page (you walk straight in) or take the project manager role from **Community settings → Initiatives**. See [Community admins join like everyone else](../guides/initiatives.md#community-admins-join-like-everyone-else).

### My Projects doesn't show everything in my community.

It isn't meant to. The cross-community lists — My Projects, My Documents, My Calendar — and the community front page show what has reached *you*: shared with you, shared with a role you hold, or shared with everyone in an initiative you're in. Open a single initiative to see all of its work. See [Your space](../guides/your-space.md#my-projects).

### Where is my data stored?

Wherever your server runs — Initiative is self-hosted, so your group controls the location. See [Data & compliance](../security/data-and-compliance.md).

### Can I get my data out?

Yes. Export projects to a portable file, spreadsheets to CSV/Excel, and calendars to `.ics`. See [Data & compliance](../security/data-and-compliance.md#getting-your-data-out).

### An import didn't match people to their accounts.

Exports and imports identify people by **handle** (`foobar#1234`), because a handle is the same in every community. A file exported before that was true names people by email address and won't match; export it again and the new file will. See [Exporting a project](../guides/projects-and-tasks.md#exporting-a-project).

## For administrators

### How do I update to a new version?

Back up, then `docker compose pull` and `docker compose up -d`. Migrations run automatically. See [Backups & updates](../admin/backups-and-updates.md).

### What do I need to back up?

The database and the uploads — together and regularly — plus keep your `SECRET_KEY` safe so a restore can decrypt. See [Backups & updates](../admin/backups-and-updates.md).

### Can I connect our company login?

Yes — Initiative supports single sign-on (OIDC), including mapping your provider's groups to communities and roles. See [Single sign-on](../admin/single-sign-on.md).
