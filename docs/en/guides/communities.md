---
icon: lucide/home
---

# Working with communities

A **community** is your group's workspace. This guide covers moving between them, inviting people, and — if you run one — looking after it.

Not in one yet? Start with [Your first community](../getting-started/your-first-community.md).

## Switching between communities

The **community rail** runs down the far-left edge: one icon per community, with the highlighted one being where you are. The **Initiative logo** above them takes you to [your personal space](your-space.md).

Click any icon to switch. Everything else follows — sidebar, initiatives, projects. Each community is fully independent; work, people and settings never cross between them.

!!! tip "Two communities at once"
    Open Initiative in two browser tabs and each can sit in a different community. Handy when you're juggling a work team and a side project.

Your rail keeps up with itself, too. If an admin adds you somewhere, a group sign-in sync brings you in, or a community you're already in lists itself publicly, the rail updates where you are — no reload.

## The community front page

Opening a community drops you on its front page. Its tools run across the top as circles; pick one and you get everything of that kind that's reached **you** — shared with you directly, shared with a role you hold, or shared with everyone in an initiative you're in. Each row shows which initiative it's from, its tags, and when it last changed. Click a name to open it, or an initiative to go there instead.

Only tools your initiatives actually use show up, so a community that doesn't run queues never grows a Queues circle.

**Search** narrows by name, and the **Name**, **Initiative** and **Last updated** headers sort — newest first until you say otherwise. Both reach everything of that kind in the community, not just the rows on screen, so nothing hides on page two. The tool, the search, and the sort are all part of the address, so you can bookmark or share exactly the view you're looking at.

Community admins get the same page. Their authority is unchanged — open a single initiative and they see all of it — but the front page is a reading list, not an inventory.

![A community's front page](../images/communities/community-front-page.png)

## Finding a community to join

Most communities are private and you get in by invitation. Some list themselves, and those you can find on your own.

Hit the **add-a-community** button on the rail and choose **Join a community**. That opens the **community directory** — a card per listed community with its banner, icon, description, categories, member count, and how many are online right now.

- **Search** by name or description.
- **Browse by category**.
- **Join** from the card. No invite, no waiting — you're a member the moment you click.

What you searched and which shelf you're on are part of the address, so a filtered directory view is a link you can send someone.

![The community directory](../images/communities/community-directory.png)

The first time you join a listed community, you're asked your date of birth. Listed communities can be found by anyone signed in, so they're open to people you've never met, and you need to be **13 or older**. You're asked once, ever.

!!! info "The date isn't kept"
    We work out whether you're old enough, then discard it. Your account records that you answered, never the date, and it isn't sold or shared. Only the parts of Initiative open to people outside your own communities ask — a private community never does, and neither does an invite into one. See [Data and compliance](../security/data-and-compliance.md).

!!! info "Not every server has a directory"
    It's a server-wide feature that starts switched **off**. No **Join a community** button means this server hasn't turned it on, and everything here is invite-only. That's the platform owner's call — see [Configuration](../admin/configuration.md).

## Listing your community (admins)

From **Community settings → Community**:

1. Turn on **List in the community directory**.
2. Pick at least one **category** — this is how people find you, so choose what you're actually for.
3. **Certify** that the community holds no adult or illegal content.

![Listing a community in the community directory](../images/communities/community-listing.png)

Unlist any time; everything carries on exactly as before, it just stops appearing to strangers.

That certification is the whole content rule — a community that can't honestly tick it doesn't get listed. One other thing keeps a community out regardless: a **member limit of one**, because there'd be no seat for anyone to take. (A nearly-full community is fine; it's the limit itself that has to leave room.)

!!! tip "Give arrivals somewhere to land"
    A listed community whose initiatives are all invite-only leaves newcomers staring at an empty page. Initiative will tell you when that's the case and point at the fix: mark one initiative **open** so people can join it, or **auto-join** so they simply arrive in it. See [How people join an initiative](initiatives.md#how-people-join-an-initiative).

## Inviting people (admins)

1. **Community settings → Users**.
2. Create an **invite link**.
3. Optionally limit it:
    - **Max uses** — how many people can join on this one link.
    - **Expires in (days)** — when it stops working.
4. **Copy** and share it however you like.

Anyone who opens it joins after signing in or creating an account.

![Managing members and invites in Community settings](../images/communities/community-users.png)

## Member roles

| Role | What they can do |
|---|---|
| **Member** | Take part in the initiatives and projects they're added to. |
| **Admin** | Everything a member can, **plus** run the community: members, invites, initiatives, settings. An admin can see and manage everything in their community. |

Promote and demote from **Community settings → Users**.

Promoting someone also lifts the **initiative roles they already hold** — every initiative they're in moves them to project manager, so the app treats them as the authority they now are. They get told when somebody asks to join, and waiting requests appear on the front page. A membership left behind by an older promotion can be fixed from that initiative's **Members** tab.

### What the member list shows

What a community actually manages: **handle**, **name** (in communities that show real names), **community role**, whether the membership came from a group sign-in sync, the member's standing, and when they joined. **Export all as CSV** writes the same columns.

A member's platform role and whether they've confirmed their email aren't a community's business, so they're in neither the list nor the CSV. Platform-wide user management lives in the [admin dashboard](../admin/platform-roles.md#managing-platform-users).

!!! note "Community admin ≠ the app's owner"
    Running *your* community gives you full control of it — not of the server or anyone else's community. Server-wide roles are separate: see [Platform roles](../admin/platform-roles.md).

## Community settings (admins)

Open **Community settings** from the sidebar or the rail:

| Tab | What's in it |
|---|---|
| **Community** | Name, description, icon and banner (square, up to 512 KB), and directory listing. |
| **AI** | Optional AI settings — see [AI features](../account/ai-features.md). |
| **Users** | Members, roles, invite links. |
| **Authentication** | Single sign-on for this community, where your server offers it. |
| **Initiatives** | Create and manage the community's initiatives. |
| **Apps** | Installed apps — see [Apps & the marketplace](apps-and-marketplace.md#adding-an-app). |
| **Trash** | Recently deleted items, restorable. |
| **Data** | Export the whole community, and re-download a finished export. |
| **Danger zone** | The things you can't undo. |

### Trash and retention

Deleted things go to the community **Trash** first, where an admin can restore them. Set how long they linger — a number of **days**, or **never auto-purge** to keep them indefinitely. This is your safety net, so give it a bit of room.

### The danger zone

Holds the hard-to-undo, chiefly **deleting the community**. That permanently removes *everything* — initiatives, projects, tasks, documents, members — and you'll be asked to confirm properly, including re-entering details. Only go here if you're certain.

??? techspec "For the technically minded — what community deletion does"
    It removes the community's isolated database area and the database roles tied to it, then cleans up the shared records connecting people to it: memberships, invites, single-sign-on mappings, access grants. Thorough and final. If you only want out of a community, **leave** it from the rail instead — that removes just you.

## Leaving a community

On the **community rail**, open the community's menu and choose **Leave community**. That removes you and nobody else. If you're the *last administrator*, promote someone first — a community shouldn't be left with nobody in charge.

## Related

- [Initiatives](initiatives.md) — organizing work inside a community.
- [Sharing & access](../sharing/index.md) — who can see what.
- [Security & privacy](../security/index.md) — how communities stay separate.
