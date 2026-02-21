import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { setDocumentTagsApiV1DocumentsDocumentIdTagsPut } from "@/api/generated/documents/documents";
import { invalidateAllDocuments } from "@/api/query-keys";
import { BulkEditTagsDialog as GenericBulkEditTagsDialog } from "@/components/shared/BulkEditTagsDialog";
import type { DocumentSummary } from "@/api/generated/initiativeAPI.schemas";
import type { DialogWithSuccessProps } from "@/types/dialog";

interface BulkEditDocumentTagsDialogProps extends DialogWithSuccessProps {
  documents: DocumentSummary[];
}

export function BulkEditTagsDialog({ documents, ...dialogProps }: BulkEditDocumentTagsDialogProps) {
  const { t } = useTranslation(["documents", "common"]);

  const labels = useMemo(
    () => ({
      title: t("bulkTags.title"),
      descriptionAdd: t("bulkTags.descriptionAdd", { count: documents.length }),
      descriptionRemove: t("bulkTags.descriptionRemove", { count: documents.length }),
      tabAdd: t("bulkTags.tabAdd"),
      tabRemove: t("bulkTags.tabRemove"),
      addPlaceholder: t("bulkTags.addPlaceholder"),
      removePlaceholder: t("bulkTags.removePlaceholder"),
      noTags: t("bulkTags.noTags"),
      tagsAdded: t("bulkTags.tagsAdded", { count: documents.length }),
      tagsRemoved: t("bulkTags.tagsRemoved", { count: documents.length }),
      applying: t("bulkTags.applying"),
      apply: t("bulkTags.apply"),
      cancel: t("common:cancel"),
      updateError: t("bulkTags.updateError"),
    }),
    [t, documents.length]
  );

  return (
    <GenericBulkEditTagsDialog
      {...dialogProps}
      items={documents}
      setTags={(docId, tagIds) =>
        setDocumentTagsApiV1DocumentsDocumentIdTagsPut(docId, { tag_ids: tagIds })
      }
      onInvalidate={() => void invalidateAllDocuments()}
      labels={labels}
    />
  );
}
