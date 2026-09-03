---
icon: lucide/share-2
---

# Sharing projects & documents

The final, most precise layer: who can reach a **specific** project or document. It works identically for both, so learn it once.

## The three levels

| Level | Can do |
|---|---|
| **Viewer** | Open and read it. |
| **Editor** | Read **and** change it. |
| **Owner** | Everything an editor can, **plus** manage who else has access. |

Pick the lowest level that lets someone do their job. Most people only need Viewer or Editor.

## Who you can share with

- **A person** — a specific member of the initiative.
- **A role** — *everyone* holding that [initiative role](initiative-roles.md), in one go. Share with "Cast" and every cast member gets access, including people you add to that role later.

Sharing with a **role** is the tidy choice when a whole group should have the same access. Set it once instead of adding people one at a time.

![Choosing who can access a project](../images/sharing/access-settings.png)

## Open, or restricted

- **All initiative members** — everyone in the initiative can reach it. Good for things the whole team should see.
- **Restricted** — only the people and roles you name. Good for anything sensitive.

Start restricted when you're unsure. Widening later is easy.

## Changing access

Open the **Access** tab in a project's or document's settings any time to add people, change a level, or remove access. Changes apply immediately.

Every settings tab has its own address, so you can send someone a link straight to a tool's sharing options rather than describing where to click.

You can also **edit access on several items at once**: from a list view, select multiple documents, projects, queues, counters or calendar events and update them in one step. Handy when a new teammate joins a batch of work, or when someone leaves.

No need to click each card, either. Click the first, hold ++shift++ and click the last, and everything between comes with it. Shift-clicking away from a card you just unticked clears that run the same way. (++shift+enter++ or ++shift+space++ does it from the keyboard.)

## Three things to remember

- **Initiative membership comes first.** You can only share with someone already in the initiative. If they're not, [add them there](../guides/initiatives.md#adding-members) first.
- **Managers see everything.** A member with the [Manager role](initiative-roles.md#the-built-in-manager-role) opens the item regardless of these settings. Intended — but worth remembering for genuinely private material.
- **Community admins see everything in their community.** Also by design, so somebody can always administer the group.

??? techspec "For the technically minded — how item sharing is stored and checked"
    Per-item sharing is recorded as grants naming a project or document, a person *or* a role, and a level (view / edit / own). On every request the database evaluates whether the current user satisfies the grant — directly, through a role they hold, through the initiative's Manager role, or as a community admin — before any data comes back. Because that check lives in the database alongside the community and initiative boundaries, the link to a project is never the thing that grants access to it. See [How your data is kept separate](../security/how-your-data-is-kept-separate.md).

## Related

- [Initiative roles](initiative-roles.md) — sharing with whole roles at once.
- [Sharing & access overview](index.md) — how this fits with the other layers.
