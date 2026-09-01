import { describe, expect, it } from "vitest";

import { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import {
  activeMention,
  entityMentionSyntax,
  MENTIONABLE_TYPES,
  typeForTrigger,
  typeTrigger,
} from "@/lib/mentions";

describe("what can be mentioned", () => {
  it("reaches every kind of thing except what people said about them", () => {
    expect(MENTIONABLE_TYPES).toContain(SearchEntityType.queue);
    expect(MENTIONABLE_TYPES).toContain(SearchEntityType.calendar_event);
    expect(MENTIONABLE_TYPES).toContain(SearchEntityType.dashboard);
    expect(MENTIONABLE_TYPES).not.toContain(SearchEntityType.comment);
  });

  it("gives every kind a trigger word without one being written down", () => {
    for (const type of MENTIONABLE_TYPES) {
      expect(typeForTrigger(typeTrigger(type))).toBe(type);
    }
  });

  it("still reads the shorthand already sitting in stored comments", () => {
    expect(typeForTrigger("doc")).toBe(SearchEntityType.document);
  });
});

describe("the mention being typed", () => {
  it("offers everything after a bare #, and narrows once a type is named", () => {
    expect(activeMention("see #ven")).toMatchObject({ types: null, query: "ven" });
    expect(activeMention("see #task:ven")).toMatchObject({
      types: [SearchEntityType.task],
      query: "ven",
    });
  });

  it("narrows to a kind that had no trigger of its own before", () => {
    expect(activeMention("see #counter-group:q1")).toMatchObject({
      types: [SearchEntityType.counter_group],
      query: "q1",
    });
  });

  it("reads @ as people and # as things", () => {
    expect(activeMention("hi @al")?.user).toBe(true);
    expect(activeMention("hi #al")?.user).toBe(false);
  });

  it("is not triggered mid-word, so an email address stays an email address", () => {
    expect(activeMention("mail me at sam@example")).toBeNull();
  });

  it("covers the trigger, so replacing it leaves no stray # behind", () => {
    const active = activeMention("see #task:ven");
    expect("see #task:ven".slice(0, "see #task:ven".length - (active?.length ?? 0))).toBe("see ");
  });

  it("ignores a type word that names nothing", () => {
    expect(activeMention("see #nonsense:x")).toBeNull();
  });
});

describe("what gets written into the comment", () => {
  it("writes the kind's own name, so the renderer reads back what it wrote", () => {
    expect(entityMentionSyntax(SearchEntityType.queue, "Intake", 4)).toBe("#queue[Intake](4)");
    expect(entityMentionSyntax(SearchEntityType.counter_group, "Q1", 7)).toBe(
      "#counter-group[Q1](7)"
    );
  });
});
