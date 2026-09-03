import { describe, expect, it } from "vitest";

import { guildHomeRedirectSearch } from "./index";

describe("the retired initiatives list route", () => {
  it("carries a create deep link across to the guild home", () => {
    // Old sidebar links and notifications still point here with ?create=true.
    expect(guildHomeRedirectSearch({ create: "true" })).toEqual({ create: "true" });
  });

  it("forwards nothing it wasn't given", () => {
    expect(guildHomeRedirectSearch({})).toEqual({});
    expect(guildHomeRedirectSearch({ create: "false" })).toEqual({});
  });
});
