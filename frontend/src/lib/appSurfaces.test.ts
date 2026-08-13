/**
 * Which surfaces belong where.
 *
 * A definition pinned before surfaces could say where they belong carries no
 * scopes, and every one of those is guild-wide — so the absent case is the one
 * that matters most here. Getting it wrong would empty the app pages of every
 * install that predates this.
 */

import { describe, expect, it } from "vitest";

import { appEmbeds, guildAppPath } from "./appSurfaces";

const embed = (id: string, scopes?: string[]) => ({
  id,
  path: `/embed/${id}`,
  name: { en: id },
  ...(scopes ? { scopes } : {}),
});

describe("appEmbeds", () => {
  it("reads a surface that says nothing as guild-wide", () => {
    const definition = { embeds: [embed("board")] };
    expect(appEmbeds(definition).map((e) => e.id)).toEqual(["board"]);
    expect(appEmbeds(definition, "initiative")).toEqual([]);
  });

  it("offers a surface in both places when it asked for both", () => {
    const definition = { embeds: [embed("runs", ["guild", "initiative"])] };
    expect(appEmbeds(definition, "guild").map((e) => e.id)).toEqual(["runs"]);
    expect(appEmbeds(definition, "initiative").map((e) => e.id)).toEqual(["runs"]);
  });

  it("keeps an initiative-only surface off the guild page", () => {
    const definition = { embeds: [embed("runs", ["initiative"])] };
    expect(appEmbeds(definition, "guild")).toEqual([]);
    expect(appEmbeds(definition, "initiative").map((e) => e.id)).toEqual(["runs"]);
  });

  it("ignores entries that are not surfaces", () => {
    const definition = { embeds: [{ id: "no-path" }, null, "board", embed("real")] };
    expect(appEmbeds(definition).map((e) => e.id)).toEqual(["real"]);
  });

  it("has nothing to offer when the app declares no embeds", () => {
    expect(appEmbeds({})).toEqual([]);
    expect(appEmbeds(null)).toEqual([]);
  });
});

describe("guildAppPath", () => {
  it("gives an app with a guild-wide surface a page", () => {
    expect(guildAppPath({ id: 7, definition: { embeds: [embed("board")] } })).toBe("/apps/7");
  });

  it("gives an app with only initiative surfaces no guild page", () => {
    expect(
      guildAppPath({ id: 7, definition: { embeds: [embed("runs", ["initiative"])] } })
    ).toBeNull();
  });
});
