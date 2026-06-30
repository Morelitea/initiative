---
icon: lucide/users
---

# Your first guild

A **guild** is a workspace — a separate space for one group of people and all their work. Before you can do much, you need to be in one. There are two ways: **join** an existing guild, or **create** a new one.

## Joining a guild (the usual way)

Most people join a guild that already exists, using an **invite link** from someone in the group (a guild administrator).

1. **Open the invite link.** It takes you to Initiative.
2. **Sign in** (or [create your account](create-account.md) if you haven't yet).
3. You're in. The link adds you to the guild and drops you on its home screen.

That's all there is to it. The guild now appears in your **guild switcher** at the top of the sidebar.

!!! note "Invite links can expire"
    For safety, an invite link may have a limited number of uses or an expiry date. If yours says it's no longer valid, ask the person who sent it for a fresh one.

## Creating a guild

If you're starting fresh — setting up a space for your own group — you can create a guild yourself, as long as your server allows it.

1. Open the **guild switcher** at the top of the sidebar.
2. Choose **Create guild** (or **Create a new guild**).
3. Give it a **name** (for example, "Tuesday Night D&D" or "Marketing Team"). You can add an **icon** to make it easy to recognize.
4. Create it. You're now the guild's first **administrator**.

!!! screenshot "Creating a guild"
    **Show:** the "Create guild" dialog with the guild name field (and icon option).

    Save as `en/images/getting-started/create-guild.png`, then use:
    `![Creating a new guild](../images/getting-started/create-guild.png)`

!!! info "Don't see a 'Create guild' option?"
    Some servers turn off guild creation on purpose, so that everyone joins through invites instead. If you can't create one, ask an administrator to invite you to a guild — or to create one for you.

## What you get in a brand-new guild

Every new guild starts with a **Default Initiative** — a ready-made folder so you have somewhere to put your first project right away. You can rename it, add more initiatives, and invite people whenever you like.

A natural first move is to create a project:

1. Open the **Default Initiative** in the sidebar.
2. Choose **Create Project**, give it a name, and you've got your first task board.

We cover all of this in detail in [Using Initiative](../guides/index.md).

## Switching between guilds

You can belong to as many guilds as you like — your gaming group, your volunteer committee, your workplace — and each stays completely separate. Use the **guild switcher** at the top of the sidebar to move between them. Switching changes everything below it (initiatives, projects, your home dashboard) to that guild.

??? techspec "For the technically minded — guilds are a hard boundary"
    A guild isn't just a label. Each guild's content lives in its own isolated area of the database, and the system enforces that you can only ever read or write guilds you belong to — at the database level, not just in the interface. Two browser tabs can even sit in two different guilds at once without leaking between them. This is the foundation of how Initiative keeps groups' data apart; see [How your data is kept separate](../security/how-your-data-is-kept-separate.md).

## Next

You're set up and in a group. From here, dive into [how Initiative is organized](../concepts/index.md) to build a clear mental picture — or jump straight to the [how-to guides](../guides/index.md).
