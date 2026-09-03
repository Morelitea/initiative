---
icon: lucide/circle-help
---

# Frequently asked questions

Short answers to what people actually ask. Each one points at the longer version.

## Starting out

### Do I need to know project management to use this?

No. A project is a board, a task is a to-do on it, and that's genuinely enough to run real work. Roles, tools, dashboards, apps — they're there when you need them and quiet until then. See [Getting started](getting-started/index.md).

### There's a lot here. Where do I begin?

Make a community, open the **Default Initiative** it comes with, create one project, add some tasks. That's a working setup. Come back for the rest when something feels missing. See [Your first community](getting-started/your-first-community.md).

### Is it free?

Self-hosting is free and always will be — it's open source and it's the complete product, not a trimmed-down version. A paid hosted service is coming for people who'd rather not run a server. See [Self-host or let us host it](self-host-or-hosted.md).

### Can I add tools that aren't built in?

Yes — the **marketplace** has ready-made dashboards and apps, and adding one takes a couple of clicks and no code. It holds what ships with Initiative plus whatever the person running your server has approved, so if something's missing, they're who to ask. See [Apps & the marketplace](guides/apps-and-marketplace.md).

A few apps need a program running alongside Initiative before they work. The **GitHub integration** is one, and it's open source — you can stand it up yourself, though it's a real deployment rather than a setting. **Automations** are ours and live only on the hosted service. See [Apps that need something running behind them](self-host-or-hosted.md#apps-that-need-something-running-behind-them).

## Getting in

### I can't find the community I was told to join

Most communities are private and don't show up anywhere until you're invited. Ask whoever told you about it for an invite link — that link takes you straight there once you've made an account.

If your server runs a [community directory](guides/communities.md#finding-a-community-to-join), listed communities appear under **Join a community** on the community rail. A community that hasn't listed itself won't be there, however hard you search.

### I don't see "Join a community"

The directory is a server-wide feature that starts switched **off**, so plenty of servers don't have one. Everything there is invite-only.

### My invite link says it's no longer valid

Links can expire, get used up, or be switched off by an admin. None of that is about you — ask for a fresh one.

### I don't see a "Create community" button

Some servers turn community creation off on purpose so people join through invites instead. Ask an admin to invite you, or to make one for you.

### I didn't get my verification or password-reset email

Give it a few minutes, then check spam. If it still hasn't landed, the server may not have email set up — ask your administrator. Reset links go stale after a while, so request a fresh one if yours is old. See [Signing in](getting-started/signing-in.md).

### I've been signed out and can't get back in

Changing your password signs out every device — that one's deliberate. If you didn't change it, use **Forgot password** on the sign-in screen. If your server uses single sign-on there may be no password to reset; sign in the way you normally do.

## The age question

### Why am I being asked my date of birth?

Because you're joining, or already in, a community that anyone signed in can find. Those are open to people you've never met, and you need to be **13 or older** to take part.

You're asked once. The answer sticks to your account, so the second community asks nothing.

### What happens to the date?

We work out whether you're old enough, then throw it away. Your account records **that** you answered — never the date. It isn't sold, shared, or stored anywhere.

### I'm not joining anything public. Why was I asked?

Something put you in a listed community without you clicking Join: an admin added you, a single sign-on group sync did, an invite led into one, or a community you were already in listed itself. Any of those counts.

A community that hasn't listed itself never asks — not on an invite, not when you're added.

### My account can't reach anyone

<a id="my-account-cant-message-anyone"></a>

If you can't join communities you can see, and the parts of Initiative open to people outside your own communities are closed to you, it's almost always the age question. Two things look alike:

| What you see | What it is | What to do |
|---|---|---|
| A date-of-birth screen you can't get past | You're in a listed community and haven't answered | Answer it. Once. |
| A screen saying you told us you're not old enough | Your account answered as under 13 | An admin can reset it — see below |

Either way, everything inside communities you were **invited** to still works.

### I typed my birthday wrong and now I'm stuck

Common, and fixable: ask an administrator of your server to **reset the age question**. Anyone on the support tier or above can do it, and it's recorded in the audit log like any other action taken on someone's account.

They can't see what you typed, because it was never kept. Resetting just lets you answer again.

!!! info "Why you can't simply re-answer"
    A question you can retry until it comes out right isn't really a question. So the answer stands, and undoing it takes somebody else — which is why the reset is logged.

### Can this be switched off?

Yes, by the platform owner under **Settings › Admin › Community**. Switching it off is the owner confirming that every account on the deployment belongs to someone 18 or older — which a company or school rollout knows and a public server doesn't. See [Data & compliance](security/data-and-compliance.md).

## Finding things

### I can't find a project or document I know exists

Two likely reasons: you're in a **different community** (check the rail down the far-left edge), or it hasn't been **shared** with you. Fastest way to check is search — ++cmd+k++ / ++ctrl+k++ and type its name. See [Search & shortcuts](guides/search-and-shortcuts.md).

### A link to something says "not found" and I know it's there

If you're not a member of the initiative it lives in, Initiative hides it completely — so a direct link says "not found" rather than "access denied". Ask to be added to the initiative. See [Sharing & access](sharing/index.md).

### My Projects doesn't show everything in my community

It isn't meant to. My Projects, My Documents and My Calendar — and the community front page — show what has reached *you*: shared with you, shared with a role you hold, or shared with everyone in an initiative you're in. Open a single initiative to see all of its work. See [Your space](guides/your-space.md#my-projects).

### I'm a community admin. Why isn't every initiative in my sidebar?

Because navigation follows what you're *in*, not what you *may reach* — otherwise a community with a hundred initiatives buries the three you actually work in. Your authority hasn't changed: open any initiative and you see all of it. To keep one to hand, join it from the community front page (you walk straight in). See [Community admins join like everyone else](guides/initiatives.md#community-admins-join-like-everybody-else).

## Tasks and projects

### Can a task have more than one person on it?

Yes, as many as you like. See [Projects & tasks](guides/projects-and-tasks.md).

### I moved a task to another project and its status changed

Expected. Projects can each have their own statuses, so a moved task restarts at **Backlog**. Set the new one and carry on.

### How do I clear out finished tasks without deleting them?

**Archive** them. There's a one-click "Archive done tasks", and you can filter archived tasks back into view whenever you want. Nothing is lost.

### I deleted something by accident

Check the **Trash** — Community settings for shared things, your own Trash for your items. Deleted things wait there a while before going for good. See [Trash and retention](guides/communities.md#trash-and-retention).

### An import didn't match people to their accounts

Exports and imports identify people by **handle** (`foobar#1234`), because a handle is the same in every community and an email address isn't. A file exported before that was true names people by email and won't match. Export it again. See [Exporting a project](guides/projects-and-tasks.md#exporting-a-project).

## Your account

### Can I change my username?

Not on your own — your handle is how people find and mention you, so changing it is an admin action. Your **display name** is yours to change any time under [Profile & preferences](account/profile-and-preferences.md).

### Why does my name show in one community and not another?

Each community decides whether it shows real names or just handles. In a handles-only community your display name isn't rendered to anyone there.

### My due dates or reminders are off by a few hours

Your **timezone** is wrong. Fix it in **User settings → Interface**.

### I'm getting too many (or too few) emails

Tune them per category in **User settings → Notifications** — each has its own email and mobile toggle. The in-app bell always works regardless. See [Notifications](guides/notifications.md).

### How do I leave a group?

On the community rail, open the community's menu and choose **Leave community**. If you're the last admin, promote someone else first.

### My account is suspended

A suspended account can still sign in and reach its own settings — that's how you get told why. Every community is closed while it lasts, but nothing is taken away: memberships, work, and everything you wrote stay put, and lifting it restores the account whole. Ask an administrator of your server.

### What's the difference between deactivating and deleting my account?

**Deactivating** is reversible — switched off, data kept. **Deleting** is permanent, and you choose whether your past contributions are anonymized or removed outright. See [Closing your account](account/profile-and-preferences.md#closing-your-account).

## Privacy and data

### Can everyone in my community see everything in it?

No. Being in a community doesn't hand you its contents. An **initiative** is only visible to the people added to it, and individual projects and documents narrow further still. The one exception is a **community admin**, who can see everything in their own community. See [Sharing & access](sharing/index.md).

### How do I keep something visible to just two or three people?

Put it in an initiative with only those people in it. That's the strongest everyday boundary and it needs no configuration — everyone else simply doesn't have it. To narrow further inside an initiative, share the specific project or document.

### Can other groups on the same server see our stuff?

No. Each community's data is separated at the database level. See [How your data is kept separate](security/how-your-data-is-kept-separate.md).

### Can an administrator read our private initiative?

A **community admin** can see everything in their own community — that's part of running it. Platform staff on a hosted service get in only through **temporary, recorded** access that expires on its own. See [Platform roles](admin/platform-roles.md).

### Can a community admin read my direct messages?

No. Messages are end-to-end encrypted, so they're readable on the devices in the conversation and nowhere else — not by an admin, not by whoever runs the server, not by us. They're also not community content, so they're not in exports or search. See [Private messages](security/private-messages.md).

### Why don't my messages show up on my new phone?

Because there's no copy on the server for it to catch up from — that's what end-to-end encryption costs. Each device keeps its own history from the moment it joined a conversation, and signing out takes that device's copy with it. See [Your messages live on your devices](guides/messages.md#your-messages-live-on-your-devices).

### Where is my data stored?

If you host Initiative yourself: wherever your server runs, and that's your call. If we host it: where our service runs. Either way it stays yours. See [Data & compliance](security/data-and-compliance.md).

### Can I get my data out?

Yes. Projects export to a portable file, spreadsheets to CSV or Excel, calendars to `.ics`. See [Getting your data out](security/data-and-compliance.md#getting-your-data-out).

## For administrators

### How do I update to a new version?

Back up, then `docker compose pull` and `docker compose up -d`. Migrations run themselves. See [Backups & updates](admin/backups-and-updates.md).

### What do I need to back up?

The database and the uploads, together and regularly — plus keep your `SECRET_KEY` somewhere safe so a restore can actually decrypt.

### Can I connect our company login?

Yes — Initiative speaks OIDC, including mapping your provider's groups to communities and roles. See [Single sign-on](admin/single-sign-on.md).

## Still stuck?

If it's the software rather than your account, see [Reporting a problem](security/reporting-a-problem.md). If it's about a specific community — who's in it, what you can reach — ask that community's admins first. They can see and fix far more of it than the server's operators can.
