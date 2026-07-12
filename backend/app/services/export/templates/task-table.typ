// Task-table export template. All data arrives as ONE json string via
// sys.inputs (never interpolated into this source) — user text stays data.
#let payload = json(bytes(sys.inputs.at("data", default: "{}")))
#let rows = payload.at("rows", default: ())

#set page(
  paper: "a4",
  margin: (x: 1.5cm, y: 1.8cm),
  footer: context {
    set text(size: 8pt, fill: luma(120))
    grid(
      columns: (1fr, auto),
      payload.at("footer", default: ""),
      counter(page).display("1 of 1", both: true),
    )
  },
)
#set text(size: 9pt)

#text(size: 16pt, weight: "bold", payload.at("title", default: "Export"))
#v(2pt)
#text(size: 9pt, fill: luma(100), payload.at("subtitle", default: ""))
#v(8pt)

#if rows.len() == 0 [
  _No tasks matched this filter._
] else [
  #table(
    columns: (2fr, 1fr, auto, auto, auto, 1fr),
    inset: (x: 6pt, y: 5pt),
    stroke: none,
    fill: (_, y) => if y == 0 { luma(230) } else if calc.odd(y) { luma(247) } else { white },
    table.header(
      [*Task*], [*Project*], [*Status*], [*Priority*], [*Due*], [*Assignees*],
    ),
    ..rows
      .map(r => (
        r.at("title", default: ""),
        r.at("project", default: ""),
        r.at("status", default: ""),
        r.at("priority", default: ""),
        r.at("due", default: ""),
        r.at("assignees", default: ""),
      ))
      .flatten()
  )
]
