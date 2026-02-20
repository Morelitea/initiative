import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { getItem, setItem } from "@/lib/storage";
import { Loader2, Link, Unlink, ChevronDown, ChevronUp, FilePlus } from "lucide-react";
import { toast } from "sonner";
import { formatDistanceToNow } from "date-fns";
import { useInitiativeDocuments } from "@/hooks/useDocuments";
import { useAttachProjectDocument, useDetachProjectDocument } from "@/hooks/useProjects";
import { useDateLocale } from "@/hooks/useDateLocale";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import { DocumentCard } from "@/components/documents/DocumentCard";
import { CreateDocumentDialog } from "@/components/documents/CreateDocumentDialog";
import {
  Carousel,
  CarouselContent,
  CarouselItem,
  CarouselNext,
  CarouselPrevious,
} from "@/components/ui/carousel";
import type { DocumentSummary } from "@/api/generated/initiativeAPI.schemas";
import type { ProjectDocumentSummary } from "@/api/generated/initiativeAPI.schemas";

type ProjectDocumentsSectionProps = {
  projectId: number;
  initiativeId: number;
  documents: ProjectDocumentSummary[];
  canCreate: boolean;
  canAttach: boolean;
};

export const ProjectDocumentsSection = ({
  projectId,
  initiativeId,
  documents,
  canCreate,
  canAttach,
}: ProjectDocumentsSectionProps) => {
  const { t } = useTranslation("projects");
  const dateLocale = useDateLocale();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [selectedDocumentId, setSelectedDocumentId] = useState<string>("");
  const storageKey = `project:${projectId}:documentsCollapsed`;
  const [isCollapsed, setIsCollapsed] = useState<boolean>(() => {
    return getItem(storageKey) === "true";
  });

  const initiativeDocsQuery = useInitiativeDocuments(initiativeId);

  const attachedDocumentIds = useMemo(
    () => new Set(documents.map((doc) => doc.document_id)),
    [documents]
  );

  const attachMutation = useAttachProjectDocument(projectId, {
    onSuccess: () => {
      toast.success(t("documents.attached"));
      setDialogOpen(false);
      setSelectedDocumentId("");
    },
  });

  const detachMutation = useDetachProjectDocument(projectId, {
    onSuccess: () => {
      toast.success(t("documents.detached"));
    },
  });

  const initiativeDocuments = useMemo(
    () => initiativeDocsQuery.data ?? [],
    [initiativeDocsQuery.data]
  );

  const documentsById = useMemo(() => {
    const map = new Map<number, DocumentSummary>();
    initiativeDocuments.forEach((doc) => map.set(doc.id, doc));
    return map;
  }, [initiativeDocuments]);

  const availableDocs = useMemo(() => {
    return initiativeDocuments.filter((doc) => !attachedDocumentIds.has(doc.id));
  }, [initiativeDocuments, attachedDocumentIds]);

  const comboboxItems = useMemo(
    () =>
      availableDocs.map((doc) => ({
        value: String(doc.id),
        label: doc.title,
      })),
    [availableDocs]
  );

  return (
    <Collapsible
      open={!isCollapsed}
      onOpenChange={(open) => {
        setIsCollapsed(!open);
        setItem(storageKey, (!open).toString());
      }}
      className="bg-card space-y-4 rounded-2xl border p-5 shadow-sm"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="inline-flex items-center gap-2">
            <h2 className="text-xl font-semibold">{t("documents.title")}</h2>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-8 w-8 rounded-full"
              onClick={() => {
                setIsCollapsed((prev) => {
                  const next = !prev;
                  setItem(storageKey, next.toString());
                  return next;
                });
              }}
              aria-label={
                isCollapsed ? t("documents.expandDocuments") : t("documents.collapseDocuments")
              }
            >
              {isCollapsed ? (
                <ChevronDown className="h-4 w-4" />
              ) : (
                <ChevronUp className="h-4 w-4" />
              )}
            </Button>
          </div>
          <p className="text-muted-foreground text-sm">{t("documents.description")}</p>
        </div>
        {(canCreate || canAttach) && (
          <div className="flex items-center gap-2">
            {canCreate && (
              <Button type="button" size="sm" onClick={() => setCreateDialogOpen(true)}>
                <FilePlus className="mr-2 h-4 w-4" />
                {t("documents.newDocument")}
              </Button>
            )}
            {canAttach && (
              <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
                <DialogTrigger asChild>
                  <Button type="button" size="sm" variant="outline">
                    <Link className="mr-2 h-4 w-4" />
                    {t("documents.attachExisting")}
                  </Button>
                </DialogTrigger>
                <DialogContent className="bg-card max-h-screen w-full max-w-lg overflow-y-auto rounded-2xl border shadow-2xl">
                  <DialogHeader>
                    <DialogTitle>{t("documents.attachDocument")}</DialogTitle>
                    <DialogDescription>{t("documents.attachDialogDescription")}</DialogDescription>
                  </DialogHeader>
                  <div className="space-y-4">
                    <div className="space-y-2">
                      <SearchableCombobox
                        items={comboboxItems}
                        value={selectedDocumentId}
                        onValueChange={(value) => setSelectedDocumentId(value)}
                        placeholder={
                          initiativeDocsQuery.isLoading
                            ? t("documents.loadingDocuments")
                            : t("documents.chooseDocument")
                        }
                        emptyMessage={
                          availableDocs.length === 0
                            ? t("documents.allAttached")
                            : t("documents.noMatchesFound")
                        }
                        buttonClassName="justify-between"
                      />
                      <p className="text-muted-foreground text-xs">{t("documents.attachHint")}</p>
                    </div>
                  </div>
                  <DialogFooter>
                    <Button
                      type="button"
                      onClick={() => attachMutation.mutate(Number(selectedDocumentId))}
                      disabled={
                        attachMutation.isPending ||
                        !selectedDocumentId ||
                        availableDocs.length === 0
                      }
                    >
                      {attachMutation.isPending ? (
                        <>
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          {t("documents.attaching")}
                        </>
                      ) : (
                        t("documents.attach")
                      )}
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            )}
          </div>
        )}
      </div>

      <CreateDocumentDialog
        open={createDialogOpen}
        onOpenChange={setCreateDialogOpen}
        initiativeId={initiativeId}
        projectId={projectId}
      />

      <CollapsibleContent className="space-y-4 data-[state=closed]:hidden">
        {documents.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            {t("documents.noDocuments")} {canAttach ? t("documents.noDocumentsHint") : ""}
          </p>
        ) : (
          <Carousel className="relative">
            <CarouselContent className="-ml-4">
              {documents.map((doc) => {
                const summary =
                  documentsById.get(doc.document_id) ?? createFallbackSummary(doc, initiativeId);
                return (
                  <CarouselItem
                    key={doc.document_id}
                    className="pl-4 sm:basis-1/2 lg:basis-1/3 xl:basis-1/4 2xl:basis-1/5"
                  >
                    <div className="space-y-2">
                      <div className="relative">
                        <DocumentCard document={summary} hideInitiative />
                        {canAttach ? (
                          <Button
                            variant="secondary"
                            size="icon"
                            className="bg-background/90 text-foreground absolute top-3 right-3 z-10 rounded-full shadow-md"
                            onClick={(event) => {
                              event.preventDefault();
                              event.stopPropagation();
                              detachMutation.mutate(doc.document_id);
                            }}
                            disabled={detachMutation.isPending}
                            aria-label={t("documents.detachDocument")}
                          >
                            {detachMutation.isPending ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <Unlink className="h-4 w-4" />
                            )}
                          </Button>
                        ) : null}
                      </div>
                      <div className="text-muted-foreground text-xs">
                        {t("documents.attachedAgo", {
                          time: formatDistanceToNow(new Date(doc.attached_at), {
                            locale: dateLocale,
                          }),
                        })}
                      </div>
                    </div>
                  </CarouselItem>
                );
              })}
            </CarouselContent>
            <CarouselPrevious className="left-0 -translate-x-1/2" />
            <CarouselNext className="right-0 translate-x-1/2" />
          </Carousel>
        )}
      </CollapsibleContent>
    </Collapsible>
  );
};

const createFallbackSummary = (
  doc: ProjectDocumentSummary,
  initiativeId: number
): DocumentSummary => ({
  id: doc.document_id,
  initiative_id: initiativeId,
  title: doc.title,
  featured_image_url: null,
  created_by_id: 0,
  updated_by_id: 0,
  created_at: doc.updated_at,
  updated_at: doc.updated_at,
  initiative: null,
  projects: [],
  is_template: false,
  comment_count: 0,
  permissions: [],
  role_permissions: [],
  tags: [],
  document_type: "native",
  file_url: null,
  file_content_type: null,
  file_size: null,
  original_filename: null,
  my_permission_level: null,
});
