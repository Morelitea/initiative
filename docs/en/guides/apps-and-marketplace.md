---
icon: lucide/store
---

# Apps & the marketplace

Whatever your group needs, some other group has needed exactly the same thing, built it, got fed up rebuilding it every year, and shared it.

The **marketplace** is where those live: ready-made dashboards and apps you add in a couple of clicks. No developer. No custom build. No waiting for us to get round to shipping it.

Your marketplace holds the listings that ship with Initiative plus whatever the person running your server has added and approved. Nothing turns up on it by accident — everything there is there because a human put it there.

## Two marketplaces

There are two, and the difference is who gets what you take.

| | **Your community's** | **Yours** |
|---|---|---|
| What's on it | Dashboards and apps | Decoration packs |
| Who it's for | Everyone in that community | You, in every community you're in |
| Where to open it | **Browse the marketplace** on your dashboards list, or the **Apps** section of the sidebar | **Browse the marketplace** on **User settings → Profile** |

![Browsing the marketplace](../images/marketplace/browse.png)

## Your community's marketplace

| | **Dashboards** | **Apps** |
|---|---|---|
| What it adds | A screen of charts, numbers and timelines | Something the whole community shares |
| Where it goes | Into one initiative | Into the community |
| Who can add it | Anyone who can create dashboards in that initiative | Community admins only |

Both browse the same way: search, open a listing to read what it does, add it.

### Adding a dashboard

1. Open the listing and choose **Add to an initiative**.
2. Pick the **initiative** it should live in.
3. Give it a **name** — the listing's name is filled in, changeable now or later.

It appears under that initiative's **Dashboards**, exactly like one you built. Rename it, tag it, share it, delete it like any other tool.

!!! info "No initiative to choose from?"
    You can only add a dashboard where you're allowed to create one. If the list is empty, ask an initiative manager to give your role the dashboard permission — see [Initiative roles](../sharing/initiative-roles.md).

A listing's page can show a **preview** drawn with sample data, so you can see the shape of it before committing. Yours will show your group's real numbers.

When the publisher ships a newer version, the dashboard shows **Version X available**. Updating is your choice; nothing changes underneath you. If a listing needs a newer Initiative than your server runs, it says so rather than half-working.

### Adding an app

An **app** adds something to the community as a whole rather than one effort — a shared surface, extra dashboard widgets, or a connection to a service your group already uses. Because it affects everyone, **only community admins can add or remove one**.

1. Switch the marketplace to the **Apps** shelf and open a listing.
2. **Add to community**, and name it.
3. If it needs setting up, it's marked **Needs setup** — open its settings to finish.

The Apps shelf lists the apps your server actually runs. Some need a program running alongside Initiative, and one your server hasn't set up — or has switched off — isn't offered here.

Expected something and can't find it? Whoever runs your server is who to ask. On the hosted service they're already running — see [Self-host or let us host it](../self-host-or-hosted.md#apps-that-need-something-running-behind-them).

Installed apps appear in the **Apps** section at the top of the sidebar, above your initiatives, and are managed under **Community settings → Apps**.

### Setting an app up

Some apps need a credential — an API key, or a sign-in to another service. Two kinds, and the difference matters:

- **Community credential** — set once by an admin, used for everyone. Good for a shared account the whole group works through.
- **Your account** — each member supplies their own, used only for them. Yours is yours; other members can't see or use it.

Each connection shows which service it uses and what it's allowed to do there, so you can decide before you hand anything over.

### Turning an app off, and removing it

- **Turn off** hides it from everyone while keeping its setup. Turn it back on and it picks up where it left off. Disabled apps stay listed in **Community settings → Apps**.
- **Remove** takes it out entirely. Anything it created moves to the **Trash**, restorable during the retention window. Every credential it held — the community's and each member's — is deleted, and the app is told to stop using them.

## Your own marketplace

Yours holds **decoration packs**: artwork for your profile, and by far the least serious part of Initiative.

Each pack is built around one thing a group of people has in common, and carries banners, frames and trophies you wear in whatever combination pleases you.

Twenty-three packs ship with Initiative:

| | |
|---|---|
| **People and identity** | Pride, Multicultural, Disability, First Nations, Black heritage, Faith and Belief, Family |
| **What you do** | Sports, Gaming, Drama, Cinema, Soundcheck, Observatory, Education |
| **What you love** | Pets, Plants, Books, Tea, Travel, Nature, Winter, Zen, Spooky |

Some run deep. Pride flies a flag, a turning ring and a heart for each of seven identities. Multicultural carries seventy flags. Disability has a trophy for eleven of the things people are, and a flag for all of them.

The banners move, too: a playhead lights the notes it passes, a curtain runs in and out, skeletons dance until sunrise, a typewriter types a line at a time, a lake changes color the whole way down as the sun sets into it, and the view from a train window keeps going past.

What you take here is yours, not your community's. Download a pack in one community and you're wearing it in all of them, because your profile belongs to you.

1. Open **Browse the marketplace** on **User settings → Profile**.
2. Open a pack to see everything in it, and the profile it would make — banner running, frame around your own picture, trophies underneath.
3. **Get this pack**, and its pieces land in your collection.

Downloading a pack puts nothing on you. It just hands you the pieces — you choose what to actually wear back on **User settings → Profile**, mixing pieces from different packs however you like. Nobody is going to stop you. See [Profile & preferences](../account/profile-and-preferences.md#decorations).

Giving one back is the same click in reverse — open the pack's card and remove it. Its pieces leave your collection, and anything from it you were wearing comes off with them.

![Decoration packs](../images/marketplace/decoration-packs.png)

## Where listings come from

Every listing in your marketplace arrived one of two ways:

- It **ships with Initiative** — part of the built-in catalog, credited to Initiative. That credit can't be claimed by anything else.
- Your **platform owner added it** — they chose that listing and published it to your deployment. If you run Initiative yourself, that's you.

There's no third way. Anyone can write a listing; reaching *your* marketplace is a decision your platform owner makes, one listing at a time. See [Publishing your own listings](../admin/publishing-listings.md).

Every listing shows **who published it** — on the card, on its page, and in the dialog where you add it — so the question is answered while you're deciding.

Two things hold whatever you install:

- **Your access rules still apply.** A dashboard shows *you* only the data you could already reach — same community, initiative, role and sharing checks as everywhere else. Two people on the same dashboard can correctly see different numbers.
- **Widgets run in a sandbox.** Marketplace widgets run in an isolated runtime that can only hand back something to draw. If one misbehaves, that tile shows an error and the rest of the page carries on.

## Related

- [Profile & preferences](../account/profile-and-preferences.md) — wearing what a decoration pack gave you.
- [Tools](tools.md) — the calendar, queues, counters and dashboards built into every initiative.
- [Sharing & access](../sharing/index.md) — who can see what you add.
- [Publishing your own listings](../admin/publishing-listings.md) — for admins adding to their server's marketplace.
