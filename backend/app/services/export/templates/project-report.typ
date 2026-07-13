// Project report template. All data arrives as ONE json string via
// sys.inputs (never interpolated into this source) — user text stays data.
#let payload = json(bytes(sys.inputs.at("data", default: "{}")))
#let rows = payload.at("rows", default: ())
#let description = payload.at("description", default: "")

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

#text(size: 16pt, weight: "bold", payload.at("title", default: "Project"))
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

#if rows.len() == 0 [
  _This project has no tasks._
] else [
  #table(
    columns: (2fr, auto, auto, auto, 1fr),
    inset: (x: 6pt, y: 5pt),
    stroke: none,
    fill: (_, y) => if y == 0 { luma(230) } else if calc.odd(y) { luma(247) } else { white },
    table.header(
      [*Task*], [*Status*], [*Priority*], [*Due*], [*Assignees*],
    ),
    ..rows
      .map(r => (
        r.at("title", default: ""),
        r.at("status", default: ""),
        r.at("priority", default: ""),
        r.at("due", default: ""),
        r.at("assignees", default: ""),
      ))
      .flatten()
  )
]
