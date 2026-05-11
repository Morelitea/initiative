---
name: initiative
description: Manage Initiative tasks and projects from the terminal. Use this skill when the user asks to list, view, create, update, complete, or delete tasks or projects in Initiative.
allowed-tools: Bash(curl *) Bash(cat *) Bash(python3 *) Read
---

# Initiative Task Manager

Manage Initiative tasks, subtasks, documents, and workspaces directly from Claude without opening the UI.

---

## Step 1 — Load config

Read the config file and extract credentials:

!`cat ~/.initiative.json 2>/dev/null || echo '{"_missing": true}'`

If `_missing` is true or the file doesn't exist, stop and tell the user:

> **Setup required.** Create `~/.initiative.json` with your Initiative credentials:
>
> ```json
> {
>   "token": "your-jwt-token",
>   "guild_id": 1,
>   "api_url": "http://localhost:8000/api/v1"
> }
> ```
>
> To get your token: open Initiative in the browser → DevTools → Application → Local Storage → copy the value of `initiative_token`.

Parse `token`, `guild_id`, and `api_url` from the config. These are referenced as `$TOKEN`, `$GUILD`, and `$API` throughout.

Set these as shell variables for all subsequent curl calls:
```bash
CONFIG=$(cat ~/.initiative.json)
TOKEN=$(echo "$CONFIG" | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")
GUILD=$(echo "$CONFIG" | python3 -c "import sys,json; print(json.load(sys.stdin)['guild_id'])")
API=$(echo "$CONFIG" | python3 -c "import sys,json; print(json.load(sys.stdin)['api_url'])")
```

---

## Step 2 — Parse the command

The user's input is: `$ARGUMENTS`

Match against the commands below. If the command is ambiguous or arguments are missing, ask the user to clarify before calling any API.

---

## Commands

### `list [project_id] [--mine] [--status <name>] [--priority <level>] [--page <n>]`

List tasks. Without arguments, lists all tasks in the guild (page 1, 25 per page).

Build the conditions array from any filters provided, then call:
```bash
curl -s -G "$API/tasks" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Guild-ID: $GUILD" \
  --data-urlencode "page_size=25" \
  --data-urlencode "page=${page:-1}" \
  --data-urlencode "conditions=${conditions:-[]}" \
  --data-urlencode "sorting=[{\"field\":\"updated_at\",\"dir\":\"desc\"}]"
```

Filter conditions:
- `project_id` → `{"field":"project_id","op":"eq","value":<id>}`
- `--status <name>` → fetch statuses first (see "Resolve status" below), then filter by `task_status_id`
- `--priority <level>` → `{"field":"priority","op":"eq","value":"<level>"}`
- `--mine` → fetch current user first via `GET $API/users/me`, then `{"field":"assignee_ids","op":"in","value":[<user_id>]}`

Display results as an ASCII table:
```
 ID     PRIORITY  STATUS            TITLE                           ASSIGNEES        DUE
 ─────  ────────  ────────────────  ──────────────────────────────  ───────────────  ──────────
 1234   high      In Progress       Fix login redirect bug          Alice, Bob       2026-05-15
 1235   medium    To Do             Add dark mode toggle            —                —
 1236   low       Done              Update README                   Charlie          2026-05-01

Showing 3 of 3 tasks  (page 1)
```

Truncate title at 30 chars. Show `—` for empty dates/assignees. Sort priority display: urgent > high > medium > low.

---

### `show <task_id>`

Show full detail for one task, including its subtasks.

```bash
curl -s "$API/tasks/$TASK_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Guild-ID: $GUILD"

curl -s "$API/tasks/$TASK_ID/subtasks" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Guild-ID: $GUILD"
```

