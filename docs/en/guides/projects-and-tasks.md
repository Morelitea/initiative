---
icon: lucide/clipboard-check
---

# Projects & tasks

A **project** is a board for tracking work; **tasks** are the to-dos on it. This is where most of the day-to-day happens.

## Creating a project

1. Open the initiative it belongs in, and choose **Create Project**.
2. Fill in:
    - **Project name** (required).
    - **Icon** — an optional emoji, so it's easy to spot.
    - **Description** — optional, Markdown supported.
    - **Initiative** — which one it lives in.
    - **Template** — optionally start from one (see [Templates](#templates)).
3. Create it. The board opens, ready for tasks.

![Creating a project](../images/projects/create-project.png)

### Favorites and pinning

- **Add to favorites** (the star) puts it in your **Favorites** list in the sidebar.
- **Pin project** keeps it near the top of its initiative.

Both are personal — they change nothing for anyone else.

## Adding tasks

**Create task** on a board. The quick form wants a **title** and a description, and that's enough to get moving. Need more right away? Expand **Advanced details** for the rest, grouped into **Tracking**, **Schedule**, **People & labels**, and any custom **Properties** your initiative has set up.

Editing a task later shows the same sections in the same order, so there's one shape to learn rather than two. Above them sit the two actions you reach for most; everything else is behind a **…** menu.

A task can hold:

| Field | What it's for |
|---|---|
| **Title** | A short name (required). |
| **Description** | The details. Markdown, with a **Preview** mode. |
| **Status** | Where it is in your workflow. |
| **Priority** | Low, Medium, High, or Urgent. |
| **Start date** | When work should begin. |
| **Due date** | When it's due. |
| **Assignees** | One or more people. |
| **Subtasks** | A checklist of smaller steps, with progress. |
| **Tags** | Labels for grouping and filtering — see [Tags](tags.md). |
| **Recurring** | Make it repeat on a schedule. |

![Editing a task's details](../images/projects/task-details.png)

### Statuses

Every project starts with four, in four stages:

**Backlog → To Do → In Progress → Done**

Fully customizable per project from **Project settings → Task statuses** — rename them, add your own, give each an icon and color. Each one still belongs to one of the four stages, which is how "archive done tasks" knows what "done" means.

### Subtasks

Break a big task into a checklist. As you tick them off, the task shows its progress ("3/5 subtasks"). Perfect for "before this is truly finished I need to do A, B and C."

### Recurring tasks

For things that keep coming back — a weekly report, a monthly review. Pick the rhythm: daily, every weekday, weekly on a chosen day, monthly on a date, annually, or a **custom** pattern.

You also choose *when* the next one shows up: on a fixed **schedule**, or only **after you complete** the current one. That second option is the one you want for chores that shouldn't pile up while you're on holiday.

### A little celebration

Finish a task assigned to you and Initiative can mark the moment — confetti, a "+1 Heart", a "Natural 20", or gold coins. Pick your flavor (or turn it off) in **User settings → Interface**. Optional sound and vibration too.

## Keeping a busy board manageable

- **Filter** by status, priority, assignee, due date, and more.
- **Sort** by any column. In Table view, hold ++shift++ and click more columns to sort by several.
- **Group** by status, priority, or assignee.
- **Select several tasks** to act on them together — status, dates, assignees, priority, tags, or archive, all in one go.

!!! tip "Archive, don't delete"
    Finished tasks don't need deleting. **Archive** clears the board while keeping the record — there's a one-click **Archive done tasks** — and you can filter archived tasks back into view whenever you want.

## Project settings

- **Details** — icon, name, description, tags.
- **Access** — who can view or edit this project. See [Sharing](../sharing/sharing-projects-and-documents.md).
- **Task statuses** — customize the workflow.
- **Advanced** — save as a template, duplicate, archive/unarchive, delete.

### Moving a task to another project

You can move a task from its menu. One quirk worth knowing: because each project can have its own statuses, a moved task restarts at **Backlog** in its new home. Set the new status and carry on.

## Templates

Set a project up the way you like it, then save it as a **template** — from **Project settings → Advanced**, or by ticking **Save as template** when you create one. Next time, start *from* it and skip the setup. Ideal for anything repeatable: every new client, event, or sprint starts identical.

## Exporting a project

**Export a project** to a portable file — an offline copy, a move elsewhere, or a backup of one project. It imports back in later.

!!! note "People are named by handle"
    An export identifies assignees, event attendees and person-typed properties by **handle** (`foobar#1234`), because a handle is the same in every community and an email address isn't. Imports match the same way. Anything exported before this was true won't match its people; export it again and the new file will.

## Archiving and deleting

- **Archive** hides a finished project without losing anything. Unarchive to bring it back.
- **Delete** sends it to the community **Trash**, restorable by an admin until the retention period passes.

## Related

- [Task views](task-views.md) — Table, Kanban, Calendar.
- [Tags](tags.md) — labeling and filtering.
- [Your space](your-space.md) — all your tasks, across every project and community.
