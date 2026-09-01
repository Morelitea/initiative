---
icon: lucide/at-sign
---

# Mentions, links & badges

Work refers to other work. A document explains a project, a comment asks about a task, a plan points at the queue it feeds. Initiative gives you three ways to write those references down, and the difference between them is how much they keep up.

| You type | You get | Keeps up? |
|---|---|---|
| `@` | A person, notified | — |
| `#` | A link to a thing, by name | Follows renames |
| `[[ ]]` | A link to another document | Follows renames |
| `/` → a badge | A chip showing what that thing is *doing* | Yes, on its own |

## Mentioning a person

Type `@` and a few letters of someone's name, anywhere you can write a comment. Pick them from the list and they'll get a notification — it's the right way to say "take a look at this."

You'll only be offered people who are in the same initiative, because a mention that reaches someone who can't open the page isn't much use to either of you.

Names match loosely, so a spelling you're not sure of still finds the person.

## Linking to a thing

Type `#` and Initiative offers everything in the initiative — projects, tasks, documents, queues, counters, calendar events and dashboards. Pick one and its name lands in your text as a link.

If you already know what kind of thing you're after, say so and the list narrows:

- `#task:` — tasks only
- `#queue:` — queues only
- `#counter-group:`, `#calendar:`, `#dashboard:`, `#document:`, `#project:` — likewise

You don't have to. `#` on its own searches the lot, and typing the kind is just a shortcut when a name is common.

Mentioning a task also notifies the people it's assigned to.

!!! tip "Links survive renames"
    A `#` link points at the thing, not at its name, so renaming a task doesn't break the sentence that mentions it.

## Linking between documents

Inside a document, `[[` opens a list of the other documents in the initiative. Pick one to link it.

If nothing matches what you've typed, you'll be offered the chance to **create** a document by that name and link it in one step — handy when you're writing and realise a page ought to exist.

Every document shows its **backlinks** — the other documents that point at it — so you can see what refers to a page without keeping track yourself.

## Badges: a chip that keeps itself current

A link tells you something exists. A **badge** tells you what it's doing right now.

In a text document, type `/` and pick a badge:

| Badge | Shows |
|---|---|
| Task status | The column the task sits in, in that project's colour |
| Task assignee | Who's holding it |
| Task due date | When it's due — in red once that's passed, unless the work is finished |
| Task priority | How urgent it was marked |
| Counter value | The current number, against its target where it has one |
| Event date | When it happens, dimmed once it has |

Choose which thing the badge is about, and the chip appears in your sentence:

> Ship the release — **In progress** · **12 Sep**

Move that task to Done and the chip turns green — in this document and every other one that mentions it, without anyone editing a word. Click a badge to open what it's about.

Badges are for text documents. A whiteboard and a spreadsheet hold shapes and cells rather than sentences, so there's nowhere for a chip to sit.

!!! note "What other people see"
    A badge shows what *you* can see. If a document mentions a task in a project that hasn't been shared with you, the chip shows the name it had when it was written and nothing about its state.

## Where each one works

- `@` mentions work in **comments**, which every tool has, and in text documents.
- `#` links work in comments and in text documents.
- `[[ ]]` links and badges are for **text documents**.

## Related

- [Documents](documents.md)
- [Search & shortcuts](search-and-shortcuts.md)
- [Notifications](notifications.md)
