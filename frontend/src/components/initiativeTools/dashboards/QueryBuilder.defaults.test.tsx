/**
 * What a new statement leaves out, and when it is decided again.
 *
 * Driven through the component's own props rather than its dataset picker: the
 * thing under test is when the conditions are seeded, and the picker does
 * nothing but hand back a spec with the new dataset and its filters cleared —
 * which is exactly what re-rendering with that spec does.
 */
import { render, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { QueryBuildRequest } from "@/api/generated/initiativeAPI.schemas";

import { QueryBuilder } from "./QueryBuilder";

const COUNT_ALL = { field: "*", aggregate: "count", alias: "count" };

const DEFAULTS: Record<string, { field: string; op: string; value: unknown }[]> = {
  tasks: [
    { field: "archived_at", op: "is_null", value: true },
    { field: "project.is_template", op: "eq", value: false },
  ],
  projects: [
    { field: "archived_at", op: "is_null", value: true },
    { field: "is_template", op: "eq", value: false },
  ],
  members: [],
};

beforeEach(() => {
  server.use(
    http.get("/api/v1/fields/:dataset", ({ params }) => {
      const dataset = String(params.dataset);
      return HttpResponse.json({
        dataset,
        fields: [
          {
            name: "title",
            type: "text",
            kind: "text",
            ops: ["eq"],
            multiple: false,
            sortable: true,
            options: [],
          },
        ],
        relations: [],
        default_filters: DEFAULTS[dataset] ?? [],
      });
    })
  );
});

const spec = (dataset: string): QueryBuildRequest =>
  ({ dataset, columns: [COUNT_ALL], where: [], group_by: [] }) as QueryBuildRequest;

/** The builder, re-rendered with whatever it last asked for — which is what
 *  the dialog around it does. */
function mount() {
  const onChange = vi.fn();
  const view = renderWithProviders(
    <QueryBuilder spec={spec("tasks")} onChange={onChange} initiativeId={7} />
  );
  const show = (next: QueryBuildRequest) =>
    view.rerender(<QueryBuilder spec={next} onChange={onChange} initiativeId={7} />);
  const seeded = () =>
    (onChange.mock.calls.at(-1)?.[0] as QueryBuildRequest | undefined)?.where?.map(
      (condition) => (condition as { field: string }).field
    );
  return { onChange, show, seeded };
}

describe("seeding a new statement", () => {
  it("leaves out archived work and templates", async () => {
    const { seeded } = mount();
    await waitFor(() => expect(seeded()).toEqual(["archived_at", "project.is_template"]));
  });

  it("seeds a dataset the author comes back to", async () => {
    // The bug this pins: choosing a dataset clears the filters, so a trip
    // through another dataset and back left a statement reporting on work
    // that is not live.
    const { show, seeded, onChange } = mount();
    await waitFor(() => expect(seeded()).toEqual(["archived_at", "project.is_template"]));

    show(spec("projects"));
    await waitFor(() => expect(seeded()).toEqual(["archived_at", "is_template"]));

    onChange.mockClear();
    show(spec("tasks"));
    await waitFor(() => expect(seeded()).toEqual(["archived_at", "project.is_template"]));
  });

  it("does not put back conditions the author deleted", async () => {
    // Removing them is how somebody asks about archived work, and the dataset
    // has not changed — so nothing seeds it again.
    const { show, onChange, seeded } = mount();
    await waitFor(() => expect(seeded()).toEqual(["archived_at", "project.is_template"]));

    onChange.mockClear();
    show(spec("tasks"));
    await new Promise((done) => setTimeout(done, 50));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("asks nothing of a dataset with neither lifecycle", async () => {
    const { show, onChange } = mount();
    onChange.mockClear();
    show(spec("members"));
    await new Promise((done) => setTimeout(done, 50));
    expect(onChange).not.toHaveBeenCalled();
  });
});
