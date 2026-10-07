/**
 * The filter's two choices: whether every row must match or any may, and
 * whether archived work and templates are left out, included, or all there is. The defaults are switches
 * so "any" never turns them into "archived or not".
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { FilterNode } from "@/lib/widgets/conditions";

import { FilterBuilder } from "./FilterBuilder";

const ARCHIVED = { field: "archived_at", op: "is_null", value: true } as FilterNode;
const TITLE_A = { field: "title", op: "ilike", value: "a" } as FilterNode;
const TITLE_B = { field: "title", op: "ilike", value: "b" } as FilterNode;

beforeEach(() => {
  server.use(
    http.get("/api/v1/fields/:dataset", ({ params }) =>
      HttpResponse.json({
        dataset: params.dataset,
        fields: [
          {
            name: "title",
            type: "text",
            kind: "text",
            ops: ["ilike"],
            multiple: false,
            sortable: true,
            options: [],
          },
        ],
        relations: [],
        default_filters: [ARCHIVED],
      })
    )
  );
});

const mount = (value: FilterNode[]) => {
  const onChange = vi.fn();
  renderWithProviders(
    <FilterBuilder value={value} onChange={onChange} initiativeId={1} dataset="tasks" />
  );
  return onChange;
};

describe("FilterBuilder", () => {
  it("reads one OR group as 'any' and keeps the default outside it", async () => {
    mount([ARCHIVED, { logic: "or", conditions: [TITLE_A, TITLE_B] }]);
    expect(await screen.findByRole("combobox", { name: /^archived$/i })).toHaveTextContent(
      /leave out/i
    );
    expect(screen.getByRole("combobox", { name: /match all or any/i })).toHaveTextContent(/any/i);
    expect(screen.getByText(/^or$/i)).toBeInTheDocument();
  });

  it("switches to 'any' by wrapping the rows, not the defaults", async () => {
    const onChange = mount([ARCHIVED, TITLE_A, TITLE_B]);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("combobox", { name: /match all or any/i }));
    await user.click(await screen.findByRole("option", { name: /^any$/i }));
    await waitFor(() =>
      expect(onChange).toHaveBeenLastCalledWith([
        ARCHIVED,
        { logic: "or", conditions: [TITLE_A, TITLE_B] },
      ])
    );
  });

  it("including archived work drops its condition", async () => {
    const onChange = mount([ARCHIVED, TITLE_A]);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("combobox", { name: /^archived$/i }));
    await user.click(await screen.findByRole("option", { name: /^include$/i }));
    expect(onChange).toHaveBeenLastCalledWith([TITLE_A]);
  });

  it("asks for only archived work with the same comparison flipped", async () => {
    const onChange = mount([ARCHIVED, TITLE_A]);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("combobox", { name: /^archived$/i }));
    await user.click(await screen.findByRole("option", { name: /^only$/i }));
    expect(onChange).toHaveBeenLastCalledWith([
      { field: "archived_at", op: "is_null", value: false },
      TITLE_A,
    ]);
  });

  it("reads 'only' back from a stored filter", async () => {
    mount([{ field: "archived_at", op: "is_null", value: false } as FilterNode]);
    expect(await screen.findByRole("combobox", { name: /^archived$/i })).toHaveTextContent(/only/i);
    expect(screen.queryByText(/no filters/i)).not.toBeInTheDocument();
  });
});
