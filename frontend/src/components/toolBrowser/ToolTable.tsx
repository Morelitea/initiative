/**
 * The one tool table. Every tool renders through it — the columns are fixed
 * and the tool only supplies the rows (see `lib/toolRows`), so switching tools
 * swaps the data, not the layout. So do the two pages that show it: a
 * community's front page and My Tools differ by a column and by which headers
 * sort, not by a second table.
 *
 * Rows are read a server page at a time, and the search box and the sortable
 * headers go to the server with them. Nothing here filters or sorts the page
 * already in hand: that would answer "no matches" while page 4 holds matches,
 * and would sort the accident of pagination rather than the work. The columns
 * every tool shares are the ones that sort, because they are the only ones
 * every tool's endpoint can order by; the tool's own column is its own
 * business.
 *
 * Every row addresses its own community, so links are absolute rather than
 * relative to whichever community the reader happens to be in.
 */

import { Link } from "@tanstack/react-router";
import type { PaginationState } from "@tanstack/react-table";
import type { ParseKeys } from "i18next";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { InitiativeRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { SortIcon } from "@/components/SortIcon";
import { TagBadge } from "@/components/tags/TagBadge";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { RelativeTime } from "@/components/ui/relative-time";
import { guildPath } from "@/lib/guildUrl";
import type { AppColumn, AppColumnDef } from "@/lib/table";
import type { ToolRow } from "@/lib/toolRows";
import { initiativeRoute, toolCamelPlural } from "@/lib/tools";

/** The leaf keys under `guildHome.columns.detail` — one per tool. */
type DetailColumnKey = Extract<ParseKeys<"guildHome">, `columns.detail.${string}`>;

/** guildHome.json header key for a tool's own column, e.g.
 *  `columns.detail.counterGroups` — derived the same way as the nav labels in
 *  `lib/tools`, and pinned for every tool by the tool-registry drift test. */
const detailColumnKey = (tool: Tool): DetailColumnKey =>
  `columns.detail.${toolCamelPlural(tool)}` as DetailColumnKey;

/** An initiative, wherever it lives: ids repeat across communities, so the
 *  community is half the key. */
const initiativeKey = (guildId: number, initiativeId: number) => `${guildId}:${initiativeId}`;

const NameCell = ({ row }: { row: ToolRow }) => (
  <div className="flex min-w-[220px] items-center gap-2 sm:min-w-0">
    {row.glyph}
    <Link
      to={guildPath(row.guildId, row.href)}
      className="truncate font-medium text-primary hover:underline"
    >
      {row.name}
    </Link>
  </div>
);

const CommunityCell = ({
  row,
  communities,
}: {
  row: ToolRow;
  communities: Map<number, string>;
}) => {
  const name = communities.get(row.guildId);
  if (!name) {
    return <span className="text-muted-foreground text-sm">—</span>;
  }
  return (
    <Link to={guildPath(row.guildId, "/")} className="text-sm hover:underline">
      {name}
    </Link>
  );
};

const InitiativeCell = ({
  row,
  initiatives,
}: {
  row: ToolRow;
  initiatives: Map<string, InitiativeRead>;
}) => {
  const { t } = useTranslation("guildHome");
  if (row.initiativeId === null) {
    return <span className="text-muted-foreground text-sm">{t("guildWide")}</span>;
  }
  const initiative = initiatives.get(initiativeKey(row.guildId, row.initiativeId));
  if (!initiative) {
    return <span className="text-muted-foreground text-sm">—</span>;
  }
  return (
    <Link
      to={guildPath(row.guildId, initiativeRoute(initiative.id))}
      className="text-sm hover:underline"
    >
      {initiative.name}
    </Link>
  );
};

const TagsCell = ({ row }: { row: ToolRow }) => {
  if (row.tags.length === 0) {
    return <span className="text-muted-foreground text-sm">—</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {row.tags.slice(0, 3).map((tag) => (
        <TagBadge key={tag.id} tag={tag} size="sm" to={guildPath(row.guildId, `/tags/${tag.id}`)} />
      ))}
      {row.tags.length > 3 && (
        <span className="text-muted-foreground text-xs">+{row.tags.length - 3}</span>
      )}
    </div>
  );
};

/** A column header that toggles that column's sort. The arrow reads the
 *  table's own state, which the page keeps in the address bar. */
const SortHeader = ({ column, label }: { column: AppColumn<ToolRow>; label: string }) => {
  const isSorted = column.getIsSorted();
  return (
    <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
      {label}
      <SortIcon isSorted={isSorted} />
    </Button>
  );
};

/** The columns a tool's list endpoint can order by, as it names them. */
export const TOOL_SORT_FIELDS = ["name", "initiative", "updated_at"] as const;
export type ToolSortField = (typeof TOOL_SORT_FIELDS)[number];

/**
 * What a cross-guild list can order by. One short of the full set: ordering by
 * initiative means ordering by its name, which a merged list — assembled in
 * Python from summaries that carry an initiative id and not its name — has no
 * way to do. So that header does not sort on My Tools.
 */
export const CROSS_GUILD_TOOL_SORT_FIELDS = ["name", "updated_at"] as const;

/** Table column id → the field name the endpoints take, and back. */
const SORT_FIELD_BY_COLUMN: Record<string, ToolSortField> = {
  name: "name",
  initiative: "initiative",
  updated: "updated_at",
};
const COLUMN_BY_SORT_FIELD: Record<ToolSortField, string> = {
  name: "name",
  initiative: "initiative",
  updated_at: "updated",
};

/** Whether `value` names a field the given set can order by — how a page reads
 *  the order out of its own address bar. */
export const isToolSortField = (
  value: unknown,
  fields: readonly ToolSortField[] = TOOL_SORT_FIELDS
): value is ToolSortField =>
  typeof value === "string" && (fields as readonly string[]).includes(value);

interface ToolTableProps {
  tool: Tool;
  rows: ToolRow[];
  /** Every initiative the rows might name, from however many communities. */
  initiatives: InitiativeRead[];
  /**
   * Community id → name. Passing it adds the community column, which is what a
   * cross-community table needs and a single community's own page does not.
   */
  communities?: Map<number, string>;
  totalCount: number;
  page: number;
  /** Computed by the page, which also uses it to recover an out-of-range page. */
  pageCount: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
  /** The search text, as it is in the address bar. */
  search: string;
  onSearchChange: (search: string) => void;
  /** One of {@link TOOL_SORT_FIELDS}, and which way. */
  sortBy: ToolSortField;
  sortDir: "asc" | "desc";
  onSortChange: (sortBy: ToolSortField, sortDir: "asc" | "desc") => void;
  /** Which headers offer to sort. Defaults to every column that can. */
  sortFields?: readonly ToolSortField[];
}

export const ToolTable = ({
  tool,
  rows,
  initiatives,
  communities,
  totalCount,
  page,
  pageCount,
  pageSize,
  onPageChange,
  onPageSizeChange,
  search,
  onSearchChange,
  sortBy,
  sortDir,
  onSortChange,
  sortFields = TOOL_SORT_FIELDS,
}: ToolTableProps) => {
  const { t } = useTranslation("guildHome");

  const initiativesByKey = useMemo(
    () =>
      new Map(
        initiatives.map((initiative) => [
          initiativeKey(initiative.guild_id, initiative.id),
          initiative,
        ])
      ),
    [initiatives]
  );

  const columns = useMemo<AppColumnDef<ToolRow>[]>(() => {
    /** A header that sorts where the page allows it, and plain text where it
     *  does not — a control that cannot act would only mislead. */
    const header = (field: ToolSortField, label: string) =>
      sortFields.includes(field)
        ? ({ column }: { column: AppColumn<ToolRow> }) => (
            <SortHeader column={column} label={label} />
          )
        : () => <span className="px-3 font-medium">{label}</span>;

    return [
      {
        accessorKey: "name",
        header: header("name", t("columns.name")),
        cell: ({ row }) => <NameCell row={row.original} />,
        enableSorting: sortFields.includes("name"),
        enableHiding: false,
      },
      ...(communities
        ? [
            {
              id: "community",
              header: t("columns.community"),
              cell: ({ row }) => <CommunityCell row={row.original} communities={communities} />,
            } satisfies AppColumnDef<ToolRow>,
          ]
        : []),
      {
        id: "initiative",
        header: header("initiative", t("columns.initiative")),
        cell: ({ row }) => <InitiativeCell row={row.original} initiatives={initiativesByKey} />,
        enableSorting: sortFields.includes("initiative"),
      },
      {
        id: "detail",
        // Each tool names this column in its own terms ("Progress", "Items",
        // …), and each means something different by it, so there is no one
        // ordering for the endpoints to agree on. It does not sort.
        header: t(detailColumnKey(tool)),
        cell: ({ row }) => (
          <span className="text-sm">
            {row.original.detail || <span className="text-muted-foreground">—</span>}
          </span>
        ),
      },
      {
        id: "tags",
        header: t("columns.tags"),
        cell: ({ row }) => <TagsCell row={row.original} />,
        size: 150,
      },
      {
        id: "updated",
        header: header("updated_at", t("columns.updated")),
        cell: ({ row }) => (
          <RelativeTime date={row.original.updatedAt} className="text-muted-foreground text-sm" />
        ),
        enableSorting: sortFields.includes("updated_at"),
      },
    ];
  }, [t, tool, initiativesByKey, communities, sortFields]);

  return (
    <DataTable
      columns={columns}
      data={rows}
      // Ids repeat across communities, so the community is half the row key.
      getRowId={(row: ToolRow) => `${row.guildId}:${row.id}`}
      enableFilterInput
      filterInputPlaceholder={t("searchPlaceholder")}
      filterValue={search}
      onFilterValueChange={onSearchChange}
      enableColumnVisibilityDropdown
      manualSorting
      // Controlled, not seeded: the order lives in the address, so the back
      // button can change it after this mounts and the headers have to follow.
      sorting={[{ id: COLUMN_BY_SORT_FIELD[sortBy], desc: sortDir === "desc" }]}
      onSortingChange={(sorting) => {
        // Clearing the sort altogether lands back on the page's own default
        // rather than on whatever each endpoint would do unsorted.
        const next = sorting[0];
        const field = next ? SORT_FIELD_BY_COLUMN[next.id] : undefined;
        if (!field) {
          onSortChange("updated_at", "desc");
          return;
        }
        onSortChange(field, next.desc ? "desc" : "asc");
      }}
      enablePagination
      manualPagination
      pageCount={pageCount}
      rowCount={totalCount}
      pageIndex={page - 1}
      onPaginationChange={(pagination: PaginationState) => {
        if (pagination.pageSize !== pageSize) {
          onPageSizeChange(pagination.pageSize);
        } else {
          onPageChange(pagination.pageIndex + 1);
        }
      }}
    />
  );
};
