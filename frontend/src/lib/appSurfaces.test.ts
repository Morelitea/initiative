/**
 * Which surfaces belong where, and which are worth offering to whom.
 *
 * Two readings that are easy to get wrong. A definition pinned before surfaces
 * could say where they belong carries no scopes, and every one of those is
 * guild-wide — getting that wrong would empty the app pages of every install
 * that predates it. And a rung is read against *where* a surface was opened, so
 * one declaration deliberately admits different people in each place.
 */

import { describe, expect, it } from "vitest";

import {
  appEmbeds,
  clearsVisibility,
  embedAllow,
  guildAppPath,
  initiativeAppPath,
  placedIn,
} from "./appSurfaces";

const ADMIN = { isGuildAdmin: true };
const MANAGER = { isGuildAdmin: false, isInitiativeManager: true };
const MEMBER = { isGuildAdmin: false };

const embed = (id: string, scopes?: string[], visibility?: string) => ({
  id,
  path: `/embed/${id}`,
  name: { en: id },
  ...(scopes ? { scopes } : {}),
  ...(visibility ? { visibility } : {}),
});

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

describe("clearsVisibility", () => {
  it("lets a guild admin past every rung", () => {
    for (const rung of [undefined, "member", "initiative_manager", "guild_admin"]) {
      expect(clearsVisibility(rung, ADMIN)).toBe(true);
    }
  });

  it("reads the manager rung against the reader's own standing", () => {
    expect(clearsVisibility("initiative_manager", MANAGER)).toBe(true);
    expect(clearsVisibility("initiative_manager", MEMBER)).toBe(false);
  });

  it("keeps a manager off the rung above them", () => {
    expect(clearsVisibility("guild_admin", MANAGER)).toBe(false);
  });

  it("admits everyone where nothing was named", () => {
    expect(clearsVisibility(undefined, MEMBER)).toBe(true);
    expect(clearsVisibility("member", MEMBER)).toBe(true);
  });

  it("does not offer a rung it cannot read", () => {
    expect(clearsVisibility("everyone", MEMBER)).toBe(false);
  });
});

describe("appEmbeds", () => {
  it("reads a surface that says nothing as guild-wide", () => {
    const definition = { embeds: [embed("board")] };
    expect(appEmbeds(definition, "guild", MEMBER).map((e) => e.id)).toEqual(["board"]);
    expect(appEmbeds(definition, "initiative", MEMBER)).toEqual([]);
  });

  it("offers a surface in both places when it asked for both", () => {
    const definition = { embeds: [embed("runs", ["guild", "initiative"])] };
    expect(appEmbeds(definition, "guild", MEMBER).map((e) => e.id)).toEqual(["runs"]);
    expect(appEmbeds(definition, "initiative", MEMBER).map((e) => e.id)).toEqual(["runs"]);
  });

  it("keeps an initiative-only surface off the guild page", () => {
    const definition = { embeds: [embed("runs", ["initiative"])] };
    expect(appEmbeds(definition, "guild", ADMIN)).toEqual([]);
    expect(appEmbeds(definition, "initiative", ADMIN).map((e) => e.id)).toEqual(["runs"]);
  });

  it("offers one declaration to different people in each place", () => {
    // The automation shape: managers inside their initiative, admins guild-wide.
    const definition = {
      embeds: [embed("runs", ["guild", "initiative"], "initiative_manager")],
    };
    expect(appEmbeds(definition, "initiative", MANAGER).map((e) => e.id)).toEqual(["runs"]);
    // Still described as a manager, but guild-wide there is nothing to manage,
    // so the rung falls through to the admins — the mint reads it the same way.
    expect(appEmbeds(definition, "guild", MANAGER)).toEqual([]);
    expect(appEmbeds(definition, "guild", ADMIN).map((e) => e.id)).toEqual(["runs"]);
    expect(appEmbeds(definition, "initiative", MEMBER)).toEqual([]);
  });

  it("does not offer a member an admin surface", () => {
    const definition = { embeds: [embed("console", ["guild"], "guild_admin")] };
    expect(appEmbeds(definition, "guild", MEMBER)).toEqual([]);
    expect(appEmbeds(definition, "guild", ADMIN).map((e) => e.id)).toEqual(["console"]);
  });

  it("ignores entries that are not surfaces", () => {
    const definition = { embeds: [{ id: "no-path" }, null, "board", embed("real")] };
    expect(appEmbeds(definition, "guild", MEMBER).map((e) => e.id)).toEqual(["real"]);
  });

  it("has nothing to offer when the app declares no embeds", () => {
    expect(appEmbeds({}, "guild", ADMIN)).toEqual([]);
    expect(appEmbeds(null, "guild", ADMIN)).toEqual([]);
  });
});

