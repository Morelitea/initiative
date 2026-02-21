import { useMemo } from "react";
import type { ColumnDef, SortingState } from "@tanstack/react-table";
import type { PaginationState } from "@tanstack/react-table";
import { Link } from "@tanstack/react-router";
import { formatDistanceToNow } from "date-fns";
import {
  Copy,
  FileSpreadsheet,
  FileText,
  Loader2,
  Presentation,
  Shield,
  Tags,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { SortIcon } from "@/components/SortIcon";
import { TagBadge } from "@/components/tags/TagBadge";
import { useDateLocale } from "@/hooks/useDateLocale";
import { useGuildPath } from "@/lib/guildUrl";
import { getFileTypeLabel } from "@/lib/fileUtils";
import { dateSortingFn } from "@/lib/sorting";
import type { DocumentSummary, TagSummary } from "@/api/generated/initiativeAPI.schemas";

// Cell component that uses guild-scoped URLs
const DocumentTitleCell = ({ document }: { document: DocumentSummary }) => {
  const gp = useGuildPath();
  return (
    <div className="min-w-[220px] sm:min-w-0">
      <Link
        to={gp(`/documents/${document.id}`)}
        className="text-primary font-medium hover:underline"
      >
        {document.title}
      </Link>
    </div>
  );
};

const DocumentTagsCell = ({ tags }: { tags: TagSummary[] }) => {
  const gp = useGuildPath();
  if (tags.length === 0) {
    return <span className="text-muted-foreground text-sm">—</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {tags.slice(0, 3).map((tag) => (
        <TagBadge key={tag.id} tag={tag} size="sm" to={gp(`/tags/${tag.id}`)} />
      ))}
      {tags.length > 3 && <span className="text-muted-foreground text-xs">+{tags.length - 3}</span>}
    </div>
  );
};

export interface DocumentsListViewProps {
  documents: DocumentSummary[];
  selectedDocuments: DocumentSummary[];
  onSelectedDocumentsChange: (docs: DocumentSummary[]) => void;
  canEditSelectedDocuments: boolean;
  canDuplicateSelectedDocuments: boolean;
  canDeleteSelectedDocuments: boolean;
  onBulkEditTags: () => void;
  onBulkEditAccess: () => void;
  onBulkDuplicate: () => void;
  isBulkDuplicating: boolean;
  onBulkDelete: () => void;
  isBulkDeleting: boolean;
  totalPages: number;
  totalCount: number;
  pageSize: number;
  onPageSizeChange: (size: number) => void;
  onPageChange: (updater: number | ((prev: number) => number)) => void;
  onPrefetchPage: (page: number) => void;
  onSortingChange: (sorting: SortingState) => void;
}

export const DocumentsListView = ({
  documents,
  selectedDocuments,
  onSelectedDocumentsChange,
  canEditSelectedDocuments,
  canDuplicateSelectedDocuments,
  canDeleteSelectedDocuments,
  onBulkEditTags,
  onBulkEditAccess,
  onBulkDuplicate,
  isBulkDuplicating,
  onBulkDelete,
  isBulkDeleting,
  totalPages,
  totalCount,
  pageSize,
  onPageSizeChange,
  onPageChange,
  onPrefetchPage,
  onSortingChange,
}: DocumentsListViewProps) => {
  const { t } = useTranslation(["documents", "common"]);
  const dateLocale = useDateLocale();

  // Column definitions with translations (must be inside component for hook access)
  const documentColumns: ColumnDef<DocumentSummary>[] = useMemo(
    () => [
      {
        accessorKey: "title",
        header: ({ column }) => {
          const isSorted = column.getIsSorted();
          return (
            <div className="flex items-center gap-2">
              <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
                {t("documents:columns.title")}
                <SortIcon isSorted={isSorted} />
              </Button>
            </div>
          );
        },
        cell: ({ row }) => <DocumentTitleCell document={row.original} />,
        enableSorting: true,
        sortingFn: "alphanumeric",
        enableHiding: false,
      },
      {
        id: "last updated",
        accessorKey: "updated_at",
        header: ({ column }) => {
          const isSorted = column.getIsSorted();
          return (
            <div className="flex items-center gap-2">
              <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
                {t("documents:columns.lastUpdated")}
                <SortIcon isSorted={isSorted} />
              </Button>
            </div>
          );
        },
        cell: ({ row }) => {
          const updatedAt = new Date(row.original.updated_at);
          return (
            <div className="min-w-[100px] sm:min-w-0">
              <span className="text-muted-foreground">
                {formatDistanceToNow(updatedAt, { addSuffix: true, locale: dateLocale })}
              </span>
            </div>
          );
        },
        sortingFn: dateSortingFn,
      },
      {
        accessorKey: "projects",
        header: t("documents:columns.projects"),
        cell: ({ row }) => {
          const count = row.original.projects.length;
          return <span>{count}</span>;
        },
      },
      {
        id: "tags",
        header: t("documents:columns.tags"),
        cell: ({ row }) => <DocumentTagsCell tags={row.original.tags ?? []} />,
        size: 150,
      },
      {
        id: "owner",
        header: t("documents:columns.owner"),
        cell: ({ row }) => {
          const ownerPermission = (row.original.permissions ?? []).find((p) => p.level === "owner");
          if (!ownerPermission) {
            return <span className="text-muted-foreground">—</span>;
          }
          const ownerMember = row.original.initiative?.members?.find(
            (m) => m.user.id === ownerPermission.user_id
          );
          const ownerName = ownerMember?.user?.full_name || ownerMember?.user?.email;
          return (
            <span>
              {ownerName || t("documents:bulk.userFallback", { id: ownerPermission.user_id })}
            </span>
          );
        },
      },
      {
        id: "type",
        accessorKey: "is_template",
        header: t("documents:columns.type"),
        cell: ({ row }) => {
          const doc = row.original;
          const isFile = doc.document_type === "file";
          const fileTypeLabel = isFile
            ? getFileTypeLabel(doc.file_content_type, doc.original_filename)
            : null;

          return (
            <div className="flex items-center gap-2">
              {isFile ? (
                <Badge variant="secondary" className="flex items-center gap-1">
                  {fileTypeLabel === "Excel" ? (
                    <FileSpreadsheet className="h-3 w-3" />
                  ) : fileTypeLabel === "PowerPoint" ? (
                    <Presentation className="h-3 w-3" />
                  ) : (
                    <FileText className="h-3 w-3" />
                  )}
                  {fileTypeLabel}
                </Badge>
              ) : doc.is_template ? (
                <Badge variant="outline">{t("documents:type.template")}</Badge>
              ) : (
                <span className="text-muted-foreground">{t("documents:type.document")}</span>
              )}
            </div>
          );
        },
      },
    ],
    [t, dateLocale]
  );

  return (
    <>
      {selectedDocuments.length > 0 && (
        <div className="border-primary bg-primary/5 flex items-center justify-between rounded-md border p-4">
          <div className="text-sm font-medium">
            {t("documents:bulk.selected", { count: selectedDocuments.length })}
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={onBulkEditTags}
              disabled={!canEditSelectedDocuments}
              title={canEditSelectedDocuments ? undefined : t("documents:bulk.needEditAccessTags")}
            >
              <Tags className="h-4 w-4" />
              {t("documents:bulk.editTags")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={onBulkEditAccess}
              disabled={!canEditSelectedDocuments}
              title={
                canEditSelectedDocuments ? undefined : t("documents:bulk.needEditAccessPermissions")
              }
            >
              <Shield className="h-4 w-4" />
              {t("documents:bulk.editAccess")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={onBulkDuplicate}
              disabled={isBulkDuplicating || !canDuplicateSelectedDocuments}
              title={
                canDuplicateSelectedDocuments
                  ? undefined
                  : t("documents:bulk.needEditAccessDuplicate")
              }
            >
              {isBulkDuplicating ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t("documents:bulk.duplicating")}
                </>
              ) : (
                <>
                  <Copy className="h-4 w-4" />
                  {t("documents:bulk.duplicate")}
                </>
              )}
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={onBulkDelete}
              disabled={isBulkDeleting || !canDeleteSelectedDocuments}
              title={canDeleteSelectedDocuments ? undefined : t("documents:bulk.needOwnerAccess")}
            >
              {isBulkDeleting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t("documents:bulk.deleting")}
                </>
              ) : (
                <>
                  <Trash2 className="h-4 w-4" />
                  {t("common:delete")}
                </>
              )}
            </Button>
          </div>
        </div>
      )}
      <DataTable
        columns={documentColumns}
        data={documents}
        enableFilterInput
        filterInputColumnKey="title"
        filterInputPlaceholder={t("documents:page.filterPlaceholder")}
        enableColumnVisibilityDropdown
        enablePagination
        manualPagination
        pageCount={totalPages}
        rowCount={totalCount}
        onPaginationChange={(pag: PaginationState) => {
          if (pag.pageSize !== pageSize) {
            onPageSizeChange(pag.pageSize);
          } else {
            onPageChange(pag.pageIndex + 1);
          }
        }}
        onPrefetchPage={(pageIndex: number) => onPrefetchPage(pageIndex + 1)}
        manualSorting
        onSortingChange={onSortingChange}
        enableResetSorting
        enableRowSelection
        onRowSelectionChange={onSelectedDocumentsChange}
        getRowId={(row: DocumentSummary) => String(row.id)}
        onExitSelection={() => onSelectedDocumentsChange([])}
      />
    </>
  );
};
