---
icon: lucide/folders
---

# Working with initiatives

An **initiative** is a folder for a big effort inside your community. It gathers the projects, documents, and tools for that effort, and it's where you decide *who's involved*. This guide covers creating initiatives, adding people, and setting up roles.

New to the idea? See [How Initiative is organized](../concepts/index.md) first.

## Creating an initiative

1. In the sidebar, find **Initiatives** and choose **Add initiative** (or **New initiative**).
2. Give it a **name** — usually the effort it represents ("Spring Play," "2026 Budget," "Onboarding").
3. Pick a **color**. This color appears alongside the initiative's projects, so groups are easy to tell apart at a glance.
4. Optionally add a **description** (you can use simple Markdown formatting).
5. Create it.

Your new initiative appears in the sidebar. Click to expand it and you'll see its projects and documents.

![Creating an initiative](../images/initiatives/create-initiative.png)

!!! info "The Default Initiative"
    Every community starts with a **Default Initiative** so there's always somewhere to begin. You can rename it and use it like any other — but it can't be deleted, so your community is never left without a home for new work.

## The initiative dashboard

Clicking an initiative's **title** in the sidebar opens its **dashboard** — an overview of that effort: how its projects are progressing, upcoming tasks, and recent activity. It's a quick way to see how the whole initiative is doing.

## Adding members

An initiative's **contents** are visible only to its **members**. To bring people in by hand:

1. Open the initiative and go to its **settings → Members**.
2. **Add** people from your community.
3. Give each person a **role** (see below).

An invite-only initiative isn't just closed to people who aren't in it — it isn't there for them at all. No "no entry" sign, no name in a list: nothing. This is how an initiative keeps sensitive work private to the people involved, even from other members of the same community.

An initiative that invites the community in (below) is listed by name, description, and size so people can find it — but that's all a non-member sees. Its projects, documents, and everything else stay out of reach until they actually join.

## How people join an initiative

Being added by hand isn't the only way in. Each initiative decides for itself how people from the community may join it, under **settings → Details → Joining**:

| Setting | What it means |
|---|---|
| **Invite only** | Nobody joins on their own. A manager adds them. This is the default, and what every initiative made before this feature still uses. |
| **By request** | Listed for the community to see. Someone asks to join, and a manager approves or declines. |
| **Anyone can join** | Listed for the community to see, and any member joins in one click. |

![Choosing how people join an initiative](../images/initiatives/join-policy.png)

Anything that isn't invite-only appears in the **Initiatives** section of the community's front page — its name, colour, description, and how many people are in it — split into the ones you're already in and the ones you could join.

![The initiative list on a community's front page](../images/initiatives/community-home-initiatives.png)

Whichever way someone arrives, they get the built-in **member** role — view-only on the always-on tools — and sharing still decides each project and document inside. Opening an initiative up doesn't expose anything that was private to it; it only changes who may walk in.

### Asking to join

On a **by request** initiative, the card offers **Request to join**, and the person can add a short note saying who they are or why they're asking.

The initiative's managers are notified — in the app, and by push or email if they've got those turned on — and the request waits in **settings → Members**, above the roster. Each one shows who asked, what they wrote, when, and whether that person has been declined here before. **Approve** adds them as a member; **Decline** doesn't.

Being declined isn't a ban. The person can ask again, and only one request of theirs can be open at a time.

![The join-request queue](../images/initiatives/join-request-queue.png)

### Adding everyone automatically

A community admin can go one step further and mark an **anyone can join** initiative as **auto-join**. From then on, everyone who arrives in the community — by invite, from the [community directory](communities.md#finding-a-community-to-join), or through single sign-on — lands in it already a member, with nothing to click.

This is how you stop a newcomer meeting an empty community. It's worth having at least one for any community that lists itself publicly.

Two things to know:

- It applies to people arriving **from now on**. It doesn't reach back and add everyone already in the community.
- Only an **anyone can join** initiative can carry it, so auto-join never hands out access that the person couldn't have given themselves from the list a moment later.

!!! tip "Community admins are already everywhere"
    A community admin reaches every initiative in their community by virtue of being an admin, so they're not enrolled as ordinary members and don't appear in these lists as needing to join.

## Roles and what they unlock

Within an initiative, each member has a **role**. A role decides which *kinds of tools* that person can use here — for example, whether they can create projects, or only view them.

Initiative comes with a **Manager** role (think project lead) whose permissions are fixed, and you can create your own roles on top — like "Coordinator," "Volunteer," "Client," or "Guest" — each with its own mix of permissions. Name them after how your group actually talks about itself, not after anything Initiative expects.

Permissions are grouped by tool:

| Tool | Typical permissions |
|---|---|
| **Projects** | View, Create |
| **Documents** | View, Create |
| **Queues** | View, Create |
| **Counters** | View, Create |
| **Events** (calendar) | View, Create |
| **Dashboards** | View, Create |

So you might give "Volunteer" members permission to *view* projects and documents but not create them, while "Coordinator" can create everything.

There's a full walkthrough of roles and how they combine with sharing in [Initiative roles](../sharing/initiative-roles.md).

![Setting permissions for an initiative role](../images/initiatives/roles.png)

!!! tip "Managers can see everything"
    The built-in **Manager** role has full access to the whole initiative — its members reach every project and document without each being shared with them. This is unique to Manager; custom roles don't get it. Give the Manager role only to people who genuinely need the whole picture.

## Initiative settings

Open an initiative's **settings** to find:

- **Details** — name, color, description, and **Joining** (how people may join; see [How people join an initiative](#how-people-join-an-initiative)).
- **Members** — who's in, and their roles.
- **Roles** — create roles and set their permissions.
- **Danger zone** — archive, unarchive, or delete the initiative.

### Archiving vs. deleting

- **Archive** tucks an initiative away when an effort is finished, without losing anything. Archived initiatives are hidden from the main view but can be brought back at any time. Good for "the spring play is over, but keep the records."
- **Delete** sends the initiative — and everything in it — to the community's **Trash**, where an admin can still restore the whole thing until the retention period ends. After that, it's gone for good.

## Related

- [Projects & tasks](projects-and-tasks.md) — the work inside an initiative.
- [Documents](documents.md) — shared knowledge inside an initiative.
- [Initiative roles](../sharing/initiative-roles.md) — roles and sharing, in depth.
