---
icon: lucide/at-sign
---

# Mentions & links

Work refers to other work. A document explains a project, a comment asks about a task, a plan points at the queue it feeds. Three characters cover all of it:

| You type | You get |
|---|---|
| `@` | A person, notified |
| `#` | A link to anything that exists |
| `[[ ]]` | A link to a tool — and it'll make one that doesn't exist yet |

All three work in every **comment**, on every tool, and inside a **text document**.

## `@` — mentioning a person

Type `@` and a few letters of someone's name, pick them from the list, and they get a notification. It's the right way to say "take a look at this."

You're only offered people in the same initiative, because a mention that reaches someone who can't open the page helps nobody. Names match loosely, so a spelling you're unsure of still finds them.

## `#` — linking to a thing

Type `#` and Initiative offers everything in the initiative: projects, tasks, documents, queues, counters, calendar events, dashboards. Pick one and its name lands in your text as a link.

Know what kind of thing you're after? Say so and the list narrows: `#task:`, `#queue:`, `#counter-group:`, `#calendar:`, `#dashboard:`, `#document:`, `#project:`. You never have to — `#` alone searches the lot — it's just a shortcut when a name is common.

Mentioning a task also notifies whoever it's assigned to.

The list reaches the work in **this initiative** — the document's own, if you're writing in one — so a community full of matching tasks can still come back with nothing. When that happens the picker says so, and says the initiative is the limit, rather than leaving you staring at an empty box.

!!! tip "Links survive renames"
    A `#` link points at the thing, not its name, so renaming a task doesn't break the sentence mentioning it.

## `[[ ]]` — linking, or making

`[[` offers the **tools** in this initiative — projects, documents, queues, counter groups, calendars, dashboards.

The difference from `#` is what happens when nothing matches: `[[ ]]` offers to **make** the thing you named, right there in the sentence you were writing. That's why it reaches tools and `#` reaches everything — a tool needs only a name and the initiative you're already in, while a task needs a project and an event needs a calendar and a time. Those can't be conjured out of a name, so reach them with `#`.

A tool your initiative has switched off isn't offered, and can't be created this way either.

Every document shows its **backlinks** — the other documents pointing at it — so you can see what refers to a page without keeping track. A `#` link counts, not just a `[[ ]]` one.

## Names look after themselves

A reference points at the thing, not its name. Rename a task and every sentence mentioning it says the new name — in every document and every comment, with nobody editing anything.

If what you pointed at is deleted, or was never shared with you, the reference keeps the words it was written with, greyed out and no longer a link. It never claims something you can't see doesn't exist, and it never leaves a hole in a sentence.

!!! note "Exports show the words"
    A PDF or Word file can't keep itself current, so an export shows the name a thing had when the reference was written.

!!! note "`#` and `@` aren't allowed in names"
    Both already mean something when you're writing, so a name or title can't contain either. Initiative says so rather than quietly making a reference nobody can follow.

## Going further than a link

Inside a text document, a **smart chip** shows what a thing is currently *doing*, not just what it's called. See [Documents](documents.md#smart-chips).

## Related

- [Documents](documents.md) — including smart chips.
- [Search & shortcuts](search-and-shortcuts.md)
- [Notifications](notifications.md)
