import { Copy, FileDown, Loader2, Shield, Tags, Trash2 } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { DocumentSummary } from "@/api/generated/initiativeAPI.schemas";
import { ExportButton } from "@/components/exports/ExportButton";
import { documentSelectionFormats } from "@/components/exports/formats";
import { Button } from "@/components/ui/button";
import { exportFilenameStem } from "@/lib/exportDownload";

interface DocumentsBulkBarProps {
  selectedDocuments: DocumentSummary[];
  canEditSelectedDocuments: boolean;
  canDuplicateSelectedDocuments: boolean;
  canDeleteSelectedDocuments: boolean;
  onBulkEditTags: () => void;
  onBulkEditAccess: () => void;
  onBulkDuplicate: () => void;
  isBulkDuplicating: boolean;
  onBulkDelete: () => void;
  isBulkDeleting: boolean;
  /** Grid/tags selection mode: renders a Cancel action that exits the mode
   * (the table view's checkboxes clear themselves, so it passes nothing). */
  onExit?: () => void;
}

/** The documents bulk-selection toolbar — shared by the table view and the
 * grid/tags selection mode so every view offers the same actions. */
export function DocumentsBulkBar({
  selectedDocuments,
  canEditSelectedDocuments,
  canDuplicateSelectedDocuments,
  canDeleteSelectedDocuments,
  onBulkEditTags,
  onBulkEditAccess,
  onBulkDuplicate,
  isBulkDuplicating,
  onBulkDelete,
  isBulkDeleting,
  onExit,
}: DocumentsBulkBarProps) {
  const { t } = useTranslation(["documents", "common"]);
  const count = selectedDocuments.length;

  // Export requires a format valid for every selected document's type — the
  // menu offers the intersection (read access suffices, so no can* gate).
  const exportFormats = useMemo(
    () => documentSelectionFormats(selectedDocuments.map((d) => d.document_type)),
    [selectedDocuments]
  );

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-primary bg-primary/5 p-4">
      <div className="font-medium text-sm">{t("documents:bulk.selected", { count })}</div>
      <div className="flex flex-wrap items-center gap-2">
        {count > 0 &&
          (exportFormats.length > 0 ? (
            <ExportButton
              endpoint="/exports/document"
              params={{ document_ids: selectedDocuments.map((d) => d.id) }}
              formats={exportFormats}
              filenameStem={exportFilenameStem("documents", "documents")}
            />
          ) : (
            <Button variant="outline" size="sm" disabled title={t("documents:bulk.noCommonFormat")}>
              <FileDown className="h-4 w-4" />
              <span className="hidden sm:ml-2 sm:inline">{t("documents:bulk.export")}</span>
            </Button>
          ))}
        <Button
          variant="outline"
          size="sm"
          onClick={onBulkEditTags}
          disabled={count === 0 || !canEditSelectedDocuments}
          title={canEditSelectedDocuments ? undefined : t("documents:bulk.needEditAccessTags")}
        >
          <Tags className="h-4 w-4" />
          {t("documents:bulk.editTags")}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={onBulkEditAccess}
          disabled={count === 0 || !canEditSelectedDocuments}
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
          disabled={count === 0 || isBulkDuplicating || !canDuplicateSelectedDocuments}
          title={
            canDuplicateSelectedDocuments ? undefined : t("documents:bulk.needEditAccessDuplicate")
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
          disabled={count === 0 || isBulkDeleting || !canDeleteSelectedDocuments}
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
        {onExit && (
          <Button variant="ghost" size="sm" onClick={onExit}>
            {t("common:cancel")}
          </Button>
        )}
      </div>
    </div>
  );
}
