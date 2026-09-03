---
icon: lucide/users
---

# Your first community

A **community** is a workspace — one separate space for one group of people and everything they work on. You need to be in one before you can do much. Three ways in: **join** by invitation, **find** one that's listed itself publicly, or **create** your own.

## Joining by invite (the usual way)

Most people arrive on an **invite link** from someone already in the group.

1. **Open the link.**
2. **Sign in**, or [create your account](create-account.md) if you haven't.
3. You're in — on the community's home screen, with its icon now on the rail.

That's the whole thing.

!!! note "Invite links can expire"
    A link may have a use limit or an expiry date. If yours says it's no longer valid, ask whoever sent it for a fresh one. Nothing's wrong with your account.

## Finding one yourself

Some communities list themselves so anyone can find them. Hit the **add-a-community** button on the rail and choose **Join a community** to browse by category or search by name — then join straight from a community's card. No invite, no waiting.

No **Join a community** option? This server hasn't switched the directory on, so everything here is invite-only. More in [Finding a community to join](../guides/communities.md#finding-a-community-to-join).

## Creating one

Starting fresh for your own group? Make a community yourself, if your server allows it.

1. On the **community rail**, choose **Create community** (look for the **+**).
2. Give it a **name** — usually just your group: "Fairview Bakery", "PTA Committee", "The Nguyens". An **icon** makes it easy to spot on the rail.
3. Create it. You're now its first **administrator**.

![Creating a new community](../images/getting-started/create-community.png)

!!! info "No 'Create community' option?"
    Some servers switch it off on purpose so everyone joins through invites. Ask an administrator to invite you, or to make one for you.

## What a brand-new community comes with

A **Default Initiative** — a ready-made folder, so you have somewhere to put your first project immediately. Rename it, add more initiatives, invite people, whenever you like.

The natural first move:

1. Open the **Default Initiative** in the sidebar.
2. **Create Project**, give it a name, and there's your first task board.

All of that in detail in [Using Initiative](../guides/index.md).

## Switching between communities

Belong to as many as you like — work, your volunteer committee, your family — and each stays completely separate. Click a community's icon on the rail to switch; the sidebar, initiatives and projects all swap over with you.

??? techspec "For the technically minded — a community is a hard boundary"
    Each community's content lives in its own database schema, created with the community, and a request is routed into exactly one of them — so reads and writes reach only communities you belong to, enforced at the database level rather than in the interface. Two browser tabs can sit in two different communities at once with no crossover. See [How your data is kept separate](../security/how-your-data-is-kept-separate.md).

## Next

You're in a group. Build a mental picture with [how Initiative is organized](../concepts/index.md), or skip straight to the [how-to guides](../guides/index.md).
