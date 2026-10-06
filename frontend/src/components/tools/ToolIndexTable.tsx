/**
 * A tool's index list drawn as a table: the columns every tool's rows share —
 * name, last change, tags and the initiative's properties — and after them the
 * ones the tool adds through its `TOOL_INDEX` entry. The server sorts, so the
 * sortable columns are named by the field the list endpoint sorts on.
 */

import { Link } from "@tanstack/react-router";
import type { SortingState } from "@tanstack/react-table";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { UnreadDot } from "@/components/notifications/UnreadDot";
import { buildPropertyColumns, propertyColumnIds } from "@/components/properties/propertyColumns";
import { SortHeader } from "@/components/SortIcon";
import { TagBadgeList } from "@/components/tags/TagBadge";
import type { ToolIndexRow } from "@/components/tools/ToolIndexPage";
import { Checkbox } from "@/components/ui/checkbox";
import { DataTable } from "@/components/ui/data-table";
import { RelativeTime } from "@/components/ui/relative-time";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import type { GridToggleOptions } from "@/hooks/useGridSelection";
import { usePersistedColumnVisibility } from "@/hooks/usePersistedColumnVisibility";
import { useProperties } from "@/hooks/useProperties";
import { useUnreadTree } from "@/hooks/useUnreadTree";
import { useCommunityPath } from "@/lib/communityUrl";
import type { AppColumnDef } from "@/lib/table";
import { toolDetailRoute, toolRouteSegment } from "@/lib/tools";

/** The list fields a table header sorts by, as its column ids. */
export const TABLE_SORT_FIELDS: ReadonlySet<string> = new Set(["name", "updated_at"]);

/** Where a tool's table keeps the reader's order and its hidden columns. */
export const toolTableStorageKey = (tool: Tool, what: "order" | "columns") =>
  `initiative-${toolRouteSegment(tool)}-${what}`;

/** The slice of {@link useGridSelection} the table's checkboxes drive. */
interface TableSelection {
  active: boolean;
  selectedIds: Set<number>;
  toggle: (row: ToolIndexRow, options?: GridToggleOptions) => void;
  setMany: (rows: readonly ToolIndexRow[], selected: boolean) => void;
}

type ToolIndexTableProps = {
  tool: Tool;
  initiativeId: number;
  rows: ToolIndexRow[];
  /** The tool's own columns, after the shared ones (its entry's `table`). */
  useColumns: () => AppColumnDef<ToolIndexRow>[];
  selection: TableSelection;
  sorting: SortingState;
  onSortingChange: (sorting: SortingState) => void;
};

export const ToolIndexTable = ({
  tool,
  initiativeId,
  rows,
  useColumns,
  selection,
  sorting,
  onSortingChange,
}: ToolIndexTableProps) => {
  const { t } = useTranslation("common");
  const columns = useColumns();
  const gp = useCommunityPath();
  const communityId = useActiveCommunityId();
  const unread = useUnreadTree();

  const { data: definitions = [] } = useProperties({ initiativeId });
  // Property columns start hidden; the column menu turns them on.
  const hiddenByDefault = useMemo(() => propertyColumnIds(definitions), [definitions]);
  const [columnVisibility, setColumnVisibility] = usePersistedColumnVisibility(
    toolTableStorageKey(tool, "columns"),
    hiddenByDefault
  );

  // The selection object is rebuilt every render; the columns depend on its
  // parts, so the headers are not remounted under a click.
  const { active, selectedIds, toggle, setMany } = selection;
  const allSelected = rows.length > 0 && rows.every((row) => selectedIds.has(row.id));
  const someSelected = rows.some((row) => selectedIds.has(row.id));

  const tableColumns = useMemo<AppColumnDef<ToolIndexRow>[]>(
    () => [
      ...(active
        ? [
            {
              id: "select",
              header: () => (
                <Checkbox
                  checked={allSelected || (someSelected && "indeterminate")}
                  onCheckedChange={(value) => setMany(rows, value === true)}
                  aria-label={t("selectAll")}
                />
              ),
              cell: ({ row }) => (
                <Checkbox
                  checked={selectedIds.has(row.original.id)}
                  // Shift extends from the last row clicked, as on the cards.
                  onClick={(event) => {
                    event.preventDefault();
                    toggle(row.original, { extend: event.shiftKey });
                  }}
                  aria-label={t("selectRow")}
                />
              ),
              enableSorting: false,
              enableHiding: false,
            } satisfies AppColumnDef<ToolIndexRow>,
          ]
        : []),
      {
        id: "name",
        accessorKey: "name",
        header: ({ column }) => <SortHeader column={column} label={t("name")} />,
        cell: ({ row }) => (
          <div className="flex min-w-[220px] items-center gap-2 sm:min-w-0">
            <Link
              to={gp(toolDetailRoute(tool, row.original.initiative_id, row.original.id))}
              className="font-medium text-primary hover:underline"
            >
              {row.original.name}
            </Link>
            {unread.hasResource(communityId, tool, row.original.id) ? <UnreadDot /> : null}
          </div>
        ),
        enableSorting: true,
        enableHiding: false,
      },
      {
        id: "updated_at",
        accessorKey: "updated_at",
        header: ({ column }) => <SortHeader column={column} label={t("toolIndex.lastUpdated")} />,
        cell: ({ row }) => (
          <div className="min-w-[100px] sm:min-w-0">
            <RelativeTime date={row.original.updated_at} className="text-muted-foreground" />
          </div>
        ),
        enableSorting: true,
      },
      {
        id: "tags",
        header: t("toolIndex.tags"),
        cell: ({ row }) =>
          row.original.tags?.length ? (
            <TagBadgeList tags={row.original.tags} tagHref={(tag) => gp(`/tags/${tag.id}`)} />
          ) : (
            <span className="text-muted-foreground text-sm">—</span>
          ),
        size: 150,
        enableSorting: false,
      },
      ...buildPropertyColumns<ToolIndexRow>(definitions, (row) => row.properties),
      ...columns,
    ],
    [
      active,
      selectedIds,
      toggle,
      setMany,
      allSelected,
      someSelected,
      rows,
      t,
      gp,
      tool,
      unread,
      communityId,
      definitions,
      columns,
    ]
  );

  return (
    <DataTable
      columns={tableColumns}
      data={rows}
      columnVisibility={columnVisibility}
      onColumnVisibilityChange={setColumnVisibility}
      enableColumnVisibilityDropdown
      manualSorting
      sorting={sorting}
      onSortingChange={onSortingChange}
      enableResetSorting
      getRowId={(row) => String(row.id)}
    />
  );
};
