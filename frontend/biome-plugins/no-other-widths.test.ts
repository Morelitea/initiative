// biome-ignore-all lint/plugin: these are the rule's fixtures
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterAll, describe, expect, it } from "vitest";

const frontend = path.join(import.meta.dirname, "..");
const dir = mkdtempSync(path.join(tmpdir(), "no-other-widths-"));
afterAll(() => rmSync(dir, { recursive: true, force: true }));

const refused = {
  "a breakpoint Tailwind no longer has": 'cn("2xl:flex")',
  "a Tailwind container size": '"@xs:flex @md:hidden"',
  "an arbitrary viewport width": '"min-[400px]:grid"',
  "an arbitrary container width": '"@[30rem]:flex"',
  "a min-width query": 'matchMedia("(min-width: 700px)")',
  "a range query": 'matchMedia("(width >= 44rem)")',
  "a range query written the other way": 'matchMedia("(700px <= width)")',
  "an exact width query": 'matchMedia("(width: 700px)")',
};
const allowed = {
  "the four breakpoints": '"sm:flex md:hidden lg:grid xl:block max-sm:p-0"',
  "the canvas variants": '"canvas-sm:flex-row canvas-md:hidden"',
  "sizes that are not variants": '"text-sm rounded-md max-w-md grid-cols-fill-60"',
  "a query built from a breakpoint": "`(width >= ${value})`",
  "a query on something else": 'matchMedia("(prefers-reduced-motion: reduce)")',
  "a width declaration": '"width: 10px"',
};
const css = {
  refused: "@media (min-width: 700px) { .a { color: red; } }",
  allowed: "@media (prefers-reduced-motion: reduce) { .a { color: red; } }",
};

/** Lints every fixture in one Biome run, and says which files it flagged. */
const flagged = (() => {
  const files: string[] = [];
  const write = (name: string, source: string) => {
    const file = path.join(dir, name);
    writeFileSync(file, source);
    files.push(file);
    return file;
  };
  const sources = Object.values({ ...refused, ...allowed });
  sources.forEach((expression, index) => {
    write(`${index}.ts`, `declare const value: string;\nexport const x = ${expression};\n`);
  });
  write("refused.css", css.refused);
  write("allowed.css", css.allowed);
  let output: string;
  try {
    output = execFileSync(
      path.join(frontend, "node_modules/.bin/biome"),
      ["lint", `--config-path=${frontend}`, "--only=plugin", "--reporter=json", ...files],
      { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }
    );
  } catch (error) {
    output = (error as { stdout: string }).stdout;
  }
  const report = JSON.parse(output) as { diagnostics: { location: { path: string } }[] };
  return new Set(report.diagnostics.map((diagnostic) => path.basename(diagnostic.location.path)));
})();

const fileOf = (expression: string) =>
  `${Object.values({ ...refused, ...allowed }).indexOf(expression)}.ts`;

describe("the no-other-widths rule", () => {
  it.each(Object.entries(refused))("refuses %s", (_, expression) => {
    expect(flagged.has(fileOf(expression))).toBe(true);
  });

  it.each(Object.entries(allowed))("allows %s", (_, expression) => {
    expect(flagged.has(fileOf(expression))).toBe(false);
  });

  it("refuses a width query in CSS, and nothing else", () => {
    expect(flagged.has("refused.css")).toBe(true);
    expect(flagged.has("allowed.css")).toBe(false);
  });
});
