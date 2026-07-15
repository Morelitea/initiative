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
      // Localized page count: the separator word arrives in the payload
      // ("1 of 3" / "1 von 3" / …); explicit current/total rather than a
      // numbering pattern, since pattern words could collide with numbering
      // symbols (e.g. Italian "di" contains roman-numeral "i").
      [#counter(page).display() #payload.at("page_of", default: "of") #counter(page).final().first()],
    )
  },
)
#set text(font: "Outfit", size: 10pt)

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

// ── Markdown-description blocks (same schema as the document template) ──────
#let render_runs(runs) = {
  runs
    .map(r => {
      let t = r.at("text", default: "")
      // A "\n" run is a hard break, not text (Typst collapses raw newlines).
      if t == "\n" { return linebreak() }
      let body = if r.at("code", default: false) { raw(t) } else { [#t] }
      if r.at("bold", default: false) { body = strong(body) }
      if r.at("italic", default: false) { body = emph(body) }
      if r.at("strike", default: false) { body = strike(body) }
      let url = r.at("link", default: none)
      if url != none { body = link(url, body) }
      body
    })
    .join()
}

#let render_list(lst, depth) = {
  // Per-item rendering keeps nested lists directly beneath their parent item;
  // enum(start:) preserves ordered numbering across single-item calls.
  set block(above: 3pt, below: 3pt)
  let ordered = lst.at("ordered", default: false)
  let index = 1
  for item in lst.at("items", default: ()) {
    let body = render_runs(item.at("runs", default: ()))
    pad(left: depth * 1em)[
      #if ordered [ #enum(start: index, body) ] else [ #list(body) ]
    ]
    index += 1
    for nested in item.at("children", default: ()) {
      render_list(nested, depth + 1)
    }
  }
}

#let render_blocks(blocks) = {
  for b in blocks {
    let btype = b.at("type", default: "paragraph")
    if btype == "heading" {
      let level = calc.min(b.at("level", default: 1), 4)
      let sizes = (12pt, 11.5pt, 11pt, 10.5pt)
      v(4pt)
      text(size: sizes.at(level - 1), weight: "bold", render_runs(b.at("runs", default: ())))
      v(2pt)
    } else if btype == "quote" {
      pad(
        left: 8pt,
        block(
          stroke: (left: 2pt + luma(180)),
          inset: (left: 8pt, y: 4pt),
          text(fill: luma(90), render_runs(b.at("runs", default: ()))),
        ),
      )
    } else if btype == "code" {
      block(
        fill: luma(246),
        inset: 8pt,
        radius: 3pt,
        width: 100%,
        raw(b.at("text", default: ""), lang: b.at("language", default: "")),
      )
    } else if btype == "hr" {
      v(4pt)
      line(length: 100%, stroke: 0.5pt + luma(200))
      v(4pt)
    } else if btype == "list" {
      render_list(b, 0)
    } else if btype == "table" {
      let rows = b.at("rows", default: ())
      if rows.len() > 0 {
        let width = calc.max(..rows.map(r => r.len()))
        table(
          columns: width,
          inset: (x: 6pt, y: 5pt),
          stroke: 0.5pt + luma(210),
          ..rows
            .map(r => {
              let padded = r + ((),) * (width - r.len())
              padded.map(c => render_runs(c))
            })
            .flatten()
        )
      }
    } else {
      par(render_runs(b.at("runs", default: ())))
    }
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

  // Description: Markdown parsed server-side into blocks (empty → none).
  section(labels.at("description", default: "Description"))
  let desc_blocks = task.at("description_blocks", default: ())
  if desc_blocks.len() > 0 {
    render_blocks(desc_blocks)
  } else [
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

  // Comments as a reply thread: each reply is indented one level under its
  // parent (depth comes from the payload), so it reads like the on-screen
  // discussion rather than a flat chronological list.
  let comments = task.at("comments", default: ())
  if comments.len() > 0 {
    section(labels.at("comments", default: "Comments"))
    for c in comments {
      pad(left: c.at("depth", default: 0) * 1.4em)[
        #text(size: 9pt, fill: luma(110))[#strong(c.at("author", default: "")) · #c.at("date", default: "")]
        #linebreak()
        #multiline(c.at("content", default: ""))
      ]
      v(5pt)
    }
  }
}
