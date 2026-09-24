---
icon: lucide/at-sign
---

# Mentions & links

Work refers to other work. A document explains a project. A comment asks about a task. A plan points at the rota that feeds it.

Three characters handle all of that:

| You type | You get |
|---|---|
| `@` | A person, and they get told |
| `#` | A link to anything that already exists |
| `[[ ]]` | A link to a tool — and it'll create one that doesn't exist yet |

All three work in every **comment**, on every tool, in a task's **description**, and inside any **text document**.

## `@` — mentioning a person

Type `@` and a few letters of somebody's name, pick them from the list, and they get a notification. It's the right way to say "can you look at this."

You're only offered people who are in the same initiative, because a mention that summons somebody to a page they can't open helps precisely nobody and mildly annoys everybody.

Names match loosely, so a spelling you're not confident about will still find the right person.

In a task's description, a person hears about it once — when their name goes in. Rewording the sentence around them later doesn't ping them again, which they will appreciate more than they'll ever say.

## `#` — linking to a thing

Type `#` and Initiative offers you everything in the initiative: projects, tasks, documents, queues, counters, calendar events, dashboards, posts. Pick one and its name drops into your text as a link.

Already know what kind of thing you want? Say so and the list narrows: `#task:`, `#queue:`, `#counter-group:`, `#calendar:`, `#dashboard:`, `#document:`, `#project:`, `#post:`.

You never *have* to. `#` on its own searches the lot — the prefixes are just a shortcut for when half the community has named something "Planning".

Mentioning a task also notifies whoever it's assigned to.

The list reaches the work in **this initiative** — the document's own, if you're writing in one — so a community absolutely stuffed with matching tasks can still come back with nothing.

When that happens the picker says so, and explains that the initiative is the limit, rather than leaving you staring at an empty box slowly retyping the same word.

!!! tip "Links survive renames"
    A `#` link points at the *thing*, not at its name. Rename a task and the sentence mentioning it quietly updates itself.

## `[[ ]]` — linking, or conjuring

`[[` offers the **tools** in this initiative — projects, documents, queues, counter groups, calendars, dashboards, posts.

The difference from `#` is what happens when nothing matches. `[[ ]]` offers to **make** the thing you just named, on the spot, without you abandoning the sentence you were halfway through.

That's why it reaches tools and `#` reaches everything. A tool needs only a name and the initiative you're already standing in. A task needs a project, and an event needs a calendar and a time — you can't summon those out of a half-written sentence, so reach them with `#`.

A tool your initiative has switched off isn't offered, and can't be created this way either.

Every document also shows its **backlinks** — the other documents pointing at it — so you can see what refers to a page without keeping a list yourself. A `#` link counts, not just a `[[ ]]` one.

## Names look after themselves

A reference points at the thing, not at its name. Rename a task and every sentence mentioning it says the new name — in every document and every comment, with nobody editing anything.

If what you pointed at gets deleted, or was never shared with you in the first place, the reference keeps the words it was written with — greyed out, no longer a link.

It never claims something you can't see doesn't exist, and it never leaves a hole in the middle of a sentence for you to puzzle over.

!!! note "Exports show the words"
    A PDF or Word file can't keep itself current, so an export shows the name a thing had when the reference was written.

!!! note "`#` and `@` aren't allowed in names"
    Both already mean something when you're writing, so a name or title can't contain either. Initiative tells you rather than quietly creating a reference nobody can follow.

## Going further than a link

Inside a text document, a **smart chip** shows what a thing is currently *doing*, not just what it's called — a task's column, an event's date, a counter against its target, a project as **1 / 3** of its tasks done. See [Documents](documents.md#smart-chips).

The same readings show up on anything you've linked, so a relation is never just a name.

## Relations

A `#` link says *that* two things are connected. A **relation** says *how*.

Every task, document and project has a panel for them. Add one and you get a
sentence with both names in it:

> **This task** *is blocked by* **Order the marquee**

Find the thing first. The wording is a dropdown in the middle, and you can
change it after — so you never have to know the vocabulary before you start
typing.

If the thing isn't in the app yet — a PDF, a photo of the whiteboard — upload
it right there instead. Choose a file, or drag one onto the panel, and it
becomes a document in the same initiative, already linked. You need to be
allowed to make documents in that initiative to see the option.

| Heading | What it means |
|---|---|
| **Attached** | The documents and files this runs on |
| **Blocked by** | What has to happen first |
| **Blocking** | What's waiting on this |
| **Part of** | The bigger thing this belongs to |
| **Made up of** | The pieces it's built from |
| **See also** | Related. No stronger claim than that |
| **Mentioned in** | Everything pointing here |

**Mentioned in** writes itself — it's the backlinks from `#` and `[[ ]]` above.
Edit the words and it follows.

### "Blocked by" earns its keep

A task waiting on something says so on the board and in the list, and the count
only counts the things that haven't finished. Mark the blocker done and the
mark goes away on its own. Nobody has to remember to tidy up.

What counts as finished depends on what it is:

| | Stops blocking when |
|---|---|
| A task | It reaches a **Done** column |
| A project | Every task in it is done — an empty one hasn't finished anything yet, so it still counts |
| An event | It's been and gone — a repeating one never counts, having no last time |
| A counter | It reaches its target |

Archived tasks sit it out, so shelving something doesn't keep a project open
forever.

Anything else — a document, a gallery, a wiki page — still shows up as a link,
and still sits there under **Blocked by** if that's what you said. It just
isn't counted, because nothing about a document says when it's done.

!!! tip "The panel remembers how you like it"
    Tiles, a list, a carousel, or a graph of everything within a hop or two.
    Pick one and that page keeps it.

## Related

- [Documents](documents.md) — including smart chips.
- [Search & shortcuts](search-and-shortcuts.md)
- [Notifications](notifications.md)
