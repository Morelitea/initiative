import path from "node:path";

import { describe, expect, it } from "vitest";

import { templates } from "./vite-plugin-templates.mjs";

const card = path.join(import.meta.dirname, "../src/themes/tavern/sections/task.card.html");

const load = (id: string) => {
  const plugin = templates();
  const context = {
    addWatchFile: () => {},
    error: (message: string) => {
      throw new Error(message);
    },
  };
  return (plugin.load as (this: typeof context, id: string) => string | null).call(context, id);
};

describe("the templates plugin", () => {
  it("compiles a template however the query is written", () => {
    // The build and the tests ask for `?template`; the dev server adds its own flags.
    for (const id of [`${card}?template`, `${card}?import&template`]) {
      expect(load(id)).toMatch(/^export default \{"section":"task.card"/);
    }
  });

  it("leaves anything else to Vite", () => {
    expect(load(card)).toBeNull();
    expect(load(`${card}?raw`)).toBeNull();
  });
});
