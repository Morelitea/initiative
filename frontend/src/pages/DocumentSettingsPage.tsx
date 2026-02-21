import { useEffect, useMemo, useState } from "react";
import { Link, useRouter, useParams } from "@tanstack/react-router";
import { formatDistanceToNow } from "date-fns";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/hooks/useAuth";
import { useDateLocale } from "@/hooks/useDateLocale";
import {
  useDocument,
  useSetDocumentCache,
  useUpdateDocument,
  useDeleteDocument,
  useDuplicateDocument,
  useCopyDocumentToInitiative,
} from "@/hooks/useDocuments";
import { useInitiatives } from "@/hooks/useInitiatives";
import { useGuildPath } from "@/lib/guildUrl";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { useSetDocumentTags } from "@/hooks/useTags";
import { DocumentSettingsDetailsTab } from "@/components/documents/settings/DocumentSettingsDetailsTab";
import { DocumentSettingsAccessTab } from "@/components/documents/settings/DocumentSettingsAccessTab";
import { DocumentSettingsAdvancedTab } from "@/components/documents/settings/DocumentSettingsAdvancedTab";
import { DocumentSettingsDialogs } from "@/components/documents/settings/DocumentSettingsDialogs";

export const DocumentSettingsPage = () => {
  const { t } = useTranslation(["documents", "common"]);
  const dateLocale = useDateLocale();
  const { documentId } = useParams({ strict: false }) as { documentId: string };
  const parsedId = Number(documentId);
  const router = useRouter();
  const setDocumentCache = useSetDocumentCache();
  const { user } = useAuth();
  const gp = useGuildPath();

  const [duplicateDialogOpen, setDuplicateDialogOpen] = useState(false);
  const [copyDialogOpen, setCopyDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [duplicateTitle, setDuplicateTitle] = useState("");
  const [copyTitle, setCopyTitle] = useState("");
  const [copyInitiativeId, setCopyInitiativeId] = useState("");
  const [isTemplate, setIsTemplate] = useState(false);
  const [documentTags, setDocumentTags] = useState<TagSummary[]>([]);

  const setDocumentTagsMutation = useSetDocumentTags();

  const documentQuery = useDocument(Number.isFinite(parsedId) ? parsedId : null);

  const document = documentQuery.data;

  const initiativesQuery = useInitiatives({ enabled: Boolean(document) && Boolean(user) });

  // Pure DAC: users with write or owner permission can manage the document
  const canManageDocument = useMemo(() => {
    if (!document || !user) {
      return false;
    }
    const myLevel = document.my_permission_level;
    return myLevel === "owner" || myLevel === "write";
  }, [document, user]);

  // Pure DAC: only owners can delete/duplicate documents
  const isOwner = useMemo(() => {
    if (!document || !user) {
      return false;
    }
    return document.my_permission_level === "owner";
  }, [document, user]);

  // Pure DAC: check if user has write access
  const hasWriteAccess = useMemo(() => {
    if (!document || !user) {
      return false;
    }
    const myLevel = document.my_permission_level;
    return myLevel === "owner" || myLevel === "write";
  }, [document, user]);

  const manageableInitiatives = useMemo(() => {
    const initiatives = initiativesQuery.data ?? [];
    if (!user) {
      return [];
    }
    if (user.role === "admin") {
      return initiatives;
    }
    return initiatives.filter((initiative) =>
      initiative.members.some(
        (member) => member.user.id === user.id && member.role === "project_manager"
      )
    );
  }, [initiativesQuery.data, user]);

  const copyableInitiatives = useMemo(() => {
    if (!document) {
      return [];
    }
    return manageableInitiatives.filter((initiative) => initiative.id !== document.initiative_id);
  }, [document, manageableInitiatives]);

  useEffect(() => {
    if (!document) {
      return;
    }
    setIsTemplate(document.is_template);
    setDuplicateTitle(t("settings.duplicateTitlePlaceholder", { title: document.title }));
    setCopyTitle(document.title);
    setDocumentTags(document.tags ?? []);
  }, [document, t]);

  useEffect(() => {
    if (!copyDialogOpen) {
      return;
    }
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

  // ── Page-level mutation hooks ──────────────────────────────────────────

  const duplicateDocumentMutation = useDuplicateDocument(parsedId, {
    onSuccess: (duplicated) => {
      toast.success(t("settings.documentDuplicated"));
      setDuplicateDialogOpen(false);
      router.navigate({
        to: gp(`/documents/${duplicated.id}`),
      });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("settings.duplicateError");
      toast.error(message);
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
      router.navigate({ to: gp(`/documents/${copied.id}`) });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("settings.copyError");
      toast.error(message);
    },
  });

  const deleteDocumentMutation = useDeleteDocument({
    onSuccess: () => {
      toast.success(t("settings.documentDeleted"));
      setDeleteDialogOpen(false);
      router.navigate({ to: gp("/documents") });
    },
    onError: () => {
      toast.error(t("settings.deleteError"));
    },
  });

  const updateTemplate = useUpdateDocument({
    onSuccess: (updated) => {
      setIsTemplate(updated.is_template);
      setDocumentCache(parsedId, updated);
    },
    onError: () => {
      toast.error(t("settings.templateError"));
    },
  });

  const handleTemplateToggle = (value: boolean) => {
    if (!document) {
      return;
    }
    const previous = isTemplate;
    setIsTemplate(value);
    updateTemplate.mutate(
      { documentId: document.id, data: { is_template: value } },
      {
        onError: () => setIsTemplate(previous),
      }
    );
  };

  const handleTagsChange = (newTags: TagSummary[]) => {
    setDocumentTags(newTags);
    setDocumentTagsMutation.mutate({
      documentId: parsedId,
      tagIds: newTags.map((tg) => tg.id),
    });
  };

  if (!Number.isFinite(parsedId)) {
    return <p className="text-destructive">{t("settings.invalidId")}</p>;
  }

  if (documentQuery.isLoading) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("settings.loading")}
      </div>
    );
  }

  if (documentQuery.isError || !document) {
    return <p className="text-destructive">{t("settings.notFound")}</p>;
  }

  return (
    <div className="space-y-6">
      <Breadcrumb>
        <BreadcrumbList>
          {document.initiative && (
            <>
              <BreadcrumbItem>
                <BreadcrumbLink asChild>
                  <Link to={gp(`/initiatives/${document.initiative.id}`)}>
                    {document.initiative.name}
                  </Link>
                </BreadcrumbLink>
              </BreadcrumbItem>
              <BreadcrumbSeparator />
            </>
          )}
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to={gp(`/documents/${document.id}`)}>{document.title}</Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>{t("settings.breadcrumb")}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-3xl font-semibold tracking-tight">{t("settings.title")}</h1>
          <p className="text-muted-foreground text-sm">{t("settings.subtitle")}</p>
        </div>
        <div className="text-muted-foreground flex flex-col items-end gap-2 text-right text-sm">
          <p className="font-medium">{document.title}</p>
          <p>
            {t("detail.updated", {
              date: formatDistanceToNow(new Date(document.updated_at), {
                addSuffix: true,
                locale: dateLocale,
              }),
            })}
          </p>
          {document.initiative ? (
            <span className="inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs">
              <InitiativeColorDot color={document.initiative.color} />
              {document.initiative.name}
            </span>
          ) : null}
        </div>
      </div>

      <Tabs defaultValue="details" className="space-y-4">
        <TabsList className="w-full max-w-xl justify-start">
          <TabsTrigger value="details">{t("settings.tabDetails")}</TabsTrigger>
          {canManageDocument ? (
            <TabsTrigger value="access">{t("settings.tabAccess")}</TabsTrigger>
          ) : null}
          <TabsTrigger value="advanced">{t("settings.tabAdvanced")}</TabsTrigger>
        </TabsList>

        {/* -- Details tab -- */}
        <DocumentSettingsDetailsTab
          isTemplate={isTemplate}
          onTemplateToggle={handleTemplateToggle}
          templateToggleDisabled={!hasWriteAccess || updateTemplate.isPending}
          hasWriteAccess={hasWriteAccess}
          documentTags={documentTags}
          onTagsChange={handleTagsChange}
        />

        {/* -- Access tab -- */}
        {canManageDocument ? (
          <DocumentSettingsAccessTab document={document} documentId={parsedId} />
        ) : null}

        {/* -- Advanced tab -- */}
        <DocumentSettingsAdvancedTab
          canManageDocument={canManageDocument}
          isOwner={isOwner}
          onDuplicateClick={() => {
            setDuplicateDialogOpen(true);
            setDuplicateTitle(t("settings.duplicateTitlePlaceholder", { title: document.title }));
          }}
          onCopyClick={() => {
            setCopyDialogOpen(true);
            setCopyTitle(document.title);
          }}
          onDeleteClick={() => setDeleteDialogOpen(true)}
        />
      </Tabs>

      <DocumentSettingsDialogs
        documentTitle={document.title}
        // Duplicate dialog
        duplicateDialogOpen={duplicateDialogOpen}
        onDuplicateDialogOpenChange={setDuplicateDialogOpen}
        duplicateTitle={duplicateTitle}
        onDuplicateTitleChange={setDuplicateTitle}
        onDuplicate={(title) => duplicateDocumentMutation.mutate({ title })}
        isDuplicating={duplicateDocumentMutation.isPending}
        // Copy dialog
        copyDialogOpen={copyDialogOpen}
        onCopyDialogOpenChange={setCopyDialogOpen}
        copyTitle={copyTitle}
        onCopyTitleChange={setCopyTitle}
        copyInitiativeId={copyInitiativeId}
        onCopyInitiativeIdChange={setCopyInitiativeId}
        onCopy={(initiativeId, title) =>
          copyDocumentMutation.mutate({
            target_initiative_id: Number(initiativeId),
            title,
          })
        }
        isCopying={copyDocumentMutation.isPending}
        copyableInitiatives={copyableInitiatives}
        isLoadingInitiatives={initiativesQuery.isLoading}
        // Delete dialog
        deleteDialogOpen={deleteDialogOpen}
        onDeleteDialogOpenChange={setDeleteDialogOpen}
        onDelete={() => deleteDocumentMutation.mutate([parsedId])}
        isDeleting={deleteDocumentMutation.isPending}
      />
    </div>
  );
};
