/**
 * A configured value has to be the type its app declared.
 *
 * The failure this exists to stop is quiet and late: every control reads a
 * string, the binding stores that string, the dashboard saves — and the tile
 * fails with `INVALID_PARAMS` the first time it is drawn, because the proxy
 * holds an `int` parameter to an actual integer, and holds every entry of a
 * `list` one to the same rule.
 */
import { describe, expect, it } from "vitest";

import { asControlValue, asDeclaredList, asDeclaredType } from "./appParams";

const int = { type: "int" };
const text = { type: "string" };
const flag = { type: "bool" };

describe("asDeclaredType", () => {
  it("makes a number of what a control read as a string", () => {
    expect(asDeclaredType(int, "7")).toBe(7);
    expect(asDeclaredType({ type: "number" }, "7.5")).toBe(7.5);
  });

  it("leaves a string a string", () => {
    expect(asDeclaredType(text, "widgets")).toBe("widgets");
    expect(asDeclaredType({ type: "select" }, "open")).toBe("open");
  });

  it("reads the two words a bool has", () => {
    expect(asDeclaredType(flag, "true")).toBe(true);
    expect(asDeclaredType(flag, "false")).toBe(false);
    expect(asDeclaredType(flag, "yes")).toBeUndefined();
  });

  it("refuses a number that is not the integer it was declared to be", () => {
    // The proxy refuses it too, so accepting it here would only move the
    // failure to the fetch — which is the part nobody is watching.
    expect(asDeclaredType(int, "1.5")).toBeUndefined();
    expect(asDeclaredType(int, "twelve")).toBeUndefined();
  });

  it("has no answer for an emptied field", () => {
    // Which is how the caller knows to drop the key rather than send "".
    expect(asDeclaredType(text, "")).toBeUndefined();
    expect(asDeclaredType(text, "   ")).toBeUndefined();
    expect(asDeclaredType(int, "")).toBeUndefined();
  });

  it("trims, because a menu's value and a typed one must agree", () => {
    expect(asDeclaredType(text, "  bug  ")).toBe("bug");
    expect(asDeclaredType(int, " 7 ")).toBe(7);
  });
});

describe("asDeclaredList", () => {
  it("holds every entry to the type, not just the first", () => {
    expect(asDeclaredList(int, ["1", "2", "3"])).toEqual([1, 2, 3]);
    expect(asDeclaredList(text, ["bug", "regression"])).toEqual(["bug", "regression"]);
  });

  it("keeps the order the app answered in", () => {
    expect(asDeclaredList(text, ["south", "north"])).toEqual(["south", "north"]);
  });

  it("drops an entry that is not a value of that type", () => {
    expect(asDeclaredList(int, ["1", "nope", "3"])).toEqual([1, 3]);
    expect(asDeclaredList(text, ["bug", "  ", "fix"])).toEqual(["bug", "fix"]);
  });

  it("has nothing to send when nothing survives", () => {
    // An empty array is what the dialog reads as "no answer", so the key is
    // dropped rather than sent — which is also what the proxy requires.
    expect(asDeclaredList(int, ["x"])).toEqual([]);
    expect(asDeclaredList(text, [])).toEqual([]);
  });
});

describe("asControlValue", () => {
  it("renders a stored value as the string a control shows", () => {
    expect(asControlValue(7)).toBe("7");
    expect(asControlValue("bug")).toBe("bug");
    expect(asControlValue(true)).toBe("true");
  });

  it("shows nothing for no answer", () => {
    expect(asControlValue(undefined)).toBe("");
    expect(asControlValue(null)).toBe("");
  });

  it("round-trips a number through a menu's string value", () => {
    // The whole point: an option's value is a string, the binding holds an int,
    // and the control has to find its own option again afterwards.
    expect(asControlValue(asDeclaredType(int, "7"))).toBe("7");
  });
});
