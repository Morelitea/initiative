---
icon: lucide/users
---

# Your first community

A **community** is a workspace — a separate space for one group of people and all their work. Before you can do much, you need to be in one. There are three ways: **join** an existing community by invitation, **find** one that has listed itself publicly, or **create** a new one.

## Joining a community (the usual way)

Most people join a community that already exists, using an **invite link** from someone in the group (a community administrator).

1. **Open the invite link.** It takes you to Initiative.
2. **Sign in** (or [create your account](create-account.md) if you haven't yet).
3. You're in. The link adds you to the community and drops you on its home screen.

That's all there is to it. The community now appears on the **community rail** down the far-left edge of the screen.

!!! note "Invite links can expire"
    For safety, an invite link may have a limited number of uses or an expiry date. If yours says it's no longer valid, ask the person who sent it for a fresh one.

## Finding a community yourself

Some communities list themselves publicly so anyone can find them. Under the **add-a-community** button on the community rail, choose **Join a community** to browse them by category or search by name — then join straight from a community's card, no invite needed.

If you don't see **Join a community**, this server hasn't switched the directory on, and every community here is invite-only. There's more in [Finding a community to join](../guides/communities.md#finding-a-community-to-join).

## Creating a community

If you're starting fresh — setting up a space for your own group — you can create a community yourself, as long as your server allows it.

1. On the **community rail** down the far-left edge of the screen, choose **Create community** (look for an **add** / **+** control on the rail).
2. Give it a **name** — usually just the name of your group, business, or household ("Fairview Bakery," "PTA Committee," "The Nguyens"). You can add an **icon** to make it easy to recognize.
3. Create it. You're now the community's first **administrator**.

![Creating a new community](../images/getting-started/create-community.png)

!!! info "Don't see a 'Create community' option?"
    Some servers turn off community creation on purpose, so that everyone joins through invites instead. If you can't create one, ask an administrator to invite you to a community — or to create one for you.

## What you get in a brand-new community

Every new community starts with a **Default Initiative** — a ready-made folder so you have somewhere to put your first project right away. You can rename it, add more initiatives, and invite people whenever you like.

A natural first move is to create a project:

1. Open the **Default Initiative** in the sidebar.
2. Choose **Create Project**, give it a name, and you've got your first task board.

We cover all of this in detail in [Using Initiative](../guides/index.md).

## Switching between communities

You can belong to as many communities as you like — your workplace, your volunteer committee, your family — and each stays completely separate. Use the **community rail** on the far-left edge of the screen to move between them — click a community's icon to switch. Switching changes everything else (the sidebar, initiatives, and projects) to that community and opens its front page.

??? techspec "For the technically minded — communities are a hard boundary"
    A community isn't just a label. Each community's content lives in its own database schema, created when the community is created, and a request is routed into exactly one of them — so you can only ever read or write communities you belong to, enforced at the database level rather than in the interface. Two browser tabs can even sit in two different communities at once without leaking between them. This is the foundation of how Initiative keeps groups' data apart; see [How your data is kept separate](../security/how-your-data-is-kept-separate.md).

## Next

You're set up and in a group. From here, dive into [how Initiative is organized](../concepts/index.md) to build a clear mental picture — or jump straight to the [how-to guides](../guides/index.md).
