import { useParams } from "@tanstack/react-router";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { useDocumentExportOptions } from "@/components/documents/useDocumentExportOptions";
import { loadWhiteboardSceneFromContent } from "@/components/documents/whiteboardSceneCache";
import { ToolSettingsLayout } from "@/components/tools/settings/ToolSettingsLayout";
import {
  useDeleteDocument,
  useDocument,
  useSetDocumentGrants,
  useUpdateDocument,
} from "@/hooks/useDocuments";

export const DocumentSettingsPage = () => {
  const { documentId } = useParams({ strict: false }) as { documentId?: string };
  const parsedId = documentId ? Number(documentId) : Number.NaN;
  const isValidId = Number.isFinite(parsedId);

  const documentQuery = useDocument(isValidId ? parsedId : null);
  const document = documentQuery.data;

  const template = useUpdateDocument(parsedId);
  const setGrants = useSetDocumentGrants(parsedId);
  const remove = useDeleteDocument();

  // A whiteboard's pictures are drawn from the scene the server holds; the
  // editor has saved it by the time anybody is here.
  const exportOptions = useDocumentExportOptions(
    document?.document_type ?? "native",
    document?.name ?? "",
    document?.document_type === "whiteboard"
      ? loadWhiteboardSceneFromContent(document.content)
      : undefined
  );

  return (
    <ToolSettingsLayout
      tool={Tool.document}
      // A document's name is edited in the editor rather than here, and it
      // carries no description field.
      entity={document}
      isLoading={isValidId && documentQuery.isLoading}
      isError={!isValidId || documentQuery.isError}
      template={template}
      setGrants={setGrants}
      remove={remove}
      exportOptions={exportOptions}
    />
  );
};
