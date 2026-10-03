import { useParams } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { DocumentSettingsDetailsTab } from "@/components/documents/settings/DocumentSettingsDetailsTab";
import { useDocumentExportOptions } from "@/components/documents/useDocumentExportOptions";
import { loadWhiteboardSceneFromContent } from "@/components/documents/whiteboardSceneCache";
import { ToolSettingsLayout } from "@/components/tools/settings/ToolSettingsLayout";
import {
  useDeleteDocument,
  useDocument,
  useSetDocumentCache,
  useSetDocumentGrants,
  useUpdateDocument,
} from "@/hooks/useDocuments";
import { toast } from "@/lib/chesterToast";

export const DocumentSettingsPage = () => {
  const { t } = useTranslation(["documents", "common"]);
  const { documentId } = useParams({ strict: false }) as { documentId?: string };
  const parsedId = documentId ? Number(documentId) : Number.NaN;
  const isValidId = Number.isFinite(parsedId);
  const setDocumentCache = useSetDocumentCache();

  const [isTemplate, setIsTemplate] = useState(false);

  const documentQuery = useDocument(isValidId ? parsedId : null);
  const document = documentQuery.data;

  const setGrants = useSetDocumentGrants(parsedId);
  const remove = useDeleteDocument();

  const canManageDocument = Boolean(document?.can.edit);

  // A whiteboard's pictures are drawn from the scene the server holds; the
  // editor has saved it by the time anybody is here.
  const exportOptions = useDocumentExportOptions(
    document?.document_type ?? "native",
    document?.name ?? "",
    document?.document_type === "whiteboard"
      ? loadWhiteboardSceneFromContent(document.content)
      : undefined
  );

  useEffect(() => {
    if (!document) return;
    setIsTemplate(document.is_template);
  }, [document]);

  const updateTemplate = useUpdateDocument(parsedId, {
    onSuccess: (updated) => {
      setIsTemplate(updated.is_template);
      setDocumentCache(parsedId, updated);
    },
    onError: () => {
      toast.error(t("settings.templateError"));
    },
  });

  const handleTemplateToggle = (value: boolean) => {
    const previous = isTemplate;
    setIsTemplate(value);
    updateTemplate.mutate({ is_template: value }, { onError: () => setIsTemplate(previous) });
  };

  return (
    <ToolSettingsLayout
      tool={Tool.document}
      // A document's name is edited in the editor rather than here, and it
      // carries no description field.
      entity={document}
      isLoading={isValidId && documentQuery.isLoading}
      isError={!isValidId || documentQuery.isError}
      setGrants={setGrants}
      remove={remove}
      detailsExtra={
        <DocumentSettingsDetailsTab
          isTemplate={isTemplate}
          onTemplateToggle={handleTemplateToggle}
          templateToggleDisabled={!canManageDocument || updateTemplate.isPending}
        />
      }
      exportOptions={exportOptions}
    />
  );
};