Display in structured format:
```
Task #1234 — Fix login redirect bug
────────────────────────────────────────────────
Project   : Frontend Redesign  (#42)
Status    : In Progress
Priority  : high
Assignees : Alice Smith, Bob Jones
Due Date  : 2026-05-15
Created   : 2026-05-01 by Alice Smith
Tags      : bug, auth

Description:
  When a user clicks a deep link before logging in,
  the redirect after login goes to / instead of the
  intended page.

Subtasks (2/5 completed):
  [x] #1  Reproduce the bug
  [x] #2  Identify affected routes
  [ ] #3  Fix redirect logic
  [ ] #4  Write tests
  [ ] #5  Deploy to staging
```

---

### `create <project_id> "<title>" [--priority <level>] [--due <YYYY-MM-DD>] [--assign <user_id>] [--description "<text>"]`

Create a new task.

Before calling the API, confirm with the user:
> Create task **"<title>"** in project #<project_id> with priority **<priority>**?  
> Assignees: <names or "none"> | Due: <date or "none">

On confirmation, POST:
```bash
curl -s -X POST "$API/tasks" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Guild-ID: $GUILD" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": <project_id>,
    "title": "<title>",
    "priority": "<priority>",
    "due_date": "<due_date or null>",
    "assignee_ids": [<ids or empty>],
    "description": "<description or null>"
  }'
```

On success, show the created task in `show` format and print:
```
✓ Task #<id> created.
```

---

### `update <task_id> <field> <value>`

Update a single field on a task. Supported fields:

| Field | Value format |
|---|---|
| `title` | quoted string |
| `priority` | `low` / `medium` / `high` / `urgent` |
| `status` | status name (resolved to ID — see below) |
| `due` | `YYYY-MM-DD` or `none` to clear |
| `description` | quoted string |
| `assign` | user ID (adds assignee) |
| `unassign` | user ID (removes assignee) |
| `archive` | `true` / `false` |

**Resolve status by name:** fetch the project's statuses first:
```bash
curl -s "$API/tasks/$TASK_ID" -H "Authorization: Bearer $TOKEN" -H "X-Guild-ID: $GUILD" \
  | python3 -c "import sys,json; t=json.load(sys.stdin); print(t['project']['id'])"

curl -s "$API/projects/$PROJECT_ID/task-statuses" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Guild-ID: $GUILD"
```
Match the status name case-insensitively to get its ID.

**For `assign`/`unassign`:** fetch the task's current `assignee_ids`, add or remove the given user ID, and PATCH `assignee_ids` with the full updated list.

Confirm before writing:
> Update task #<id>: set **<field>** → **<value>**?

```bash
curl -s -X PATCH "$API/tasks/$TASK_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Guild-ID: $GUILD" \
  -H "Content-Type: application/json" \
  -d '{<field>: <value>}'
```

On success: `✓ Task #<id> updated.`

---

### `complete <task_id>`

Mark a task done. Shorthand for `update <task_id> status done`.

1. Fetch the task to get `project_id` and current title.
2. Fetch `GET $API/projects/$PROJECT_ID/task-statuses` and find the status where `category == "done"`.
3. Confirm:
   > Mark task #<id> **"<title>"** as done?
4. PATCH `task_status_id` to the done status ID.

On success: `✓ Task #<id> marked complete.`

---

### `delete <task_id>`

Delete a task permanently.

1. Fetch the task to show its title in the confirmation prompt.
2. Confirm:
   > Permanently delete task #<id> **"<title>"**? This cannot be undone.
3. On confirmation:
```bash
curl -s -X DELETE "$API/tasks/$TASK_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Guild-ID: $GUILD"
```

On success: `✓ Task #<id> deleted.`

---

### `subtask add <task_id> "<content>"`

Add a subtask to an existing task.

Confirm:
> Add subtask **"<content>"** to task #<task_id>?

```bash
curl -s -X POST "$API/tasks/$TASK_ID/subtasks" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Guild-ID: $GUILD" \
  -H "Content-Type: application/json" \
  -d '{"content": "<content>"}'
```

On success: `✓ Subtask #<id> added to task #<task_id>.`

---

