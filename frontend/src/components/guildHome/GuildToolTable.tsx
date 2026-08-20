/**
 * The guild home's one table. Every tool renders through it — the columns are
 * fixed and the tool only supplies the rows (see `useGuildToolRows`), so
 * switching tools swaps the data, not the layout.
 *
 * Rows are read a server page at a time, in the order that tool's endpoint
 * returns them (recently-updated or by name, depending on the tool). There is
 * deliberately no client-side sort or filter here: either would only reach the
 * page already in hand, and a table that answers "no matches" while the guild
 * holds matches on page 4 is worse than no filter at all. Both come back the
 * moment the remaining list endpoints accept `search`/`sort_by` — the page's
 * pagination is already server-driven.
 */

import { Link } from "@tanstack/react-router";
import type { PaginationState } from "@tanstack/react-table";
import type { ParseKeys } from "i18next";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { InitiativeRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { TagBadge } from "@/components/tags/TagBadge";
import { DataTable } from "@/components/ui/data-table";
import { RelativeTime } from "@/components/ui/relative-time";
import type { GuildToolRow } from "@/hooks/useGuildToolRows";
import { useGuildPath } from "@/lib/guildUrl";
import type { AppColumnDef } from "@/lib/table";
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
        header: t("columns.name"),
        cell: ({ row }) => <NameCell row={row.original} />,
        enableHiding: false,
      },
      {
        id: "initiative",
        header: t("columns.initiative"),
        cell: ({ row }) => (
          <InitiativeCell initiativeId={row.original.initiativeId} initiatives={initiativesById} />
        ),
      },
      {
        id: "detail",
        // Each tool names this column in its own terms ("Progress", "Items", …).
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
        header: t("columns.updated"),
        cell: ({ row }) => (
          <RelativeTime date={row.original.updatedAt} className="text-muted-foreground text-sm" />
        ),
      },
    ],
    [t, tool, initiativesById]
  );

  return (
    <DataTable
      columns={columns}
      data={rows}
      getRowId={(row: GuildToolRow) => String(row.id)}
      enableColumnVisibilityDropdown
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
