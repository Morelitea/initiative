/**
 * Which surfaces belong where, and which are worth offering to whom.
 *
 * Two readings that are easy to get wrong. A definition pinned before surfaces
 * could say where they belong carries no scopes, and every one of those is
 * guild-wide — getting that wrong would empty the app pages of every install
 * that predates it. And who may open a surface is the server's answer
 * (`surface_access`), so a surface the server did not say opens here is not
 * offered, whatever the definition declares.
 */

import { describe, expect, it } from "vitest";

import {
  appEmbeds,
  declaredEmbeds,
  embedAllow,
  guildAppPath,
  initiativeAppPath,
  placedIn,
  type SurfaceAccess,
} from "./appSurfaces";

const embed = (id: string, scopes?: string[], adminOnly?: boolean) => ({
  id,
  path: `/embed/${id}`,
  name: { en: id },
  ...(scopes ? { scopes } : {}),
  ...(adminOnly !== undefined ? { admin_only: adminOnly } : {}),
});

const access = (
  surface_id: string,
  openable_guild_wide: boolean,
  openable_initiatives: number[] = []
): SurfaceAccess => ({ surface_id, openable_guild_wide, openable_initiatives });

describe("embedAllow", () => {
  it("grants a surface exactly what it asked for", () => {
    expect(embedAllow({ capabilities: ["clipboard-write", "fullscreen"] })).toBe(
      "clipboard-write; fullscreen"
    );
  });

  it("grants nothing to a surface that asked for nothing", () => {
    expect(embedAllow({ capabilities: [] })).toBe("");
  });

  it("grants nothing to a definition pinned before surfaces could ask", () => {
    expect(embedAllow({})).toBe("");
  });

  it("grants nothing when there is no surface open", () => {
    expect(embedAllow(null)).toBe("");
  });
});

describe("declaredEmbeds", () => {
  it("reads a surface that says nothing as guild-wide", () => {
    const definition = { embeds: [embed("board")] };
    expect(declaredEmbeds(definition, "guild").map((e) => e.id)).toEqual(["board"]);
    expect(declaredEmbeds(definition, "initiative")).toEqual([]);
  });

  it("offers a surface in both places when it asked for both", () => {
    const definition = { embeds: [embed("runs", ["guild", "initiative"])] };
    expect(declaredEmbeds(definition, "guild").map((e) => e.id)).toEqual(["runs"]);
    expect(declaredEmbeds(definition, "initiative").map((e) => e.id)).toEqual(["runs"]);
  });

  it("ignores entries that are not surfaces", () => {
    const definition = { embeds: [{ id: "no-path" }, null, "board", embed("real")] };
    expect(declaredEmbeds(definition, "guild").map((e) => e.id)).toEqual(["real"]);
  });

  it("has nothing when the app declares no embeds", () => {
    expect(declaredEmbeds({}, "guild")).toEqual([]);
    expect(declaredEmbeds(null, "guild")).toEqual([]);
  });
});

describe("appEmbeds", () => {
  it("offers a guild-wide surface only where the server says it opens", () => {
    const definition = { embeds: [embed("board")] };
    expect(
      appEmbeds({ definition, surface_access: [access("board", true)] }).map((e) => e.id)
    ).toEqual(["board"]);
    expect(appEmbeds({ definition, surface_access: [access("board", false)] })).toEqual([]);
  });

  it("offers an initiative surface in the initiatives the server listed", () => {
    const definition = { embeds: [embed("runs", ["guild", "initiative"])] };
    const app = { definition, surface_access: [access("runs", false, [4])] };
    expect(appEmbeds(app, 4).map((e) => e.id)).toEqual(["runs"]);
    expect(appEmbeds(app, 5)).toEqual([]);
    expect(appEmbeds(app)).toEqual([]);
  });

  it("keeps an initiative-only surface off the guild page", () => {
    // Even if an answer said otherwise, the surface never asked to render there.
    const definition = { embeds: [embed("runs", ["initiative"])] };
    const app = { definition, surface_access: [access("runs", true, [4])] };
    expect(appEmbeds(app)).toEqual([]);
    expect(appEmbeds(app, 4).map((e) => e.id)).toEqual(["runs"]);
  });

  it("offers nothing the server gave no answer for", () => {
    const definition = { embeds: [embed("board")] };
    expect(appEmbeds({ definition })).toEqual([]);
    expect(appEmbeds({ definition, surface_access: null })).toEqual([]);
    expect(appEmbeds(null)).toEqual([]);
  });
});

