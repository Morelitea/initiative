---
icon: lucide/home
---

# Working with guilds

A **guild** is your group's workspace — one separate space for one group of people. This guide covers moving between guilds, inviting people, and (if you're an administrator) looking after one.

If you haven't joined or created a guild yet, start with [Your first guild](../getting-started/your-first-guild.md).

## Switching between guilds

You can belong to many guilds at once. The **guild switcher** sits at the very top of the sidebar and shows the one you're currently in.

- Click it to see your other guilds and switch to one.
- Switching changes everything below it — initiatives, projects, your home dashboard — to that guild.
- Each guild is independent. Work, people, and settings never cross between them.

!!! tip "Two guilds at once"
    Open Initiative in two browser tabs and you can have each tab in a different guild — handy if you're juggling, say, a work team and a side project.

## Inviting people (administrators)

Guild administrators bring new people in with **invite links**.

1. Go to **Guild settings → Users**.
2. Create an **invite link**.
3. Optionally set limits:
    - **Max uses** — how many people may join with this one link.
    - **Expires in (days)** — when the link stops working.
4. **Copy the link** and share it however you like (email, chat, etc.).

Anyone who opens the link can join the guild after signing in or creating an account.

!!! screenshot "Guild settings — Users and invites"
    **Show:** the Guild settings "Users" tab, with the member list and the invite-link controls (Max uses, Expires in).

    Save as `en/images/guilds/guild-users.png`, then use:
    `![Managing members and invites in Guild settings](../images/guilds/guild-users.png)`

## Member roles

Inside a guild there are two roles:

| Role | What they can do |
|---|---|
| **Member** | Take part in the initiatives and projects they're added to. |
| **Admin** | Everything a member can do, **plus** manage the guild: members, invites, initiatives, settings, and more. A guild admin can see and manage everything in their guild. |

Administrators can promote a member to admin, or step a member back down, from **Guild settings → Users**.

!!! note "Guild admin is not the same as the app's owner"
    Being an admin of *your* guild gives you full control of that guild — but not of the whole server or other people's guilds. Server-wide roles are a separate thing, covered in [Platform roles](../admin/platform-roles.md).

## Guild settings (administrators)

Open **Guild settings** from the sidebar (or the guild switcher). You'll find tabs for:

- **Guild** — the name, description, and icon. (Icons should be a square image, up to 512&nbsp;KB.)
- **Users** — members, their roles, and invite links.
- **Initiatives** — create and manage the guild's initiatives.
- **AI** — optional AI settings for the guild (see [AI features](../account/ai-features.md)).
- **Trash** — recently deleted items, which you can restore.
- **Danger zone** — sensitive actions, including deleting the guild.

### Trash and retention

When something is deleted, it isn't gone immediately — it goes to the guild's **Trash**, where an admin can restore it. You can set how long items stay before they're cleared for good (a number of **days**, or **never auto-purge** to keep them indefinitely). This is your safety net for accidental deletions.

### The danger zone

The **Danger zone** holds actions that are hard or impossible to undo — most importantly, **deleting the guild**. Deleting a guild permanently removes *everything* in it: initiatives, projects, tasks, documents, and members. To prevent accidents, you'll be asked to confirm carefully (including re-entering details). Only do this if you're certain.

??? techspec "For the technically minded — what guild deletion does"
    Deleting a guild removes its isolated database area and the database roles tied to it, and cleans up the shared records that connect people to it (memberships, invites, single-sign-on mappings, access grants). It's thorough and final. If you only want to step back from a guild without destroying it, **leave** it instead (from the guild switcher) — that just removes *you*.

## Leaving a guild

Don't want to be in a guild anymore? Open the **guild switcher** and choose **Leave guild**. This removes you only — the guild and everyone else carry on. If you're the *last administrator*, you'll need to promote someone else to admin first, so the guild isn't left without anyone in charge.

## Related

- [Initiatives](initiatives.md) — organizing work inside a guild.
- [Sharing & access](../sharing/index.md) — who can see what.
- [Security & privacy](../security/index.md) — how guilds stay separate.
