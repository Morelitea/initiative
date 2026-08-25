import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { DataTable } from "@/components/ui/data-table";
import { usePersistedTableState } from "@/hooks/usePersistedTableState";
import { getItem, setItem } from "@/lib/storage";

const KEY = "test-table";

type Row = { id: number; name: string; team: string };

const data: Row[] = [
  { id: 1, name: "b", team: "red" },
  { id: 2, name: "a", team: "blue" },
];

const columns = [
  {
    id: "name",
    accessorKey: "name",
    header: ({ column }) => (
      <button type="button" onClick={() => column.toggleSorting(false)}>
        Name
      </button>
    ),
    cell: ({ row }) => row.original.name,
    enableSorting: true,
  },
  { id: "team", accessorKey: "team", header: "Team", cell: ({ row }) => row.original.team },
] as never;

/** Wired exactly the way a list wires it: stored state seeds, changes write. */
function Harness({ storageKey = KEY }: { storageKey?: string }) {
  const [tableState, { setGrouping, setSorting }] = usePersistedTableState(storageKey);
  return (
    <DataTable
      key={storageKey}
      columns={columns}
      data={data}
      enableFilterInput
      groupingOptions={[{ id: "team", label: "Team" }]}
      initialSorting={tableState.sorting}
      initialState={{ grouping: tableState.grouping }}
      onGroupingChange={setGrouping}
      onSortingChange={setSorting}
    />
  );
}

const stored = () => JSON.parse(getItem(KEY) ?? "null");

describe("usePersistedTableState", () => {
  it("remembers a grouping choice across a remount", async () => {
    const user = userEvent.setup();
    const first = render(<Harness />);

    await user.click(screen.getByRole("combobox", { name: /group by/i }));
    await user.click(screen.getByRole("option", { name: "Team" }));
    expect(stored().grouping).toEqual(["team"]);

    first.unmount();
    render(<Harness />);
    expect(screen.getByRole("combobox", { name: /group by/i })).toHaveTextContent("Team");
  });

  it("remembers a sort choice across a remount", async () => {
    const user = userEvent.setup();
    const first = render(<Harness />);

    await user.click(screen.getByRole("button", { name: "Name" }));
    expect(stored().sorting).toEqual([{ id: "name", desc: false }]);

    first.unmount();
    render(<Harness />);
    // Ascending by name puts "a" first; unsorted, the source order leads with "b".
    expect(screen.getAllByRole("row")[1]).toHaveTextContent("a");
  });

  it("clearing a choice clears what was stored", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("combobox", { name: /group by/i }));
    await user.click(screen.getByRole("option", { name: "Team" }));
    await user.click(screen.getByRole("combobox", { name: /group by/i }));
    await user.click(screen.getByRole("option", { name: "None" }));

    expect(stored().grouping).toEqual([]);
  });

  it("swaps to the new key's answer when the list changes what it is showing", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Harness storageKey="table-a" />);

    await user.click(screen.getByRole("combobox", { name: /group by/i }));
    await user.click(screen.getByRole("option", { name: "Team" }));

    // A sibling list with nothing saved must not inherit this one's grouping.
    rerender(<Harness storageKey="table-b" />);
    expect(screen.getByRole("combobox", { name: /group by/i })).toHaveTextContent("None");

    rerender(<Harness storageKey="table-a" />);
    expect(screen.getByRole("combobox", { name: /group by/i })).toHaveTextContent("Team");
  });

  it("falls back to no grouping or sorting when the stored blob is unusable", () => {
    setItem(KEY, "{ not json");
    render(<Harness />);

    expect(screen.getByRole("combobox", { name: /group by/i })).toHaveTextContent("None");
    expect(screen.getAllByRole("row")[1]).toHaveTextContent("b");
  });
});
