# Bundled export fonts

**Outfit** — the same typeface the web UI uses, embedded so exported PDFs match
the app's look. Licensed under the SIL Open Font License 1.1 (see `OFL.txt`);
Copyright 2021 The Outfit Project Authors (https://github.com/Outfitio/Outfit-Fonts).

Static instances (Regular 400, Medium 500, Bold 700) were generated from the
Google Fonts variable font with `fonttools varLib.instancer` — Typst 0.15
selects the default (Thin) instance from a variable font rather than the
requested weight, so static cuts are required for correct weights.

The renderer loads this directory via `font_paths` while keeping
`ignore_system_fonts=True`, so output stays deterministic (only the
typst-wheel fonts + these). Typst's automatic glyph fallback covers marks
Outfit lacks (e.g. the checklist boxes ☑ ☐).
