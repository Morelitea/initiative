import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buildPropertyDefinition, buildPropertySummary, buildTask } from "@/__tests__/factories";
import i18n from "@/__tests__/helpers/i18n-test";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { PropertyDefinitionRead, TaskListRead } from "@/api/generated/initiativeAPI.schemas";
import { taskFields } from "@/lib/views/tasks";
import { type ViewContext, type ViewNode, ViewTree } from "@/lib/views/tree";
import type { TranslateFn } from "@/types/i18n";

const field = (id: string): ViewNode => ({ type: "field", props: { field: id } });

const draw = (
  node: ViewNode,
  task: TaskListRead,
  hidden: string[] = [],
  definitions: PropertyDefinitionRead[] = []
) => {
  const view: ViewContext = {
    fields: taskFields(definitions),
    variant: "card",
    isHidden: (fieldId) => hidden.includes(fieldId),
    env: {
      t: i18n.getFixedT(null, ["projects", "dates", "relations"]) as TranslateFn,
      communityPath: (path) => path,
      taskHref: (taskId) => `/tasks/${taskId}`,
    },
  };
  return renderWithProviders(<ViewTree node={node} item={task} view={view} />);
};

describe("taskFields", () => {
  it("adds one field per property, labelled by name", () => {
    const fields = taskFields([buildPropertyDefinition({ id: 4, name: "Effort" })]);

    expect(fields.get("property:Effort")).toMatchObject({ label: "Effort", source: "property" });
  });

  it("keeps two properties of the same name apart", () => {
    const fields = taskFields([
      buildPropertyDefinition({ id: 4, name: "Status" }),
      buildPropertyDefinition({ id: 9, name: "Status" }),
    ]);

    expect([...fields.keys()].slice(-2)).toEqual(["property:Status (#4)", "property:Status (#9)"]);
  });
});

describe("ViewTree", () => {
  it("draws nothing for a part or a field it does not know", () => {
    const node: ViewNode = {
      type: "stack",
      children: [{ type: "nope" }, { type: "constructor" }, field("nope"), field("priority")],
    };

    draw(node, buildTask({ priority: "medium" }));

    expect(screen.getByText(/priority: medium/i)).toBeInTheDocument();
  });

  it("skips a hidden field and one with nothing in it", () => {
    const node: ViewNode = {
      type: "stack",
      children: [field("priority"), field("description"), field("comments"), field("dueDate")],
    };
    const task = buildTask({
      description_excerpt: null,
      comment_count: 0,
      due_date: "2026-08-03T21:15:00Z",
    });

    const { container } = draw(node, task, ["priority"]);

    expect(container.textContent).toMatch(/^Due:/);
  });

  it("draws the item's properties in its order, each hidden by its own field", () => {
    // Two that share a name are turned off separately, and one whose
    // definition has not arrived is still drawn.
    const definitions = [
      buildPropertyDefinition({ id: 9, name: "Status" }),
      buildPropertyDefinition({ id: 4, name: "Effort" }),
      buildPropertyDefinition({ id: 12, name: "Status" }),
      buildPropertyDefinition({ id: 15, name: "Owner" }),
    ];
    const task = buildTask({
      properties: [
        buildPropertySummary({ property_id: 4, name: "Effort", value: "large" }),
        buildPropertySummary({ property_id: 15, name: "Owner", value: "" }),
        buildPropertySummary({ property_id: 9, name: "Status", value: "open" }),
        buildPropertySummary({ property_id: 12, name: "Status", value: "shut" }),
        buildPropertySummary({ property_id: 20, name: "Phase", value: "beta" }),
      ],
    });

    const { container } = draw(
      { type: "properties" },
      task,
      ["property:Status (#12)"],
      definitions
    );

    expect(container.textContent).toBe("Effort:largeStatus:openPhase:beta");
  });
});
