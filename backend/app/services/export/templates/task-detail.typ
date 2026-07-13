// Detailed task report: one task per page, with description, subtasks and
// comments. All data arrives as ONE json string via sys.inputs (never
// interpolated into this source) — user text stays data. The template holds
// NO natural-language content: every field label arrives already localized
// in the payload's `labels` map (the adapter translates to the export
// creator's locale), so this file is pure layout.
#let payload = json(bytes(sys.inputs.at("data", default: "{}")))
#let tasks = payload.at("tasks", default: ())
#let labels = payload.at("labels", default: (:))

#set page(
  paper: "a4",
  margin: (x: 1.8cm, y: 2cm),
  header: context {
    // Guild brand band: name on the left, larger icon top-right, repeated on
    // every page. Absent when no brand is supplied, so it stays inert.
    let brand = payload.at("brand", default: none)
    if brand != none {
      let icon = brand.at("icon", default: none)
      grid(
        columns: (1fr, auto),
        align: (left + horizon, right + top),
        text(size: 9pt, fill: luma(90), weight: "medium", brand.at("name", default: "")),
        if icon != none { image("assets/" + icon, height: 22pt) } else { [] },
      )
      v(2pt)
      line(length: 100%, stroke: 0.4pt + luma(220))
    }
  },
  footer: context {
    set text(size: 8pt, fill: luma(120))
    grid(
      columns: (1fr, auto),
      payload.at("footer", default: ""),
      counter(page).display("1 of 1", both: true),
    )
  },
)
#set text(size: 10pt)

// Preserve author-entered line breaks in free text (description, comments):
// the string arrives as data, so split and re-emit hard breaks.
#let multiline(s) = {
  // Guard none defensively: a null free-text value must not abort the compile.
  let s = if s == none { "" } else { s }
  let lines = s.split("\n")
  for (i, line) in lines.enumerate() {
    line
    if i < lines.len() - 1 { linebreak() }
  }
}

// A "Label: value" row, only rendered when the value is non-empty.
#let field(label, value) = {
  if value != none and value != "" [
    #text(fill: luma(90))[#strong(label): #value]
    #linebreak()
  ]
}

#let section(label) = {
  v(6pt)
  text(size: 11pt, weight: "bold", label)
  v(2pt)
}

// Report header (page 1 only), then each task — the first shares this page,
// the rest start on their own.
#text(size: 15pt, weight: "bold", payload.at("title", default: ""))
#v(1pt)
#text(size: 9pt, fill: luma(100), payload.at("subtitle", default: ""))
#v(6pt)
#line(length: 100%, stroke: 0.5pt + luma(210))
#v(8pt)

#if tasks.len() == 0 [
  #emph(payload.at("empty_message", default: ""))
]

#for (idx, task) in tasks.enumerate() {
  if idx > 0 { pagebreak() }

  text(size: 16pt, weight: "bold", task.at("title", default: ""))
  v(3pt)

  // Meta line: project · status · priority (non-empty parts only).
  let meta = (
    task.at("project", default: ""),
    task.at("status", default: ""),
    task.at("priority", default: ""),
  ).filter(p => p != "")
  if meta.len() > 0 {
    text(size: 9pt, fill: luma(110), meta.join(" · "))
    v(4pt)
  }

  field(labels.at("due", default: "Due"), task.at("due", default: ""))
  field(labels.at("start", default: "Start"), task.at("start", default: ""))
  field(
    labels.at("assignees", default: "Assignees"),
    task.at("assignees", default: ()).join(", "),
  )
  field(
    labels.at("tags", default: "Tags"),
    task.at("tags", default: ()).join(", "),
  )

  // Description.
  section(labels.at("description", default: "Description"))
  let desc = task.at("description", default: "")
  if desc.trim() != "" [
    #multiline(desc)
  ] else [
    #text(fill: luma(150), style: "italic", labels.at("noDescription", default: ""))
  ]

  // Subtasks (checkboxes from completion state).
  let subs = task.at("subtasks", default: ())
  if subs.len() > 0 {
    section(labels.at("subtasks", default: "Subtasks"))
    for sub in subs [
      #box(if sub.at("done", default: false) [☑] else [☐]) #sub.at("content", default: "")
      #linebreak()
    ]
  }

  // Comments (author · date, then body).
  let comments = task.at("comments", default: ())
  if comments.len() > 0 {
    section(labels.at("comments", default: "Comments"))
    for c in comments {
      text(size: 9pt, fill: luma(110))[#strong(c.at("author", default: "")) · #c.at("date", default: "")]
      linebreak()
      multiline(c.at("content", default: ""))
      v(5pt)
    }
  }
}
