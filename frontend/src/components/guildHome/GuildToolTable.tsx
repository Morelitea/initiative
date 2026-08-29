/**
 * The guild home's one table. Every tool renders through it — the columns are
 * fixed and the tool only supplies the rows (see `useGuildToolRows`), so
 * switching tools swaps the data, not the layout.
 *
 * Rows are read a server page at a time, and the search box and the three
 * sortable headers go to the server with them. Nothing here filters or sorts
 * the page already in hand: that would answer "no matches" while the guild
 * holds matches on page 4, and would sort the accident of pagination rather
 * than the guild's work. The columns every tool shares — name, initiative,
 * last updated — are the ones that sort, because they are the only ones every
 * tool's endpoint can order by; the tool's own column is its own business.
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
import type { GuildToolRow } from "@/hooks/useGuildToolRows";
import { useGuildPath } from "@/lib/guildUrl";
import type { AppColumn, AppColumnDef } from "@/lib/table";
import { initiativeRoute, toolCamelPlural } from "@/lib/tools";

/** The leaf keys under `guildHome.columns.detail` — one per tool. */
type DetailColumnKey = Extract<ParseKeys<"guildHome">, `columns.detail.${string}`>;

/** guildHome.json header key for a tool's own column, e.g.
 *  `columns.detail.counterGroups` — derived the same way as the nav labels in
 *  `lib/tools`, and pinned for every tool by the tool-registry drift test. */
const detailColumnKey = (tool: Tool): DetailColumnKey =>
  `columns.detail.${toolCamelPlural(tool)}` as DetailColumnKey;

const NameCell = ({ row }: { row: GuildToolRow }) => {
  const gp = useGuildPath();
  return (
    <div className="flex min-w-[220px] items-center gap-2 sm:min-w-0">
      {row.glyph}
      <Link to={gp(row.href)} className="truncate font-medium text-primary hover:underline">
        {row.name}
      </Link>
    </div>
  );
};

const InitiativeCell = ({
  initiativeId,
  initiatives,
}: {
  initiativeId: number | null;
  initiatives: Map<number, InitiativeRead>;
}) => {
  const { t } = useTranslation("guildHome");
  const gp = useGuildPath();
  if (initiativeId === null) {
    return <span className="text-muted-foreground text-sm">{t("guildWide")}</span>;
  }
  const initiative = initiatives.get(initiativeId);
  if (!initiative) {
    return <span className="text-muted-foreground text-sm">—</span>;
  }
  return (
    <Link to={gp(initiativeRoute(initiative.id))} className="text-sm hover:underline">
      {initiative.name}
    </Link>
  );
};

const TagsCell = ({ row }: { row: GuildToolRow }) => {
  const gp = useGuildPath();
  if (row.tags.length === 0) {
    return <span className="text-muted-foreground text-sm">—</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {row.tags.slice(0, 3).map((tag) => (
        <TagBadge key={tag.id} tag={tag} size="sm" to={gp(`/tags/${tag.id}`)} />
      ))}
      {row.tags.length > 3 && (
        <span className="text-muted-foreground text-xs">+{row.tags.length - 3}</span>
      )}
    </div>
  );
};

/** A column header that toggles that column's sort. The arrow reads the
 *  table's own state, which the page keeps in the address bar. */
const SortHeader = ({ column, label }: { column: AppColumn<GuildToolRow>; label: string }) => {
  const isSorted = column.getIsSorted();
  return (
    <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
      {label}
      <SortIcon isSorted={isSorted} />
    </Button>
  );
};

/** The columns every tool's list endpoint can order by, as it names them. */
export const GUILD_TOOL_SORT_FIELDS = ["name", "initiative", "updated_at"] as const;
export type GuildToolSortField = (typeof GUILD_TOOL_SORT_FIELDS)[number];

/** Table column id → the field name the endpoints take, and back. */
const SORT_FIELD_BY_COLUMN: Record<string, GuildToolSortField> = {
  name: "name",
  initiative: "initiative",
  updated: "updated_at",
};
const COLUMN_BY_SORT_FIELD: Record<GuildToolSortField, string> = {
  name: "name",
  initiative: "initiative",
  updated_at: "updated",
};

export const isGuildToolSortField = (value: unknown): value is GuildToolSortField =>
  typeof value === "string" && (GUILD_TOOL_SORT_FIELDS as readonly string[]).includes(value);

interface GuildToolTableProps {
  tool: Tool;
  rows: GuildToolRow[];
  initiatives: InitiativeRead[];
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
  /** One of {@link GUILD_TOOL_SORT_FIELDS}, and which way. */
  sortBy: GuildToolSortField;
  sortDir: "asc" | "desc";
  onSortChange: (sortBy: GuildToolSortField, sortDir: "asc" | "desc") => void;
}

export const GuildToolTable = ({
  tool,
  rows,
  initiatives,
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
}: GuildToolTableProps) => {
  const { t } = useTranslation("guildHome");

  const initiativesById = useMemo(
    () => new Map(initiatives.map((initiative) => [initiative.id, initiative])),
    [initiatives]
  );

  const columns = useMemo<AppColumnDef<GuildToolRow>[]>(
    () => [
      {
        accessorKey: "name",
        header: ({ column }) => <SortHeader column={column} label={t("columns.name")} />,
        cell: ({ row }) => <NameCell row={row.original} />,
        enableSorting: true,
        enableHiding: false,
      },
      {
        id: "initiative",
        header: ({ column }) => <SortHeader column={column} label={t("columns.initiative")} />,
        cell: ({ row }) => (
          <InitiativeCell initiativeId={row.original.initiativeId} initiatives={initiativesById} />
        ),
        enableSorting: true,
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
        header: ({ column }) => <SortHeader column={column} label={t("columns.updated")} />,
        cell: ({ row }) => (
          <RelativeTime date={row.original.updatedAt} className="text-muted-foreground text-sm" />
        ),
        enableSorting: true,
      },
    ],
    [t, tool, initiativesById]
  );

  return (
    <DataTable
      columns={columns}
      data={rows}
      getRowId={(row: GuildToolRow) => String(row.id)}
      enableFilterInput
      filterInputPlaceholder={t("searchPlaceholder")}
      filterValue={search}
      onFilterValueChange={onSearchChange}
      enableColumnVisibilityDropdown
      manualSorting
      initialSorting={[{ id: COLUMN_BY_SORT_FIELD[sortBy], desc: sortDir === "desc" }]}
      onSortingChange={(sorting) => {
        // Clearing the sort altogether lands back on the guild home's own
        // default rather than on whatever each endpoint would do unsorted.
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
