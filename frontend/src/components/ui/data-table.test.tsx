import type { ColumnDef } from "@tanstack/react-table";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { DataTable } from "./data-table";

interface Row {
  id: number;
  name: string;
}

const columns: ColumnDef<Row>[] = [
  {
    accessorKey: "name",
    header: "Name",
    cell: ({ row }) => row.original.name,
  },
];

const rows: Row[] = [
  { id: 1, name: "Alpha" },
  { id: 2, name: "Bravo" },
  { id: 3, name: "Charlie" },
  { id: 4, name: "Delta" },
  { id: 5, name: "Echo" },
];

/** Renders the table and exposes the latest reported selection via a data attr. */
function Harness({ data = rows }: { data?: Row[] }) {
  const [selected, setSelected] = useState<Row[]>([]);
  return (
    <div>
      <div data-testid="selection">{selected.map((r) => r.id).join(",")}</div>
      <DataTable
        columns={columns}
        data={data}
        enableRowSelection
        enableFilterInput
        getRowId={(row) => String(row.id)}
        onRowSelectionChange={setSelected}
      />
    </div>
  );
}

const reported = () => screen.getByTestId("selection").textContent;

/** Enter selection mode and return the per-row selection checkboxes in DOM order. */
async function enterSelectionMode(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Select" }));
  return () => screen.getAllByRole("checkbox", { name: "Select row" });
}

describe("DataTable row selection", () => {
  it("shift+clicking selects the inclusive range in displayed order", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const getCheckboxes = await enterSelectionMode(user);

    // Anchor on row 2 (Bravo)...
    await user.click(getCheckboxes()[1]);
    expect(reported()).toBe("2");

    // ...then shift+click row 4 (Delta) → selects 2,3,4 inclusive.
    await user.keyboard("{Shift>}");
    await user.click(getCheckboxes()[3]);
    await user.keyboard("{/Shift}");

    expect(reported()).toBe("2,3,4");
  });

  it("shift+click after select-all does not range from a stale anchor", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const getCheckboxes = await enterSelectionMode(user);

    // Establish an anchor on row 1, then select-all + deselect-all. Select-all
    // clears the anchor, leaving an empty selection and no anchor.
    await user.click(getCheckboxes()[0]);
    const selectAll = screen.getByRole("checkbox", { name: "Select all" });
    await user.click(selectAll);
    expect(reported()).toBe("1,2,3,4,5");
    await user.click(selectAll);
    expect(reported()).toBe("");

    // A shift+click now behaves as a fresh single toggle. If the row-1 anchor had
    // leaked, this would range-select 1..4; instead only row 4 is selected.
    await user.keyboard("{Shift>}");
    await user.click(getCheckboxes()[3]);
    await user.keyboard("{/Shift}");

    expect(reported()).toBe("4");
  });

  it("keeps selection consistent across filtering (filter out, select more, clear)", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const getCheckboxes = await enterSelectionMode(user);

    // Select Alpha + Bravo.
    await user.click(getCheckboxes()[0]);
    await user.click(getCheckboxes()[1]);
    expect(reported()).toBe("1,2");

    // Filter to hide the selected rows (show only Echo).
    const filter = screen.getByPlaceholderText("Filter...");
    await user.type(filter, "Echo");

    // Only Echo is visible now; select it.
    const visible = screen.getAllByRole("checkbox", { name: "Select row" });
    expect(visible).toHaveLength(1);
    await user.click(visible[0]);

    // Selection persists across the filter: all three reported, not just Echo.
    expect(reported()).toBe("1,2,5");

    // Clear the filter → checkboxes and reported selection stay in sync.
    await user.clear(filter);
    const all = screen.getAllByRole("checkbox", { name: "Select row" });
    const checkedIds = rows
      .filter((_, i) => (all[i] as HTMLElement).getAttribute("data-state") === "checked")
      .map((r) => r.id);
    expect(checkedIds).toEqual([1, 2, 5]);
    expect(reported()).toBe("1,2,5");
  });

  it("shows a filter-aware count when selected rows are hidden by the filter", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const getCheckboxes = await enterSelectionMode(user);

    await user.click(getCheckboxes()[0]);
    await user.click(getCheckboxes()[1]);

    const filter = screen.getByPlaceholderText("Filter...");
    await user.type(filter, "Echo");

    // 2 selected, both hidden, 1 row matches the filter → filtered-variant message.
    expect(screen.getByText("2 selected (1 match filter)")).toBeInTheDocument();
  });

  it("uses the filter-aware count even when selected <= filtered total", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const getCheckboxes = await enterSelectionMode(user);

    // Select Alpha + Bravo (2 selected).
    await user.click(getCheckboxes()[0]);
    await user.click(getCheckboxes()[1]);

    // Filter to show Charlie/Delta/Echo (3 visible) — none of them are selected.
    // selected (2) <= filteredTotal (3), but both selected rows are hidden, so the
    // plain "2 of 3 selected" would be misleading. Expect the filtered variant.
    const filter = screen.getByPlaceholderText("Filter...");
    await user.type(filter, "e");

    expect(screen.getByText("2 selected (3 match filter)")).toBeInTheDocument();
    expect(screen.queryByText("2 of 3 row(s) selected")).not.toBeInTheDocument();
  });
});

