/**
 * A navigation blocker must say when it also blocks a reload.
 *
 * `useBlocker`'s `enableBeforeUnload` defaults to **true**, and the router
 * never consults `shouldBlockFn` for an unload — so a mounted blocker prompts
 * "Changes you made may not be saved" on every refresh, whether or not there
 * is anything to save. That is not theoretical: the posts board renders its
 * create dialog whether it is open or not, so every refresh of the board asked
 * the question with nothing typed.
 *
 * The condition has to be repeated rather than inferred, so this only checks
 * that the option is present — a blocker that genuinely wants the prompt
 * always can pass `true` and say so.
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const SRC = path.resolve(__dirname, "..");

const walk = (dir: string, found: string[] = []): string[] => {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, found);
    else if (/\.tsx?$/.test(entry.name) && !entry.name.includes(".test.")) found.push(full);
  }
  return found;
};

describe("useBlocker", () => {
  it("always says whether it blocks a reload too", () => {
    const offenders: string[] = [];
    for (const file of walk(SRC)) {
      const source = fs.readFileSync(file, "utf-8");
      for (const call of source.matchAll(/useBlocker\(\{([\s\S]*?)\}\)/g)) {
        if (!call[1].includes("enableBeforeUnload")) {
          offenders.push(path.relative(SRC, file));
        }
      }
    }

    expect(
      offenders,
      `these block navigation but leave the reload prompt on unconditionally — pass \`enableBeforeUnload\`: ${offenders.join(", ")}`
    ).toEqual([]);
  });
});
