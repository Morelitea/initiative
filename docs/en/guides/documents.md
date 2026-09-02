---
icon: lucide/file-text
---

# Documents

A **document** is where your group writes things down — notes, plans, scripts, budgets — and keeps files. Documents live inside an initiative, and many of them can be edited by several people **at the same time**, live.

## Kinds of document

When you create a document, you choose a type:

| Type | What it's for |
|---|---|
| **Text document** | A rich-text page — like a word processor — for notes, plans, and write-ups. |
| **Spreadsheet** | A grid of cells with formulas, for numbers, lists, and tables. |
| **Whiteboard** | A free-form visual canvas for sketching ideas and diagrams. |
| **Smart link** | An embedded view of something hosted elsewhere (a YouTube video, a shared file, and the like). |
| **Upload** | A file you upload — PDF, Word, Excel, PowerPoint, text, images, and more. |

!!! info "File uploads have a size limit"
    Uploaded files can be up to **50&nbsp;MB** each. For very large files, link to them with a **Smart link** instead.

## Creating a document

1. In an initiative (or from **My Documents**), choose **Create Document**.
2. Pick the **document type**.
3. Give it a **title** and confirm the **initiative** it belongs to.
4. Optionally start from a **template**.
5. **Start writing** (or upload your file).

![Creating a document](../images/documents/create-document.png)

## Writing a text document

The text editor has the tools you'd expect:

- **Formatting** — bold, italic, underline, strikethrough, superscript, subscript, and inline code.
- **Blocks** — headings, paragraphs, quotes, and code blocks.
- **Lists** — bulleted, numbered, and checklists.
- **Alignment** — left, center, right, justified.
- **Insert** — images, tables, a horizontal divider, and embedded videos.
- **Undo / redo** for when you change your mind.

Everything **autosaves** as you type, so there's no "save" button to remember.

A few keys do more than they look:

- `@` mentions a person, and `#` links to anything in the initiative — see [Mentions & links](mentions-and-links.md).
- `[[` links to another document, and offers to create one if the name is new.
- `/` opens the insert menu — images, tables, embeds, and [smart chips](#smart-chips).

![The document editor](../images/documents/editor.png)

## Smart chips

A link tells you something exists. A **smart chip** tells you what it's doing right now.

Type `/` in a text document and pick one, or choose **Smart chip** from the toolbar's insert menu and pick the thing first:

| Smart chip | Shows |
|---|---|
| Task status | The column the task sits in, in that project's colour |
| Task assignee | Who's holding it |
| Task due date | When it's due — in red once that's passed, unless the work is finished |
| Task priority | How urgent it was marked |
| Counter value | The current number, against its target where it has one |
| Event date | When it happens, dimmed once it has |

The chip carries the reading itself, so your sentence keeps its shape:

> Ship the release — **In progress** · **12 Sep**

Hover one to see what it's about: what the thing is called now, what kind of thing it is, and which of its facts you're looking at. Click it to open that thing.

Move that task to Done and the chip turns green — here, and in every other document that mentions it, without anyone editing a word.

Smart chips are for text documents. A whiteboard and a spreadsheet hold shapes and cells rather than sentences, so there's nowhere for a chip to sit.

!!! note "What other people see"
    A chip shows what *you* can see. If a document mentions a task in a project that hasn't been shared with you, the chip shows the name it had when it was written and nothing about its state.

!!! tip "Exports show the words, not the chip"
    A chip can't keep itself current inside a PDF or a Word file, so an export shows the name the thing had when the chip was written.

## Working in a spreadsheet

The spreadsheet supports the everyday essentials:

- **Formulas** like `SUM`, `AVERAGE`, `MIN`, `MAX`, `COUNT`, `IF`, and `ROUND`.
- **Formatting** — fonts, colors, alignment, and number formats (plain, number, currency, percent, date).
- **Freeze** rows or columns so headers stay put as you scroll.
- **Import and export** as CSV or Excel (XLSX).

## Sketching on a whiteboard

A **whiteboard** is a free-form canvas for the thinking that doesn't fit in a paragraph — a floor plan, a seating chart, a flow of who-does-what, boxes and arrows on a wall.

- **Draw anything** — shapes, arrows, freehand lines, text, and images, arranged however you like.
- **Work on it together** — everyone's pointer shows up live, labeled with their name, so you can point at the same thing at the same time.
- **Go fullscreen** when the canvas needs the whole window.
- **Export as a picture** — save a whiteboard as a **PNG** or **SVG** image to drop into a slide deck, an email, or a printout.

Whiteboards autosave like everything else, and they're shared, tagged, and commented on exactly like any other document.

## Editing together, live

Documents are built for collaboration:

- **Real-time editing** — when two people open the same document, they see each other's changes appear as they happen.
- **Autosave** keeps everything current without anyone hitting save.
- **Offline-friendly** — if your connection drops, you can keep editing; your changes sync up when you're back online.

!!! tip "You'll see who else is here"
    When others are viewing or editing a document with you, Initiative shows who's present, so you won't accidentally talk over each other.

## Comments and mentions

Open a document's **Comments** to discuss it without changing the content. You can reply to build a thread, and edit or delete your own comments. The thread sits at the full width of the page, underneath the document — the same place it sits on every other kind of page.

To pull someone into the conversation, type `@` and pick them — they'll get a notification. To point at something rather than someone, type `#` and pick any project, task, document, queue, counter, calendar event or dashboard in the initiative.

See [Mentions & links](mentions-and-links.md).

### Reactions

Every comment has a row of **reactions** underneath it and a small button to add one. A reaction is a way to answer without writing a reply — agreement, thanks, or "I've seen this."

- Click the button to pick an emoji. It opens on a set of common suggestions, with every emoji searchable underneath.
- Click a reaction someone has already added to add yours to it; click it again to take yours back.
- Hovering a reaction shows who added it.

Anyone who can reply to a thread can react to it, and the community home's recent-comments feed shows what each comment drew. The comment's author is notified about reactions — as a periodic summary rather than one message each, and only if they've left that switch on under [Notifications](notifications.md).

!!! tip "Turning comments off"
    Every tool — documents, projects, queues, counters, calendars, and dashboards — has a
    **Disable comments** switch under **Settings → Advanced**. Turning it off takes the thread
    off that item's page; nothing is deleted, and it all comes back if you turn it on again.
    Tasks are unaffected: a task keeps its own comments whatever its project is set to.

## File documents and version history

For uploaded files, Initiative keeps a **version history**. When a file is updated, you can **upload a new version** while the older ones stay available, each marked with its date. That way you can always get back to an earlier copy.

## Attaching documents to a project

A document can be **attached** to a project so the relevant reference sits right next to the work. From a project, choose **Attach existing** to link a document you've already made (or create a new one to attach).

## Document settings

Open a document's **settings** for:

- **Details** — tags and metadata.
- **Access** — who can view, edit, or own it (see [Sharing](../sharing/sharing-projects-and-documents.md)). Access levels are **Viewer**, **Editor**, and **Owner**.
- **Advanced** — save as a template, duplicate it, copy it to another initiative, or delete it.

## Templates

Made a document layout you'll reuse — a meeting-notes format, a project brief? Save it as a **template** and start fresh copies from it any time. Templates are copied, not edited directly, so the original stays pristine.

## Related

- [Sharing projects & documents](../sharing/sharing-projects-and-documents.md) — control who sees each document.
- [Tags](tags.md) — organize documents with labels.
- [Mentions & links](mentions-and-links.md) — refer to people and other work.
- [Your space](your-space.md) — find all the documents that are yours.