describe("guildAppPath", () => {
  it("gives an app with a guild-wide surface a page", () => {
    expect(guildAppPath({ id: 7, definition: { embeds: [embed("board")] } }, MEMBER)).toBe(
      "/apps/7"
    );
  });

  it("gives an app with only initiative surfaces no guild page", () => {
    expect(
      guildAppPath({ id: 7, definition: { embeds: [embed("runs", ["initiative"])] } }, ADMIN)
    ).toBeNull();
  });

  it("gives a member no page when every surface is for admins", () => {
    const app = {
      id: 7,
      definition: { embeds: [embed("console", ["guild"], "guild_admin")] },
    };
    expect(guildAppPath(app, MEMBER)).toBeNull();
    expect(guildAppPath(app, ADMIN)).toBe("/apps/7");
  });

  it("sends a tool-instance app to the tool it mounted", () => {
    expect(
      guildAppPath({ id: 7, tool: "calendar", artifacts: [{ type: "calendar", id: 3 }] }, MEMBER)
    ).toBe("/calendars/3");
  });
});

describe("initiativeAppPath", () => {
  const app = (embeds: ReturnType<typeof embed>[]) => ({ id: 7, definition: { embeds } });

  it("gives a manager a row inside their initiative", () => {
    const declaration = app([embed("runs", ["initiative"], "initiative_manager")]);
    expect(initiativeAppPath(declaration, 4, MANAGER)).toBe("/i/4/apps/7");
    expect(initiativeAppPath(declaration, 4, MEMBER)).toBeNull();
    expect(initiativeAppPath(declaration, 4, ADMIN)).toBe("/i/4/apps/7");
  });

  it("gives no row to an app with only a guild-wide surface", () => {
    expect(initiativeAppPath(app([embed("board")]), 4, ADMIN)).toBeNull();
  });

  it("gives a tool-instance app no row of its own", () => {
    // The tool it mounted already lives in an initiative.
    expect(
      initiativeAppPath(
        { id: 7, tool: "calendar", artifacts: [{ type: "calendar", id: 3 }] },
        4,
        ADMIN
      )
    ).toBeNull();
  });
});

describe("placedIn", () => {
  it("offers an unplaced app in every initiative", () => {
    expect(placedIn({ placement: {} }, 4)).toBe(true);
    expect(placedIn({ placement: null }, 4)).toBe(true);
    expect(placedIn({}, 4)).toBe(true);
  });

  it("offers a placed app only where it was placed", () => {
    expect(placedIn({ placement: { initiatives: [4, 9] } }, 4)).toBe(true);
    expect(placedIn({ placement: { initiatives: [4, 9] } }, 5)).toBe(false);
  });

  it("reads an empty choice as nowhere rather than everywhere", () => {
    // Distinct from `{}`: the guild kept the guild-wide surface and dropped
    // the per-initiative ones.
    expect(placedIn({ placement: { initiatives: [] } }, 4)).toBe(false);
  });

  it("keeps a row out of an initiative the app was placed away from", () => {
    // Placement is where the app goes, so it reads the same for an admin.
    const app = {
      id: 7,
      placement: { initiatives: [9] },
      definition: {
        embeds: [{ id: "runs", path: "/embed", name: { en: "Runs" }, scopes: ["initiative"] }],
      },
    };
    expect(initiativeAppPath(app, 9, ADMIN)).toBe("/i/9/apps/7");
    expect(initiativeAppPath(app, 4, ADMIN)).toBeNull();
    expect(initiativeAppPath(app, 4, MANAGER)).toBeNull();
  });
});