describe("guildAppPath", () => {
  it("gives an app with a surface this reader opens a page", () => {
    expect(
      guildAppPath({
        id: 7,
        definition: { embeds: [embed("board")] },
        surface_access: [access("board", true)],
      })
    ).toBe("/apps/7");
  });

  it("gives a reader no page when no surface opens for them", () => {
    expect(
      guildAppPath({
        id: 7,
        definition: { embeds: [embed("console", ["guild"], true)] },
        surface_access: [access("console", false)],
      })
    ).toBeNull();
  });

  it("gives an app with only initiative surfaces no guild page", () => {
    expect(
      guildAppPath({
        id: 7,
        definition: { embeds: [embed("runs", ["initiative"])] },
        surface_access: [access("runs", false, [4])],
      })
    ).toBeNull();
  });

  it("sends a tool-instance app to the tool it mounted", () => {
    expect(
      guildAppPath({ id: 7, tool: "calendar", artifacts: [{ type: "calendar", id: 3 }] })
    ).toBe("/calendars");
  });

  it("sends it to the list rather than to one of them", () => {
    // A member may add calendars to the app, so its home is everything it
    // holds — the same address whether that is one calendar or six.
    const app = {
      id: 7,
      tool: "calendar",
      artifacts: [
        { type: "calendar", id: 3 },
        { type: "calendar", id: 4 },
      ],
    };
    expect(guildAppPath(app)).toBe("/calendars");
  });
});

describe("initiativeAppPath", () => {
  const app = (openIn: number[]) => ({
    id: 7,
    definition: { embeds: [embed("runs", ["initiative"])] },
    placements: [{ initiative_id: 4 }],
    surface_access: [access("runs", false, openIn)],
  });

  it("gives a row where the server says the reader opens a surface", () => {
    expect(initiativeAppPath(app([4]), 4)).toBe("/i/4/apps/7");
    expect(initiativeAppPath(app([]), 4)).toBeNull();
  });

  it("gives no row to an app with only a guild-wide surface", () => {
    expect(
      initiativeAppPath(
        {
          id: 7,
          definition: { embeds: [embed("board")] },
          placements: [{ initiative_id: 4 }],
          surface_access: [access("board", true)],
        },
        4
      )
    ).toBeNull();
  });

  it("gives a tool-instance app no row of its own", () => {
    // The tool it mounted already lives in an initiative.
    expect(
      initiativeAppPath({ id: 7, tool: "calendar", artifacts: [{ type: "calendar", id: 3 }] }, 4)
    ).toBeNull();
  });
});

describe("placedIn", () => {
  it("offers an app placed nowhere in no initiative", () => {
    expect(placedIn({ placements: [] }, 4)).toBe(false);
    expect(placedIn({ placements: null }, 4)).toBe(false);
    expect(placedIn({}, 4)).toBe(false);
  });

  it("offers a placed app only where it was placed", () => {
    const app = { placements: [{ initiative_id: 4 }, { initiative_id: 9 }] };
    expect(placedIn(app, 4)).toBe(true);
    expect(placedIn(app, 5)).toBe(false);
  });

  it("keeps a row out of an initiative the app was placed away from", () => {
    // Placement is where the app goes, so it reads the same for an admin.
    const app = {
      id: 7,
      placements: [{ initiative_id: 9 }],
      definition: {
        embeds: [{ id: "runs", path: "/embed", name: { en: "Runs" }, scopes: ["initiative"] }],
      },
      surface_access: [access("runs", false, [9])],
    };
    expect(initiativeAppPath(app, 9)).toBe("/i/9/apps/7");
    expect(initiativeAppPath(app, 4)).toBeNull();
  });
});
