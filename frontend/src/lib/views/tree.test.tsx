import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buildPropertyDefinition, buildPropertySummary, buildTask } from "@/__tests__/factories";
import i18n from "@/__tests__/helpers/i18n-test";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { PropertyDefinitionRead, TaskListRead } from "@/api/generated/initiativeAPI.schemas";
import { taskFields } from "@/lib/views/tasks";
import {
  LAYOUT_PARTS,
  type Parts,
  renderNode,
  type ViewContext,
  type ViewNode,
  ViewTree,
} from "@/lib/views/tree";
import type { TranslateFn } from "@/types/i18n";

const field = (id: string): ViewNode => ({ type: "field", props: { field: id } });

const viewOf = (
  hidden: string[] = [],
  definitions: PropertyDefinitionRead[] = [],
  variant: ViewContext["variant"] = "card"
): ViewContext => ({
  fields: taskFields(definitions),
  variant,
  isHidden: (fieldId) => hidden.includes(fieldId),
  env: {
    t: i18n.getFixedT(null, ["projects", "dates", "relations"]) as TranslateFn,
    communityPath: (path) => path,
    taskHref: (task) => `/tasks/${task.id}`,
  },
});

const draw = (
  node: ViewNode,
  task: TaskListRead,
  hidden: string[] = [],
  definitions: PropertyDefinitionRead[] = []
) => renderWithProviders(<ViewTree node={node} item={task} view={viewOf(hidden, definitions)} />);

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

  it("draws a property a stored view names by its definition id", () => {
    const task = buildTask({
      properties: [buildPropertySummary({ property_id: 4, name: "Effort", value: "large" })],
    });

    const { container } = draw(
      field("property:4"),
      task,
      [],
      [buildPropertyDefinition({ id: 4, name: "Effort" })]
    );

    expect(container.textContent).toBe("Effort:large");
  });
});

describe("renderNode", () => {
  it("draws an item's page through the parts it is given", () => {
    // The page's regions are layout any kind of item shares; what fills them
    // is the item's own.
    const parts: Parts<string> = { ...LAYOUT_PARTS, name: (_node, item) => <p>{item}</p> };
    const page: ViewNode = {
      type: "page",
      children: [
        { type: "header", children: [{ type: "name" }] },
        { type: "main", children: [{ type: "field", props: { field: "title" } }] },
        { type: "side", children: [{ type: "name" }] },
      ],
    };

    const { container } = renderWithProviders(
      <>{renderNode(page, "Ada", viewOf([], [], "page"), parts)}</>
    );

    expect(container.textContent).toBe("AdaAda");
  });
});
