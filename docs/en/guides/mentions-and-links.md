---
icon: lucide/at-sign
---

# Mentions & links

Work refers to other work. A document explains a project. A comment asks about a task. A plan points at the rota that feeds it.

Three characters cover all of it:

| You type | You get |
|---|---|
| `@` | A person, and they get told |
| `#` | A link to anything that already exists |
| `[[ ]]` | A link to a tool — and it'll create one that doesn't exist yet |

All three work in every **comment**, on every tool, and inside any **text document**.

## `@` — mentioning a person

Type `@` and a few letters of somebody's name, pick them from the list, and they get a notification. It's the right way to say "can you look at this."

You're only offered people who are in the same initiative, because a mention that reaches somebody who can't open the page helps precisely nobody.

Names match loosely, so a spelling you're not confident about will still find the right person.

## `#` — linking to a thing

Type `#` and Initiative offers you everything in the initiative: projects, tasks, documents, queues, counters, calendar events, dashboards. Pick one and its name drops into your text as a link.

Already know what kind of thing you want? Say so and the list narrows: `#task:`, `#queue:`, `#counter-group:`, `#calendar:`, `#dashboard:`, `#document:`, `#project:`.

You never *have* to. `#` on its own searches everything — the prefixes are just a shortcut for when a name is common.

Mentioning a task also notifies whoever it's assigned to.

The list reaches the work in **this initiative** — the document's own, if you're writing in one — so a community absolutely full of matching tasks can still come back with nothing. When that happens the picker says so, and explains that the initiative is the limit, rather than leaving you staring at an empty box wondering what you typed wrong.

!!! tip "Links survive renames"
    A `#` link points at the *thing*, not at its name. Rename a task and the sentence mentioning it quietly updates itself.

## `[[ ]]` — linking, or conjuring

`[[` offers the **tools** in this initiative — projects, documents, queues, counter groups, calendars, dashboards.

The difference from `#` is what happens when nothing matches: `[[ ]]` offers to **make** the thing you just named, right there, without you leaving the sentence you were in the middle of.

That's why it reaches tools and `#` reaches everything. A tool needs only a name and the initiative you're already standing in. A task needs a project, and an event needs a calendar and a time — you can't summon those out of a half-written sentence, so reach them with `#`.

A tool your initiative has switched off isn't offered, and can't be created this way either.

Every document also shows its **backlinks** — the other documents pointing at it — so you can see what refers to a page without keeping a list yourself. A `#` link counts, not just a `[[ ]]` one.

## Names look after themselves

A reference points at the thing, not at its name. Rename a task and every sentence mentioning it says the new name — in every document and every comment, with nobody editing anything.

If what you pointed at gets deleted, or was never shared with you in the first place, the reference keeps the words it was written with, greyed out and no longer a link. It never claims something you can't see doesn't exist, and it never leaves a hole in the middle of a sentence.

!!! note "Exports show the words"
    A PDF or Word file can't keep itself current, so an export shows the name a thing had when the reference was written.

!!! note "`#` and `@` aren't allowed in names"
    Both already mean something when you're writing, so a name or title can't contain either. Initiative tells you rather than quietly creating a reference nobody can follow.

## Going further than a link

Inside a text document, a **smart chip** shows what a thing is currently *doing*, not just what it's called. See [Documents](documents.md#smart-chips).

## Related

- [Documents](documents.md) — including smart chips.
- [Search & shortcuts](search-and-shortcuts.md)
- [Notifications](notifications.md)
