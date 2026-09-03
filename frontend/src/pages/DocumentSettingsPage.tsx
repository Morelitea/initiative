import { useParams, useRouter } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { DocumentSettingsAdvancedTab } from "@/components/documents/settings/DocumentSettingsAdvancedTab";
import { DocumentSettingsDetailsTab } from "@/components/documents/settings/DocumentSettingsDetailsTab";
import { DocumentSettingsDialogs } from "@/components/documents/settings/DocumentSettingsDialogs";
import { ToolSettingsLayout } from "@/components/tools/settings/ToolSettingsLayout";
import {
  useCopyDocumentToInitiative,
  useDeleteDocument,
  useDocument,
  useDuplicateDocument,
  useSetDocumentCache,
  useSetDocumentGrants,
  useUpdateDocument,
} from "@/hooks/useDocuments";
import { useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import { useInitiatives } from "@/hooks/useInitiatives";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { useGuildPath } from "@/lib/guildUrl";
import { hasWriteAccess } from "@/lib/permissions";
import { toolDetailRoute } from "@/lib/tools";

export const DocumentSettingsPage = () => {
  const { t } = useTranslation(["documents", "common"]);
  const { documentId } = useParams({ strict: false }) as { documentId?: string };
  const parsedId = documentId ? Number(documentId) : Number.NaN;
  const isValidId = Number.isFinite(parsedId);
  const router = useRouter();
  const gp = useGuildPath();
  const setDocumentCache = useSetDocumentCache();

  const [duplicateDialogOpen, setDuplicateDialogOpen] = useState(false);
  const [copyDialogOpen, setCopyDialogOpen] = useState(false);
  const [duplicateTitle, setDuplicateTitle] = useState("");
  const [copyTitle, setCopyTitle] = useState("");
  const [copyInitiativeId, setCopyInitiativeId] = useState("");
  const [isTemplate, setIsTemplate] = useState(false);

  const documentQuery = useDocument(isValidId ? parsedId : null);
  const document = documentQuery.data;

  const setGrants = useSetDocumentGrants(parsedId);
  const remove = useDeleteDocument();

  const canManageDocument = hasWriteAccess(document?.my_permission_level);

  const initiativesQuery = useInitiatives({ enabled: Boolean(document) });

  // Copying creates a document in the target initiative, so the target list is
  // the initiatives whose server-computed create flag is on — minus the one the
  // document is already in.
  const { creatableInitiatives } = useToolCreateAccess(Tool.document, {
    enabled: Boolean(document),
  });

  const copyableInitiatives = useMemo(() => {
    if (!document) return [];
    return creatableInitiatives.filter((initiative) => initiative.id !== document.initiative_id);
  }, [document, creatableInitiatives]);

  useEffect(() => {
    if (!document) return;
    setIsTemplate(document.is_template);
    setDuplicateTitle(t("settings.duplicateTitlePlaceholder", { title: document.name }));
    setCopyTitle(document.name);
  }, [document, t]);

  useEffect(() => {
    if (!copyDialogOpen) return;
    if (copyableInitiatives.length === 0) {
      setCopyInitiativeId("");
      return;
    }
    const currentIsValid = copyableInitiatives.some(
      (initiative) => String(initiative.id) === copyInitiativeId
    );
    if (!currentIsValid) {
      setCopyInitiativeId(String(copyableInitiatives[0].id));
    }
  }, [copyDialogOpen, copyableInitiatives, copyInitiativeId]);

  const duplicateDocumentMutation = useDuplicateDocument(parsedId, {
    onSuccess: (duplicated) => {
      toast.success(t("settings.documentDuplicated"));
      setDuplicateDialogOpen(false);
      router.navigate({
        to: gp(toolDetailRoute(Tool.document, duplicated.initiative_id, duplicated.id)),
      });
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "documents:settings.duplicateError"));
    },
  });

  const copyDocumentMutation = useCopyDocumentToInitiative(parsedId, {
    onSuccess: (copied) => {
      toast.success(
        t("settings.documentCopied", {
          initiative:
            copyableInitiatives.find((i) => String(i.id) === copyInitiativeId)?.name ?? "",
        })
      );
      setCopyDialogOpen(false);
      router.navigate({ to: gp(toolDetailRoute(Tool.document, copied.initiative_id, copied.id)) });
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "documents:settings.copyError"));
    },
  });

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
      advancedExtra={
        document ? (
          <DocumentSettingsAdvancedTab
            canManageDocument={canManageDocument}
            onDuplicateClick={() => {
              setDuplicateDialogOpen(true);
              setDuplicateTitle(t("settings.duplicateTitlePlaceholder", { title: document.name }));
            }}
            onCopyClick={() => {
              setCopyDialogOpen(true);
              setCopyTitle(document.name);
            }}
          />
        ) : null
      }
    >
      {document && (
        <DocumentSettingsDialogs
          documentTitle={document.name}
          duplicateDialogOpen={duplicateDialogOpen}
          onDuplicateDialogOpenChange={setDuplicateDialogOpen}
          duplicateTitle={duplicateTitle}
          onDuplicateTitleChange={setDuplicateTitle}
          onDuplicate={(title) => duplicateDocumentMutation.mutate({ name: title })}
          isDuplicating={duplicateDocumentMutation.isPending}
          copyDialogOpen={copyDialogOpen}
          onCopyDialogOpenChange={setCopyDialogOpen}
          copyTitle={copyTitle}
          onCopyTitleChange={setCopyTitle}
          copyInitiativeId={copyInitiativeId}
          onCopyInitiativeIdChange={setCopyInitiativeId}
          onCopy={(initiativeId, title) =>
            copyDocumentMutation.mutate({
              target_initiative_id: Number(initiativeId),
              name: title,
            })
          }
          isCopying={copyDocumentMutation.isPending}
          copyableInitiatives={copyableInitiatives}
          isLoadingInitiatives={initiativesQuery.isLoading}
        />
      )}
    </ToolSettingsLayout>
  );
};
