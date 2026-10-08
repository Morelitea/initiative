/**
 * Tavern, Initiative's own theme: every community screen's layout, as templates.
 *
 * Laid out exactly as a community's theme is (`sections/`, and later `blocks/`,
 * `snippets/`, `assets/`, `config/`), so what a contributor edits here is what a
 * theme author sees in the code editor. The Vite plugin compiles each
 * `sections/<name>.html` when it is imported, and a template that does not
 * compile fails the build like a type error.
 */

import type { CompiledTemplate } from "@/lib/templates/compile";

const compiled = import.meta.glob<CompiledTemplate>("./sections/*.html", {
  query: "?template",
  import: "default",
  eager: true,
});

/** Tavern's template for each section, by section name. */
export const TAVERN: Readonly<Record<string, CompiledTemplate>> = Object.fromEntries(
  Object.values(compiled).map((template) => [template.section, template])
);