### `subtask complete <task_id> <subtask_id>`

Mark a subtask as completed.

```bash
curl -s -X PATCH "$API/subtasks/$SUBTASK_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Guild-ID: $GUILD" \
  -H "Content-Type: application/json" \
  -d '{"is_completed": true}'
```

On success: `✓ Subtask #<subtask_id> completed.`

---

### `subtask delete <task_id> <subtask_id>`

Delete a subtask.

Confirm:
> Delete subtask #<subtask_id>?

```bash
curl -s -X DELETE "$API/subtasks/$SUBTASK_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Guild-ID: $GUILD"
```

On success: `✓ Subtask #<subtask_id> deleted.`

---

### `projects`

List all projects in the guild.

```bash
curl -s "$API/projects" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Guild-ID: $GUILD"
```

Display as table:
```
 ID    NAME                           INITIATIVE           TASKS
 ────  ─────────────────────────────  ───────────────────  ─────
 42    Frontend Redesign              Q2 Product            14
 43    API Modernization              Platform               8
 44    Docs Overhaul                  —                      3
```

---

### `workspaces`

List all initiatives (workspaces) in the guild.

```bash
curl -s "$API/initiatives" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Guild-ID: $GUILD"
```

Display as table:
```
 ID    NAME                    DESCRIPTION                         COLOR
 ────  ──────────────────────  ──────────────────────────────────  ───────
 1     Q2 Product              All Q2 product work                 #4f46e5
 2     Platform                Backend infrastructure              #0891b2
 3     Docs Overhaul           —                                   —
```

---

### `workspace create "<name>" [--description "<text>"] [--color <hex>]`

Create a new initiative (workspace).

Confirm:
> Create workspace **"<name>"**?  
> Description: <text or "none"> | Color: <hex or "none">

```bash
curl -s -X POST "$API/initiatives" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Guild-ID: $GUILD" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "<name>",
    "description": "<description or null>",
    "color": "<hex or null>"
  }'
```

On success: `✓ Workspace #<id> "<name>" created.`

---

### `workspace update <initiative_id> <field> <value>`

Update a workspace. Supported fields: `name`, `description`, `color`.

Confirm:
> Update workspace #<id>: set **<field>** → **<value>**?

```bash
curl -s -X PATCH "$API/initiatives/$INITIATIVE_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Guild-ID: $GUILD" \
  -H "Content-Type: application/json" \
  -d '{"<field>": "<value>"}'
```

On success: `✓ Workspace #<id> updated.`

---

### `files [--initiative <id>] [--page <n>]`

List documents/files in the guild, optionally filtered by initiative.

```bash
curl -s -G "$API/documents" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Guild-ID: $GUILD" \
  --data-urlencode "page_size=25" \
  --data-urlencode "page=${page:-1}" \
  ${initiative_id:+--data-urlencode "initiative_id=$initiative_id"}
```

Display as table:
```
 ID     TITLE                          INITIATIVE           UPDATED
 ─────  ─────────────────────────────  ───────────────────  ──────────
 101    API Design Doc                 Platform             2026-05-09
 102    Onboarding Guide               Q2 Product           2026-05-01
 103    Sprint Retro Notes             —                    2026-04-28

Showing 3 of 3 files  (page 1)
```

---

### `file show <document_id>`

Show the content of a document.

```bash
curl -s "$API/documents/$DOCUMENT_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Guild-ID: $GUILD"
```

Display structured output:
```
File #101 — API Design Doc
────────────────────────────────────────────────
Initiative : Platform  (#2)
Updated    : 2026-05-09

Content:
  <rendered plain text from the document's content field>
```

The `content` field is a Lexical JSON state. Extract text nodes and render them as plain paragraphs, preserving heading structure where possible.

---

### `file create <initiative_id> "<title>" [--content "<text>"]`

Create a new document in an initiative.

Confirm:
> Create file **"<title>"** in initiative #<initiative_id>?

