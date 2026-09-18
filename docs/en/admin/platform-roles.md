---
icon: lucide/shield-half
---

# Platform roles

Two role systems, kept deliberately separate:

- **Community roles** (superadmin / admin / member) govern a single workspace. See [Working with communities](../guides/communities.md).
- **Platform roles** govern the **whole server** — every community, every user. That's this page. The ladder runs member → support → moderator → operator → owner. **Admin** belongs to the community ladder above, and stays there.

Platform roles are managed by the [owner](#the-owner) — and for some actions, operators — from **Settings → Platform** and the **Operator dashboard**.

## The ladder

Five rungs, each adding to the one below:

| Role | What it can do |
|---|---|
| **Member** | Standard access to their own communities. No server-wide privileges. This is everyone by default. |
| **Support** | Read-only visibility across the platform (users, communities, audit), can **request** time-bound access to a community to help with an issue, and can let somebody answer the age question again after a typo. |
| **Moderator** | Everything Support can do, **plus** user management (suspend/reactivate) and content moderation. |
| **Operator** | Manages users, communities, and roles platform-wide, has cross-community access (via break-glass), approves access requests, and writes [announcements](announcements.md). |
| **Owner** | Full control, **including server-wide configuration** (single sign-on, email, branding, AI). The only role that can change configuration. |

!!! info "Capabilities, not just titles"
    Each rung maps to a set of **capabilities**, and features are gated on the capability rather than the role name. The practical upshot is exactly what the table says — but it means the model is precise about *what* each role may do, not just who outranks whom.

## The owner

The **first person to register** on a new server becomes the **owner**. The owner is the only role that can change app-wide configuration, so:

!!! warning "Never leave the server without an owner"
    Don't demote or delete the last owner-level account.

    Initiative does guard against removing the final configuration-holder, but don't rely on that as a plan. Make sure there is always at least one person who can change settings and is reachable.

## Managing platform users

**Operator dashboard → Users** lists every account on the server. A row names somebody by their handle and their address — whatever they filled in as a real name is theirs, and none of this needs it.

**Manage** opens everything you can change about one account:

- **Username** — the handle they're addressed by. The four digits after it stay as they are.
- **Profile picture** — take one down. Putting one up stays theirs.
- **Suspend** — freezes the account. They can still sign in and read why, and reach none of their communities. Nothing is deleted; lifting it hands everything back.
- **Platform role** — move them up or down the ladder. You can't grant a rung above your own.

Each of those asks for its own capability, so a moderator opening the same panel sees the first three and not the fourth.

The row's actions menu keeps the one-off jobs:

- **Reset a user's password** (sends them a reset email).
- **Reactivate** a deactivated account.
- **Export** the user list as CSV.
- **Let someone answer the age question again**, where they answered as under age. Nearly always a mistyped year. It clears the answer and nothing else — they answer again from scratch, and no birthday is recorded either way. See [Asking members their age](configuration.md#asking-members-their-age).
- **Delete a user**, choosing how thorough it is:
    - **Deactivate** — can't sign in; data preserved; reversible.
    - **Anonymize** — personal details removed; their content remains as "Deleted user"; not reversible.
    - **Hard delete** — everything removed, including authored content; not reversible.

Before a destructive delete, Initiative makes you resolve **blockers** — for example, transferring projects the user owns, or promoting a replacement where they held a community's last [superadmin](../guides/communities.md#why-superadmin-is-separate) seat — so nothing important is orphaned.

## Cross-community access: break-glass and time-bound grants

**Nobody holds a standing back door into communities they don't belong to** — not even platform operators. When platform staff genuinely need to reach a community's data, they take **explicit, time-bound, recorded** access instead. Manage it from **Settings → Access**.

### What a grant can say

A request names **what it reaches**, and the two halves are asked for separately:

| | What it reaches |
|---|---|
| **Content** | What the community holds — read-only, or read-and-write. A read-write grant edits existing material; it doesn't author new material or manage members. |
| **Settings** | The community's configuration and nothing inside it, held at **admin** or **superadmin** — the community's own two rungs. Somebody helping with a moderation setting has no business in anybody's documents, and this is how they don't end up there. |

Ask for one, the other, or both. Each is approved and recorded on its own.

### The two paths

- **Request and approve** (Support and Moderator). Someone **requests** what they need, for a chosen number of hours, with a reason. An approver (Operator/Owner) grants or denies it, and it **auto-expires**.
- **Break glass** (Operator and Owner). For urgent situations, an operator can **self-issue** an emergency grant — approved instantly, scoped to that community, expiring automatically. Breaking glass issues both halves, the settings one at superadmin, because an emergency is no time to discover you asked for the wrong shape. Each is named and recorded separately, so afterwards the log says exactly how far it went.

!!! info "A grant is never a membership"
    Whatever it reaches and whoever holds it, a grant runs out. Anything that would outlive it stays out of reach — a grantee can't answer a request to join an initiative, for instance, because the membership on the other side of that answer has no end date.

!!! info "Breaking glass asks for your authenticator code"
    As soon as **anybody** who can break glass has set up [two-factor authentication](../account/two-factor-authentication.md), breaking glass asks everybody for a code — theirs, at the moment they do it. One of your recovery codes works too, which matters, because the phone is the thing most likely to be missing in the hour you need this.

    Nobody switches this on. It follows from who has enrolled, which means it can only ever be on while at least one person can satisfy it — there is no way to end up with a server nobody can break glass into. The flip side is worth knowing before it surprises you: if a colleague enrols and you haven't, your next break-glass is refused until you do. Setting one up takes about a minute, under **Security** in your own settings.

!!! info "Why it's built this way"
    Privileged access has to be deliberately taken, is scoped to one community, expires on its own, and leaves a record naming who took it and why. That's a stronger position than a permanent bypass nobody has to justify. More in [How your data is kept separate](../security/how-your-data-is-kept-separate.md).

![Access requests and break-glass](../images/admin/access-grants.png)

## Announcements

Operators and owners can write **announcements** — notices shown in a dialog to the people using the server. They're for a change somebody has to act on, or would otherwise be confused by. See [Announcements](announcements.md).

## What you decide per community

**Settings → Platform → Communities** lists every community on the server, and **Manage** opens what you set for one of them: its storage and member limits, whether it may configure [its own sign-in](single-sign-on.md#letting-a-community-use-a-provider), and a few features you can switch off. See [File & object storage](object-storage.md#per-community-storage-limits) for the limits.

## Related

- [Announcements](announcements.md) — telling everyone something.
- [Configuration](configuration.md) — foundational settings.
- [Working with communities](../guides/communities.md) — the per-community roles, and the superadmin seat.
- [How your data is kept separate](../security/how-your-data-is-kept-separate.md) — the access model behind all of this.
