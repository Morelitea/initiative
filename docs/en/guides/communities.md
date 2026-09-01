---
icon: lucide/home
---

# Working with communities

A **community** is your group's workspace — one separate space for one group of people. This guide covers moving between communities, inviting people, and (if you're an administrator) looking after one.

If you haven't joined or created a community yet, start with [Your first community](../getting-started/your-first-community.md).

## Switching between communities

You can belong to many communities at once. The **community rail** runs down the far-left edge of the screen — a vertical strip of icons, one per community. The highlighted icon is the community you're in now, and the **Initiative logo** above the communities takes you to [your personal space](your-space.md).

- Click any community's icon to switch to it.
- Switching changes everything else — the sidebar, initiatives, and projects — over to that community.
- Each community is independent. Work, people, and settings never cross between them.

Opening a community lands you on its **front page**: a row of the community's tools across the top, one circle each. Pick a tool and everything of that kind in the community is listed underneath it — every project, document, calendar, queue, counter group or dashboard you have access to, wherever it lives — with the initiative it belongs to, its tags, and when it last changed. Click a name to open it, or an initiative to go there instead.

Only the tools your initiatives actually use appear, so a community that doesn't run queues never shows a Queues circle.

**Search** narrows the list by name, and the **Name**, **Initiative** and **Last updated** headers sort it — newest changes first until you say otherwise. Both reach everything of that kind in the community rather than just the rows on screen, so nothing hides on a later page. The tool you're looking at, what you searched for, and the order you put it in are all part of the address, so you can bookmark or share exactly the view you're on.

![A community's front page](../images/communities/community-front-page.png)

!!! tip "Two communities at once"
    Open Initiative in two browser tabs and you can have each tab in a different community — handy if you're juggling, say, a work team and a side project.

## Finding a community to join

Most communities are private and you get in by invitation. Some choose to list themselves publicly, and those you can find and join on your own.

Under the **add-a-community** button on the community rail, choose **Join a community**. That opens the **community directory**: a card for each listed community with its banner, icon, description, categories, how many members it has, and how many are there right now.

- **Search** by name or description.
- **Browse by category** — the shelves group communities by what they're for.
- **Join** from a community's card. There's no invite and no waiting: you're a member as soon as you click.

What you searched for and which shelf you're on are both part of the address, so a filtered view of the directory is a link you can send someone.

![The community directory](../images/communities/community-directory.png)

!!! info "Not every server has one"
    The directory is a server-wide feature that starts switched **off**. If you don't see **Join a community**, this server hasn't turned it on, and communities here are invite-only. That's the platform owner's decision — see [Configuration](../admin/configuration.md).

## Listing your community (administrators)

A community admin can put their community in the directory from **Community settings → Community**.

1. Turn on **List in the community directory**.
2. Pick at least one **category**. This is how people find you when browsing, so choose what your community is actually for.
3. **Certify** that the community holds no adult or illegal content.

![Listing a community in the community directory](../images/communities/community-listing.png)

You can unlist at any time; the community and everything in it carry on exactly as before, it simply stops appearing to strangers.

The certification is the whole of the content rule — a community that can't honestly tick it isn't listed. One other thing keeps a community out of the directory whatever you do:

- A community whose **member limit is set to one** is never listed — there would be no seat for anyone to join. (A nearly-full community is fine; it's the limit itself that has to leave room.)

!!! tip "Give arrivals somewhere to land"
    A listed community whose initiatives are all invite-only leaves newcomers looking at an empty page — they've joined the community but can't see any of its work yet. Initiative will tell you when that's the case and point you at the fix: mark one initiative **open** so people can join it themselves, or **auto-join** so they simply arrive in it. See [How people join an initiative](initiatives.md#how-people-join-an-initiative).

## Inviting people (administrators)

Community administrators bring new people in with **invite links**.

1. Go to **Community settings → Users**.
2. Create an **invite link**.
3. Optionally set limits:
    - **Max uses** — how many people may join with this one link.
    - **Expires in (days)** — when the link stops working.
4. **Copy the link** and share it however you like (email, chat, etc.).

Anyone who opens the link can join the community after signing in or creating an account.

![Managing members and invites in Community settings](../images/communities/community-users.png)

## Member roles

Inside a community there are two roles:

| Role | What they can do |
|---|---|
| **Member** | Take part in the initiatives and projects they're added to. |
| **Admin** | Everything a member can do, **plus** manage the community: members, invites, initiatives, settings, and more. A community admin can see and manage everything in their community. |

Administrators can promote a member to admin, or step a member back down, from **Community settings → Users**.

!!! note "Community admin is not the same as the app's owner"
    Being an admin of *your* community gives you full control of that community — but not of the whole server or other people's communities. Server-wide roles are a separate thing, covered in [Platform roles](../admin/platform-roles.md).

## Community settings (administrators)

Open **Community settings** from the sidebar (or the community rail). You'll find tabs for:

- **Community** — the name, description, and icon. (Icons should be a square image, up to 512&nbsp;KB.)
- **Users** — members, their roles, and invite links.
- **Initiatives** — create and manage the community's initiatives.
- **AI** — optional AI settings for the community (see [AI features](../account/ai-features.md)).
- **Trash** — recently deleted items, which you can restore.
- **Danger zone** — sensitive actions, including deleting the community.

### Trash and retention

When something is deleted, it isn't gone immediately — it goes to the community's **Trash**, where an admin can restore it. You can set how long items stay before they're cleared for good (a number of **days**, or **never auto-purge** to keep them indefinitely). This is your safety net for accidental deletions.

### The danger zone

The **Danger zone** holds actions that are hard or impossible to undo — most importantly, **deleting the community**. Deleting a community permanently removes *everything* in it: initiatives, projects, tasks, documents, and members. To prevent accidents, you'll be asked to confirm carefully (including re-entering details). Only do this if you're certain.

??? techspec "For the technically minded — what community deletion does"
    Deleting a community removes its isolated database area and the database roles tied to it, and cleans up the shared records that connect people to it (memberships, invites, single-sign-on mappings, access grants). It's thorough and final. If you only want to step back from a community without destroying it, **leave** it instead (from the community rail) — that just removes *you*.

## Leaving a community

Don't want to be in a community anymore? On the **community rail**, open the community's menu and choose **Leave community**. This removes you only — the community and everyone else carry on. If you're the *last administrator*, you'll need to promote someone else to admin first, so the community isn't left without anyone in charge.

## Related

- [Initiatives](initiatives.md) — organizing work inside a community.
- [Sharing & access](../sharing/index.md) — who can see what.
- [Security & privacy](../security/index.md) — how communities stay separate.
