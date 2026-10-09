/**
 * Compile a theme's section templates when they are imported.
 *
 * `import x from "./sections/task.card.html?template"` is the compiled template:
 * the section is the file's name, and its definition comes from the registry.
 * A template that does not compile is an error in the dev overlay and fails the
 * build and the tests, as a type error would. Editing one hot-reloads it.
 *
 * JavaScript with its types beside it (the .d.mts), like the other helpers the
 * Vite config loads, so `tsc -b` checks the config without walking into the
 * compiler; the app's own project checks the compiler.
 */

import { readFileSync } from "node:fs";
import { basename } from "node:path";

import { compileTemplate } from "../src/lib/templates/compile.ts";
import { SECTIONS } from "../src/lib/templates/sections.ts";

/** @returns {import("vite").Plugin} */
export function templates() {
  return {
    name: "initiative-templates",
    enforce: "pre",
    load(id) {
      // The dev server adds flags of its own to the query (`?import&template`),
      // so `template` is looked for among them rather than as the whole query.
      const [file, query = ""] = id.split("?");
      if (!file.endsWith(".html") || !new URLSearchParams(query).has("template")) return null;
      this.addWatchFile(file);
      const name = basename(file, ".html");
      const section = SECTIONS[name];
      if (!section) this.error(`${file}: there is no section called ${name}`);
      const { template, errors } = compileTemplate(readFileSync(file, "utf-8"), {
        name,
        section,
      });
      if (!template) {
        this.error(`${file}:\n${errors.map((error) => `  ${error.message}`).join("\n")}`);
      }
      return `export default ${JSON.stringify(template)};`;
    },
  };
}
