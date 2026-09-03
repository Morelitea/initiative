---
icon: lucide/file-text
---

# Documents

A **document** is where your group writes things down — notes, plans, scripts, budgets — and keeps its files.

Documents live inside an initiative, and most kinds can be edited by several people **at the same time**, live.

No emailing versions round. No `final_v3_ACTUAL_final.docx`. No wondering whether Dave is working on the old one.

## Kinds of document

| Type | What it's for |
|---|---|
| **Text document** | A page you write on, like a word processor. Notes, plans, write-ups. |
| **Spreadsheet** | A grid with formulas. Numbers, lists, tables. |
| **Whiteboard** | A blank canvas for sketching things out. |
| **Smart link** | An embedded view of something that lives somewhere else — a video, a shared file. |
| **Upload** | An actual file: PDF, Word, Excel, PowerPoint, images, and more. |

!!! info "50 MB per uploaded file"
    Plenty for almost anything that isn't video. For the things that are, use a **Smart link** to point at wherever it already lives instead.

## Making one

1. In an initiative, choose **Create Document**.
2. Pick the **type**.
3. Give it a **title** and confirm which **initiative** it belongs to.
4. Optionally start from a **template**.
5. Write. Or upload. Or draw.

![Creating a document](../images/documents/create-document.png)

## Writing a text document

The editor has what you'd expect: **bold, italic, underline**, headings, quotes, code blocks, bulleted and numbered lists, checklists, alignment, images, tables, dividers, embedded video, and undo for when you change your mind.

Everything **autosaves**. There is no save button — which means there is no save button to forget to press at 11pm, and no version of this evening where you lose forty minutes of work to a browser tab.

Four keys do more than they look like they do:

- `@` mentions a person.
- `#` links to anything in the initiative. See [Mentions & links](mentions-and-links.md).
- `[[` links to another document — and offers to make one if the name is new.
- `/` opens the insert menu: images, tables, embeds, and [smart chips](#smart-chips).

![The document editor](../images/documents/editor.png)

## Smart chips

A link tells you something exists. A **smart chip** tells you what it's *doing right now*, and keeps telling you without anybody maintaining it.

Type `/` in a text document and pick one, or use **Smart chip** in the toolbar's insert menu. The picker opens on whatever you were working on most recently, so usually there's nothing to type.

| Smart chip | Shows |
|---|---|
| Task status | The column it's sitting in, in that project's colour |
| Task assignee | Who's holding it |
| Task due date | When it's due — turning red once that's passed, unless it's finished |
| Task priority | How urgent somebody said it was |
| Counter value | The current number, against its target if it has one |
| Event date | When it happens, dimmed once it has |

The chip carries the reading itself, so your sentence keeps its shape:

> Ship the release — **In progress** · **12 Sep**

Hover it to see what the thing is called now and what kind of thing it is. Click it to go there.

Move that task to Done and the chip turns green — here, and in every other document that mentions it, with nobody editing a word. Meeting notes that are still accurate a month later, more or less for free.

Smart chips are a text-document thing. A whiteboard holds shapes and a spreadsheet holds cells, so there's nowhere for a chip to sit.

!!! note "What other people see"
    A chip shows what *you* can see. If a document mentions a task in a project nobody's shared with you, the chip just shows the name it had when it was written, and nothing about its state.

!!! tip "Exports show the words, not the chip"
    A chip can't keep itself up to date inside a PDF or a Word file, so an export shows the name the thing had when the chip was written.

## Spreadsheets

The everyday essentials, and not much more:

- **Formulas** — `SUM`, `AVERAGE`, `MIN`, `MAX`, `COUNT`, `IF`, `ROUND`.
- **Formatting** — fonts, colours, alignment, and number formats (plain, number, currency, percent, date).
- **Freeze** rows or columns so the headers stay put while you scroll.
- **Import and export** as CSV or Excel.

## Whiteboards

A blank canvas for the thinking that flatly refuses to become a paragraph. A floor plan. A seating chart. Who-does-what. Boxes and arrows that made complete sense at the time and will need explaining in March.

- **Draw anything** — shapes, arrows, freehand lines, text, images.
- **Work on it together** — everyone's pointer shows up live with their name on it, so you can point at the same thing at the same time from different houses.
- **Go fullscreen** when the canvas wants the whole window.
- **Export as a picture** — PNG or SVG, for a slide deck, an email, or a printout.

Whiteboards autosave like everything else, and are shared, tagged and commented on exactly like any other document.

## Working on something together

- **Real-time editing** — open the same document as somebody else and you'll see their changes appear as they type.
- **Autosave** keeps it current without anyone doing anything.
- **Offline-friendly** — if your connection drops you can keep working, and it syncs up when you're back.

!!! tip "You'll see who else is in here"
    Initiative shows who's viewing or editing alongside you, so nobody rewrites the same paragraph twice in opposite directions.

## Comments and mentions

Open a document's **Comments** to talk about it without touching the actual content. Reply to build a thread; edit or delete your own.

To pull somebody in, type `@`. To point at a *thing* rather than a person, type `#` and pick any project, task, document, queue, counter, calendar event or dashboard in the initiative. See [Mentions & links](mentions-and-links.md).

### Reactions

Every comment gets a row of **reactions** and a button to add one — a way to answer without writing a whole reply. Agreement, thanks, or the universally understood "I have read this and have nothing to add."

- Click the button and pick an emoji. Common ones first, everything searchable underneath.
- Click a reaction somebody's already added to join in; click again to take yours back.
- Hover one to see who added it.

Anyone who can reply can react. The author gets told — as a periodic summary, not one ping per thumbs-up, because that would be unbearable — and only if they've left that switch on under [Notifications](notifications.md).

!!! tip "Turning comments off"
    Every tool — documents, projects, queues, counters, calendars, dashboards — has a **Disable comments** switch under **Settings → Advanced**. It takes the thread off that item's page; nothing is deleted, and it all comes back if you switch it on again.

    Tasks are unaffected. A task keeps its own comments whatever its project says.

## Uploaded files and version history

Uploaded files keep a **version history**. Upload a new version and the older ones stay put, each marked with its date.

So you can always get back to the copy from before somebody helpfully reorganised it.

## Attaching documents to a project

A document can be **attached** to a project so the relevant reference sits right next to the work. From a project, choose **Attach existing** — or make a new one to attach.

## Document settings

- **Details** — tags and metadata.
- **Access** — who can view, edit or own it. Levels are **Viewer**, **Editor**, **Owner**. See [Sharing](../sharing/sharing-projects-and-documents.md).
- **Advanced** — save as a template, duplicate, copy to another initiative, delete.

## Templates

Made a layout you'll use again — a meeting-notes format, a project brief? Save it as a **template** and start fresh copies from it whenever.

Templates get copied rather than edited, so the original stays pristine no matter what anyone does to their copy.

## Related

- [Sharing projects & documents](../sharing/sharing-projects-and-documents.md) — who sees each one.
- [Tags](tags.md) — labelling so you can find things later.
- [Mentions & links](mentions-and-links.md) — pointing at people and other work.
- [Your space](your-space.md) — every document that's yours, in one list.