Content is optional — if `--content` is provided, wrap it in a minimal Lexical paragraph node structure:
```json
{
  "root": {
    "children": [{"children": [{"text": "<content>", "type": "text"}], "type": "paragraph", "version": 1}],
    "type": "root",
    "version": 1
  }
}
```

```bash
curl -s -X POST "$API/documents" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Guild-ID: $GUILD" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "<title>",
    "initiative_id": <initiative_id>,
    "content": <lexical_json_or_empty_object>
  }'
```

On success: `✓ File #<id> "<title>" created.`

---

### `file edit <document_id> <field> <value>`

Update a document. Supported fields: `title`, `content` (plain text, wrapped into Lexical format).

Confirm:
> Update file #<id>: set **<field>**?

For `content`, fetch the current document first, then replace the text in the Lexical state with the new value using the same minimal structure as `file create`.

```bash
curl -s -X PATCH "$API/documents/$DOCUMENT_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Guild-ID: $GUILD" \
  -H "Content-Type: application/json" \
  -d '{"<field>": <value>}'
```

On success: `✓ File #<id> updated.`

---

### `file delete <document_id>`

Delete a document permanently.

1. Fetch the document to show its title.
2. Confirm:
   > Permanently delete file #<id> **"<title>"**? This cannot be undone.

```bash
curl -s -X DELETE "$API/documents/$DOCUMENT_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Guild-ID: $GUILD"
```

On success: `✓ File #<id> deleted.`

---

### `report [--project <id>] [--initiative <id>] [--mine]`

Generate a markdown summary report of task status across a project or initiative.

1. Fetch tasks using the same filters as `list` but with `page_size=100`.
2. Group by status category: `todo`, `in_progress`, `done`, `cancelled`.
3. Output:

```
## Task Report — Frontend Redesign (#42)
Generated: 2026-05-10

### Summary
  Total     : 14
  To Do     : 4
  In Progress: 6
  Done      : 3
  Cancelled : 1

### In Progress
  #1234  [high]    Fix login redirect bug          — Alice, Bob       due 2026-05-15
  #1238  [medium]  Refactor auth middleware         — unassigned       due —

### To Do
  #1240  [urgent]  Security audit                  — unassigned       due 2026-05-20
  ...

### Done
  #1230  [low]     Update README                   — Charlie
  ...
```

---

### `help`

Print a compact command reference:

```
Tasks:
  /initiative list [project_id] [--mine] [--status <name>] [--priority <level>]
  /initiative show <task_id>
  /initiative create <project_id> "<title>" [--priority <level>] [--due <date>] [--assign <id>]
  /initiative update <task_id> <field> <value>
  /initiative complete <task_id>
  /initiative delete <task_id>

Subtasks:
  /initiative subtask add <task_id> "<content>"
  /initiative subtask complete <task_id> <subtask_id>
  /initiative subtask delete <task_id> <subtask_id>

Projects:
  /initiative projects

Workspaces:
  /initiative workspaces
  /initiative workspace create "<name>" [--description "<text>"] [--color <hex>]
  /initiative workspace update <initiative_id> <field> <value>

Files:
  /initiative files [--initiative <id>]
  /initiative file show <document_id>
  /initiative file create <initiative_id> "<title>" [--content "<text>"]
  /initiative file edit <document_id> <field> <value>
  /initiative file delete <document_id>

Reports:
  /initiative report [--project <id>] [--initiative <id>] [--mine]

  /initiative help
```

---

## Error handling

| HTTP status | Action |
|---|---|
| 401 | Token expired. Tell user to refresh `~/.initiative.json` with a new token. |
| 403 | Insufficient permissions. Show the server's `detail` field. Do not retry. |
| 404 | Resource not found. Confirm the ID with the user. |
| 422 | Show the `detail` validation errors from the response body. |
| Connection refused | API not running. Suggest: `cd backend && uvicorn app.main:app --reload` |

For any other error, print the status code and raw response body so the user can diagnose it.