/**
 * A row fanned out over a multi-valued field: the project task table groups by
 * tag this way, emitting one row per (task, tag) pair so a row shows up under
 * every value it carries.
 */
interface FannedRow extends Row {
  group?: string;
}

const fannedColumns: ColumnDef<FannedRow>[] = [
  { accessorKey: "name", header: "Name", cell: ({ row }) => row.original.name },
  {
    id: "group",
    accessorFn: (row) => row.group ?? "Ungrouped",
    header: "Group",
    cell: ({ getValue }) => getValue<string>(),
    enableHiding: false,
  },
];

const fannedRows: FannedRow[] = [
  { id: 1, name: "Alpha", group: "bug" },
  { id: 1, name: "Alpha", group: "urgent" },
  { id: 2, name: "Bravo", group: "bug" },
  { id: 3, name: "Charlie" },
];

/** The same rows unfanned, as a consumer would pass them when not grouping. */
const plainRows: FannedRow[] = [
  { id: 1, name: "Alpha" },
  { id: 2, name: "Bravo" },
  { id: 3, name: "Charlie" },
];

const fannedRowId = (row: FannedRow) => (row.group ? `${row.id}::${row.group}` : String(row.id));

/** Renders the grouped table, with a button that re-shapes the data in place. */
function GroupedHarness() {
  const [fanned, setFanned] = useState(true);
  const [selected, setSelected] = useState<FannedRow[]>([]);
  const data = fanned ? fannedRows : plainRows;
  return (
    <div>
      <button type="button" onClick={() => setFanned((previous) => !previous)}>
        Reshape
      </button>
      <div data-testid="selection">{selected.map((r) => fannedRowId(r)).join(",")}</div>
      <DataTable
        columns={fannedColumns}
        data={data}
        enableRowSelection
        getRowId={fannedRowId}
        groupingOptions={[{ id: "group", label: "Group" }]}
        columnVisibility={{ group: false }}
        initialState={{ grouping: ["group"] }}
        onRowSelectionChange={setSelected}
      />
    </div>
  );
}

describe("DataTable grouping", () => {
  it("groups on a hidden column, listing a fanned-out row under each of its groups", () => {
    render(<GroupedHarness />);

    // The grouping column drives the group headers without becoming a column.
    expect(screen.queryByRole("columnheader", { name: "Group" })).not.toBeInTheDocument();
    const groupHeaders = screen
      .getAllByRole("row")
      .filter((row) => row.getAttribute("data-state") === "grouped")
      .map((row) => row.textContent);
    expect(groupHeaders).toEqual(["Ungrouped", "bug", "urgent"]);

    // Alpha carries two groups, so it appears under both.
    expect(screen.getAllByText("Alpha")).toHaveLength(2);
    expect(screen.getAllByText("Bravo")).toHaveLength(1);
  });

  it("re-reports the selection when the data is re-shaped under it", async () => {
    const user = userEvent.setup();
    render(<GroupedHarness />);
    const getCheckboxes = await enterSelectionMode(user);

    // Rows read Ungrouped (Charlie), bug (Alpha, Bravo), urgent (Alpha) — pick
    // Alpha's row in the "bug" group.
    await user.click(getCheckboxes()[1]);
    expect(reported()).toBe("1::bug");

    // Re-shaping the rows re-keys them, so nothing is checked any more — the
    // reported selection has to follow rather than keep the stale row.
    await user.click(screen.getByRole("button", { name: "Reshape" }));
    expect(reported()).toBe("");
  });

  it("does not bring a selection back when the original row keys return", async () => {
    const user = userEvent.setup();
    render(<GroupedHarness />);
    const getCheckboxes = await enterSelectionMode(user);

    await user.click(getCheckboxes()[1]);
    const reshape = screen.getByRole("button", { name: "Reshape" });

    // Away from the fanned shape the selected id no longer exists...
    await user.click(reshape);
    expect(reported()).toBe("");

    // ...and back in it, the row must stay unchecked rather than re-select
    // itself off a selection id nothing reported any more.
    await user.click(reshape);
    expect(reported()).toBe("");
    const checked = getCheckboxes().filter((box) => box.getAttribute("data-state") === "checked");
    expect(checked).toHaveLength(0);
  });
});
