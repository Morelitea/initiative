---
icon: lucide/folders
---

# Working with initiatives

An **initiative** is a folder for one big effort inside your community. It holds that effort's projects, documents and tools, and it's where you decide who's actually involved in it.

New to the idea? [How Initiative is organized](../concepts/index.md) explains the shape first.

## Making one

1. In the sidebar, find **Initiatives** and choose **Add initiative**.
2. **Name** it after the effort: "Spring Play", "2026 Budget", "Onboarding".
3. Pick a **colour**. It follows the initiative's projects around, so you can tell at a glance what belongs to what without reading a single word.
4. Add a **description** if you like.
5. Create it.

It shows up in the sidebar. Expand it to see its projects and documents.

![Creating an initiative](../images/initiatives/create-initiative.png)

!!! info "The Default Initiative"
    Every community starts with one, so there's always somewhere to put things. Rename it, use it like any other.

    It just can't be deleted — which means you can never quite manage to leave yourself with nowhere to put a project, however determined you are.

## The initiative dashboard

Clicking an initiative's **title** opens its dashboard: how the projects are getting on, what's coming up, what's changed lately.

It's the quick answer to "how's this going?" — the question you'd otherwise answer by opening five things and doing arithmetic in your head.

## Adding members

An initiative's contents are visible **only to its members**. To add somebody by hand:

1. Open the initiative → **settings → Members**.
2. **Add** people from your community.
3. Give each one a **role** (see below).

Here's the important bit: an invite-only initiative isn't merely closed to people who aren't in it. It isn't *there* for them at all. No name in a list. No locked door to rattle. No "you do not have permission" message to feel odd about.

That's how an initiative keeps sensitive work with the people involved — even from other members of the same community — without anybody ever having to be told they're on the outside of something.

An initiative that opens itself up (below) shows its name, description and size so people can find it. That's all a non-member gets. The projects and documents stay out of reach until they actually join.

## How people join an initiative

Each initiative sets its own front door, under **settings → Details → Joining**:

| Setting | What it means |
|---|---|
| **Invite only** | Nobody joins on their own. A manager adds them. This is the default. |
| **By request** | Listed for the community. Somebody asks, a manager says yes or no. |
| **Anyone can join** | Listed for the community, and any member joins in one click. |

![Choosing how people join an initiative](../images/initiatives/join-policy.png)

Anything that isn't invite-only appears in the **Initiatives** section of the community front page — name, colour, description, member count — split into the ones you're already in and the ones you could join.

![The initiative list on a community's front page](../images/initiatives/community-home-initiatives.png)

However somebody arrives, they land on the built-in **member** role, which is view-only on the always-on tools, and sharing still decides each individual project and document inside.

So opening an initiative up doesn't suddenly expose anything that was private within it. It only changes who's allowed to walk in.

### Asking to join

On a **by request** initiative, the card offers **Request to join**, with room for a short note explaining who they are or why they're asking.

Managers get notified — in the app, plus push or email if they've got those on — and the request waits in **settings → Members**, above the roster, showing who asked, what they wrote, when, and whether they've been turned down here before. **Approve** adds them. **Decline** doesn't.

Being declined isn't a ban and it isn't permanent. They can ask again later.

They can also only have one request open at a time, so nobody can express their enthusiasm by sending you fifteen.

![The join-request queue](../images/initiatives/join-request-queue.png)

### Adding everyone automatically

A community admin can mark an **anyone can join** initiative as **auto-join**. From then on, everybody arriving in the community — by invite, from the [directory](communities.md#finding-a-community-to-join), or through a work login — lands in it already a member, with nothing to click.

This is how you stop every new arrival meeting a completely empty community and quietly concluding they've done something wrong. Worth having at least one if your community is publicly listed.

Two things to know:

- It applies **from now on**. It doesn't sweep in everybody who's already there.
- Only an **anyone can join** initiative can carry it — so auto-join never hands out access that somebody couldn't have taken for themselves a moment later anyway.

### Community admins join like everybody else

A community admin has authority over every initiative in their community. But authority isn't navigation.

Their sidebar and front page show **the initiatives they're actually in**, then the ones on offer, exactly like everybody else's.

An admin buried under a hundred initiatives they have never once opened cannot find the three they actually work in. That helps nobody, least of all the admin.

To put one in front of themselves, an admin joins it from the front page. They walk straight in whatever the joining setting says — no request, no waiting — and arrive on the **project manager** role their standing already implies. **Community settings → Initiatives** still lists every initiative in the community.

None of this changes what an admin may *do*. Open any initiative and they see all of it.

!!! tip "Adding an admin to your initiative"
    A project manager can add a community admin like anybody else — the member picker offers them, and they arrive as project manager, which is the only role their standing allows here.

## Roles and what they unlock

Each member holds a **role**, which decides which *kinds of tools* they can use here — whether they can make projects, or only look at them.

Initiative ships a **Manager** role (think project lead) with fixed permissions, and you build your own on top: "Coordinator". "Volunteer". "Client". "Guest". "Person Who Only Needs To See The Rota".

Name them after how your group actually talks about itself, not after anything Initiative expects. Nobody has ever introduced themselves at a committee meeting as a view-only contributor.

Permissions are grouped by tool — **Projects**, **Documents**, **Queues**, **Counters**, **Events**, **Dashboards** — each offering **View** and **Create**. So "Volunteer" might view projects and documents but create nothing, while "Coordinator" creates everything.

![Setting permissions for an initiative role](../images/initiatives/roles.png)

There's a full walkthrough in [Initiative roles](../sharing/initiative-roles.md).

!!! warning "Managers see absolutely everything"
    The built-in **Manager** role reaches every project and document in the initiative, whether or not it was ever shared with them. That's unique to Manager — custom roles don't get it, and can't be given it however much you'd like them to.

    So hand it to the people who genuinely need the whole picture. Not as a thank-you for being helpful, and not because somebody's been around a long time and it felt rude not to.

## Initiative settings

- **Details** — name, colour, description, and **Joining**.
- **Members** — who's in, their roles, and any waiting requests.
- **Roles** — make roles and set what they can do.
- **Properties** — custom fields this initiative's tasks, documents and events can carry.
- **Export** — download the initiative's data (managers and above).
- **Danger zone** — archive, unarchive, delete.

### Archiving vs. deleting

- **Archive** tucks a finished effort out of sight without losing a single thing. Restorable whenever. This is the button for "the spring play is over, but I am absolutely not throwing away the records."
- **Delete** sends the initiative and everything inside it to the community **Trash**, where an admin can still restore the whole lot until the retention period runs out. After that it's genuinely gone.

When in doubt, archive. Archiving has never once ruined anybody's week.

## Related

- [Projects & tasks](projects-and-tasks.md) — the work inside an initiative.
- [Documents](documents.md) — the writing inside an initiative.
- [Initiative roles](../sharing/initiative-roles.md) — roles and sharing in depth.
