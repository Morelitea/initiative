import { FileSpreadsheet, FileText, Presentation } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { DocumentSummary } from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/components/ui/badge";
import { getFileTypeLabel } from "@/lib/fileUtils";
import type { AppColumnDef } from "@/lib/table";
import { getUserDisplayName } from "@/lib/userDisplay";

/** What the documents table shows beside the columns every tool's table has:
 *  how many projects a document is linked to, its owner, and its type. */
export const useDocumentColumns = (): AppColumnDef<DocumentSummary>[] => {
  const { t } = useTranslation("documents");

  return useMemo<AppColumnDef<DocumentSummary>[]>(
    () => [
      {
        id: "projects",
        header: t("columns.projects"),
        cell: ({ row }) => <span>{row.original.projects.length}</span>,
      },
      {
        id: "owner",
        header: t("columns.owner"),
        cell: ({ row }) => {
          // An installed app owns what it made; its name is the owner's name.
          if (row.original.owner_app) {
            return <span>{row.original.owner_app.name}</span>;
          }
          const ownerGrant = (row.original.grants ?? []).find((g) => g.level === "owner");
          if (!ownerGrant || ownerGrant.user_id == null) {
            return <span className="text-muted-foreground">—</span>;
          }
          const ownerName = row.original.owner ? getUserDisplayName(row.original.owner) : undefined;
          return <span>{ownerName || t("columns.ownerFallback", { id: ownerGrant.user_id })}</span>;
        },
      },
      {
        id: "type",
        header: t("columns.type"),
        cell: ({ row }) => {
          const doc = row.original;
          if (doc.document_type === "file") {
            const fileTypeLabel = getFileTypeLabel(doc.file_content_type, doc.original_filename);
            const Icon =
              fileTypeLabel === "Excel"
                ? FileSpreadsheet
                : fileTypeLabel === "PowerPoint"
                  ? Presentation
                  : FileText;
            return (
              <Badge variant="secondary" className="flex w-fit items-center gap-1">
                <Icon className="h-3 w-3" />
                {fileTypeLabel}
              </Badge>
            );
          }
          return doc.is_template ? (
            <Badge variant="outline">{t("type.template")}</Badge>
          ) : (
            <span className="text-muted-foreground">{t("type.document")}</span>
          );
        },
      },
    ],
    [t]
  );
};
