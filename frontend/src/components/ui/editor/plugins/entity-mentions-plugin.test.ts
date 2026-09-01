import { describe, expect, it } from "vitest";

import { ENTITY_TRIGGER } from "@/lib/mentions";

import { entityMatch } from "./entity-mentions-plugin";

describe("what a # in a document matches", () => {
  it("triggers on # and leaves @ to the people plugin", () => {
    expect(entityMatch("see #ven")).not.toBeNull();
    expect(entityMatch("see @al")).toBeNull();
  });

  it("hands back the whole trigger to replace, so no # is left behind", () => {
    const match = entityMatch("see #ven");
    expect(match?.replaceableString).toBe("#ven");
  });

  it("keeps the type word, which is what narrowing is read from", () => {
    const match = entityMatch("see #task:ven");
    expect(match?.matchingString).toBe("task:ven");
    expect(match?.replaceableString).toBe(`${ENTITY_TRIGGER}task:ven`);
  });

  it("does not trigger mid-word", () => {
    expect(entityMatch("issue#42")).toBeNull();
  });

  it("offers as soon as the trigger is typed, before any letters", () => {
    expect(entityMatch("see #")?.matchingString).toBe("");
  });
});
