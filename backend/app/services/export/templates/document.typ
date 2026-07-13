// Lexical document export template. All data arrives as ONE json string via
// sys.inputs (never interpolated into this source) — user text stays data.
// Referenced images are staged by the backend under assets/ in the compile
// root; the payload's image blocks name them by file.
#let payload = json(bytes(sys.inputs.at("data", default: "{}")))
#let blocks = payload.at("blocks", default: ())

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
#set text(font: "Outfit", size: 10pt)

#let render_runs(runs) = {
  runs
    .map(r => {
      let t = r.at("text", default: "")
      let body = if r.at("code", default: false) { raw(t) } else { [#t] }
      if r.at("bold", default: false) { body = strong(body) }
      if r.at("italic", default: false) { body = emph(body) }
      if r.at("strike", default: false) { body = strike(body) }
      if r.at("underline", default: false) { body = underline(body) }
      let url = r.at("link", default: none)
      if url != none { body = link(url, body) }
      body
    })
    .join()
}

#let render_list(lst, depth) = {
  // Items render one at a time so each item's nested lists appear directly
  // BENEATH it, not after all its siblings. Ordered lists keep their
  // numbering across the single-item enum() calls via start:. Tighten block
  // spacing so per-item calls read as one list.
  set block(above: 3pt, below: 3pt)
  let items = lst.at("items", default: ())
  let checklist = lst.at("checklist", default: false)
  let ordered = lst.at("ordered", default: false)
  let index = 1
  for item in items {
    let body = render_runs(item.at("runs", default: ()))
    pad(left: depth * 1em)[
      #if checklist [
        #box(if item.at("checked", default: false) [☑] else [☐]) #body
      ] else if ordered [
        #enum(start: index, body)
      ] else [
        #list(body)
      ]
    ]
    index += 1
    for nested in item.at("children", default: ()) {
      render_list(nested, depth + 1)
    }
  }
}

#let title = payload.at("title", default: "")
#if title != "" [
  #text(size: 18pt, weight: "bold", title)
  #v(2pt)
  #text(size: 9pt, fill: luma(100), payload.at("subtitle", default: ""))
  #v(10pt)
]

#for b in blocks {
  let btype = b.at("type", default: "paragraph")
  if btype == "heading" {
    let level = calc.min(b.at("level", default: 1), 4)
    let sizes = (14pt, 12.5pt, 11.5pt, 10.5pt)
    v(6pt)
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
  } else if btype == "image" {
    let asset = b.at("asset", default: none)
    if asset != none {
      // Honor the editor's resize (CSS px -> pt at 0.75), clamped to the
      // content width (~470pt on A4 with these margins); untouched images
      // keep the 80% default.
      let wpx = b.at("width", default: none)
      let hpx = b.at("height", default: none)
      if wpx != none {
        image("assets/" + asset, width: calc.min(wpx * 0.75, 470) * 1pt)
      } else if hpx != none {
        image("assets/" + asset, height: calc.min(hpx * 0.75, 680) * 1pt)
      } else {
        image("assets/" + asset, width: 80%)
      }
    } else {
      let url = b.at("url", default: "")
      link(url)[#b.at("alt", default: url)]
    }
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
