// Generic data-table export template: unlike task-table/project-report the
// column set comes from the payload (key/label, optional width hint), so any
// source with a columns/rows payload renders without a bespoke template.
// All data arrives as ONE json string via sys.inputs (never interpolated
// into this source) — user text stays data.
#let payload = json(bytes(sys.inputs.at("data", default: "{}")))
#let cols = payload.at("columns", default: ())
#let rows = payload.at("rows", default: ())
#let description = payload.at("description", default: "")

#set page(
  paper: "a4",
  margin: (x: 1.5cm, y: 1.8cm),
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
#set text(font: "Outfit", size: 9pt)

#text(size: 16pt, weight: "bold", payload.at("title", default: "Export"))
#v(2pt)
#text(size: 9pt, fill: luma(100), payload.at("subtitle", default: ""))
#v(6pt)

#if description != "" [
  #block(
    inset: (x: 8pt, y: 6pt),
    fill: luma(248),
    radius: 3pt,
    width: 100%,
    text(size: 9pt, description),
  )
  #v(8pt)
]

// Width hints are a closed vocabulary (payload-controlled, so no arbitrary
// track expressions); unknown values fall back to auto.
#let track(w) = if w == "2fr" { 2fr } else if w == "1fr" { 1fr } else { auto }
// Cells can be numbers (counter values, rotation order) — render as text.
#let cell(v) = if v == none { "" } else { str(v) }

#if rows.len() == 0 [
  #emph(payload.at("empty_message", default: ""))
] else [
  #table(
    columns: cols.map(c => track(c.at("width", default: "auto"))),
    inset: (x: 6pt, y: 5pt),
    stroke: none,
    fill: (_, y) => if y == 0 { luma(230) } else if calc.odd(y) { luma(247) } else { white },
    table.header(..cols.map(c => strong(cell(c.at("label", default: ""))))),
    ..rows
      .map(r => cols.map(c => cell(r.at(c.at("key", default: ""), default: ""))))
      .flatten()
  )
]
