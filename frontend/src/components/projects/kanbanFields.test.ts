import { describe, expect, it } from "vitest";

import type { PropertyDefinitionRead } from "@/api/generated/initiativeAPI.schemas";
import {
  buildKanbanCardFields,
  isKanbanFieldVisible,
  KANBAN_FIELD_IDS,
  kanbanFieldOptions,
  kanbanFieldsStorageKey,
} from "@/components/projects/kanbanFields";

const definition = (id: number, name: string): PropertyDefinitionRead =>
  ({ id, name, type: "text" }) as PropertyDefinitionRead;

const translate = (key: string) => key;

describe("isKanbanFieldVisible", () => {
  it("shows anything the reader has not turned off", () => {
    // The default has to be "shown": a board nobody has configured must look
    // exactly as it did before the menu existed.
    expect(isKanbanFieldVisible({}, "priority")).toBe(true);
    expect(isKanbanFieldVisible({ priority: true }, "priority")).toBe(true);
    expect(isKanbanFieldVisible({ tags: false }, "priority")).toBe(true);
  });

  it("hides only what is explicitly off", () => {
    expect(isKanbanFieldVisible({ priority: false }, "priority")).toBe(false);
  });
});

describe("kanbanFieldOptions", () => {
  it("offers every built-in field, and not the title", () => {
    const ids = kanbanFieldOptions([], translate).map((option) => option.id);

    expect(ids).toEqual([...KANBAN_FIELD_IDS]);
    // A card with no title is not a card, so it is never offered.
    expect(ids).not.toContain("title");
  });

  it("appends one entry per property, labelled by name", () => {
    const options = kanbanFieldOptions([definition(4, "Effort")], translate);

    expect(options.at(-1)).toMatchObject({
      id: "property:Effort",
      label: "Effort",
      definitionId: 4,
    });
  });

  it("keeps two properties of the same name apart", () => {
    const options = kanbanFieldOptions(
      [definition(4, "Status"), definition(9, "Status")],
      translate
    );
    const ids = options.slice(-2).map((option) => option.id);

    expect(new Set(ids).size).toBe(2);
    expect(ids).toEqual(["property:Status (#4)", "property:Status (#9)"]);
  });
});

describe("buildKanbanCardFields", () => {
  it("answers for built-in fields", () => {
    const fields = buildKanbanCardFields({ priority: false }, []);

    expect(fields.shows("priority")).toBe(false);
    expect(fields.shows("tags")).toBe(true);
  });

  it("resolves a property by id, not by name", () => {
    const definitions = [definition(4, "Effort")];
    const fields = buildKanbanCardFields({ "property:Effort": false }, definitions);

    expect(fields.showsProperty(4)).toBe(false);
    expect(fields.showsProperty(5)).toBe(true);
  });

  it("hides one of two same-named properties without touching the other", () => {
    // The reason `showsProperty` takes an id: a card holds a summary carrying
    // the name, and the `(#id)` suffix the menu used depends on the whole
    // definition list, which no single card can see.
    const definitions = [definition(4, "Status"), definition(9, "Status")];
    const fields = buildKanbanCardFields({ "property:Status (#9)": false }, definitions);

    expect(fields.showsProperty(4)).toBe(true);
    expect(fields.showsProperty(9)).toBe(false);
  });

  it("shows a property whose definition arrives after the choices were saved", () => {
    const fields = buildKanbanCardFields({ "property:Effort": false }, []);

    expect(fields.showsProperty(4)).toBe(true);
  });
});

describe("kanbanFieldsStorageKey", () => {
  it("is per project, so two boards keep separate choices", () => {
    expect(kanbanFieldsStorageKey(1)).not.toBe(kanbanFieldsStorageKey(2));
  });
});
