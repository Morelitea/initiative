import { type ChangeEvent, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { FileSpreadsheet, FileText, Loader2, Plus, Presentation, Upload, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import {
  copyDocumentApiV1DocumentsDocumentIdCopyPost,
  createDocumentApiV1DocumentsPost,
  getListDocumentsApiV1DocumentsGetQueryKey,
  listDocumentsApiV1DocumentsGet,
  uploadDocumentFileApiV1DocumentsUploadPost,
} from "@/api/generated/documents/documents";
import {
  getGetInitiativeApiV1InitiativesInitiativeIdGetQueryKey,
  getInitiativeApiV1InitiativesInitiativeIdGet,
} from "@/api/generated/initiatives/initiatives";
import { attachProjectDocumentApiV1ProjectsProjectIdDocumentsDocumentIdPost } from "@/api/generated/projects/projects";
import { apiClient } from "@/api/client";
import { invalidateAllDocuments, invalidateProject } from "@/api/query-keys";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import {
  CreateAccessControl,
  type RoleGrant,
  type UserGrant,
} from "@/components/access/CreateAccessControl";
import { formatBytes, getFileTypeLabel } from "@/lib/fileUtils";
import type { DocumentRead, DocumentSummary, Initiative } from "@/types/api";

type CreateDocumentDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** If provided, the initiative is locked and cannot be changed */
  initiativeId?: number;
  /** If provided, pre-selects this initiative (but user can change it) */
  defaultInitiativeId?: number;
  /** If provided, the created document will be auto-attached to this project */
  projectId?: number;
  /** Called after successful creation/upload */
  onSuccess?: (document: DocumentRead) => void;
  /** List of initiatives user can create documents in (required if initiativeId not provided) */
  initiatives?: Initiative[];
};

export const CreateDocumentDialog = ({
  open,
  onOpenChange,
  initiativeId,
  defaultInitiativeId,
  projectId,
  onSuccess,
  initiatives = [],
}: CreateDocumentDialogProps) => {
  const { t } = useTranslation(["documents", "common"]);

  const [createDialogTab, setCreateDialogTab] = useState<"new" | "upload">("new");
  const [newTitle, setNewTitle] = useState("");
  const [selectedInitiativeId, setSelectedInitiativeId] = useState(
    defaultInitiativeId ? String(defaultInitiativeId) : ""
  );
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [isTemplateDocument, setIsTemplateDocument] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [roleGrants, setRoleGrants] = useState<RoleGrant[]>([]);
  const [userGrants, setUserGrants] = useState<UserGrant[]>([]);
  const [accessLoading, setAccessLoading] = useState(false);

  // Determine effective initiative ID
  const effectiveInitiativeId =
    initiativeId ?? (selectedInitiativeId ? Number(selectedInitiativeId) : null);

  // Find the locked initiative for display (from passed list or fetch if needed)
  const lockedInitiativeFromList = useMemo(() => {
    if (!initiativeId) return null;
    return initiatives.find((i) => i.id === initiativeId) ?? null;
  }, [initiativeId, initiatives]);

  // Query the initiative if we have an ID but it's not in the passed list
  const initiativeQuery = useQuery<Initiative>({
    queryKey: getGetInitiativeApiV1InitiativesInitiativeIdGetQueryKey(initiativeId!),
    queryFn: () =>
      getInitiativeApiV1InitiativesInitiativeIdGet(initiativeId!) as unknown as Promise<Initiative>,
    enabled: open && !!initiativeId && !lockedInitiativeFromList,
  });

  const lockedInitiative = lockedInitiativeFromList ?? initiativeQuery.data ?? null;

  // Query templates
  const templateDocumentsQuery = useQuery<DocumentSummary[]>({
    queryKey: getListDocumentsApiV1DocumentsGetQueryKey({ page_size: 0 }),
    queryFn: async () => {
      const response = await (listDocumentsApiV1DocumentsGet({
        page_size: 0,
      }) as unknown as Promise<{ items: DocumentSummary[] }>);
      return response.items;
    },
    enabled: open,
  });

  // Filter templates — backend already enforces access control via RLS
  const manageableTemplates = useMemo(() => {
    if (!templateDocumentsQuery.data) return [];
    return templateDocumentsQuery.data.filter((doc) => doc.is_template);
  }, [templateDocumentsQuery.data]);

  // Reset form when dialog closes, or set default initiative when dialog opens
  useEffect(() => {
    if (open) {
      // When dialog opens, set the default initiative if provided
      if (defaultInitiativeId) {
        setSelectedInitiativeId(String(defaultInitiativeId));
      }
    } else {
      // When dialog closes, reset the form
      setNewTitle("");
      setSelectedInitiativeId(defaultInitiativeId ? String(defaultInitiativeId) : "");
      setSelectedTemplateId("");
      setIsTemplateDocument(false);
      setSelectedFile(null);
      setCreateDialogTab("new");
      setRoleGrants([]);
      setUserGrants([]);
    }
  }, [open, defaultInitiativeId]);

  // Clear template when "save as template" is toggled on
  useEffect(() => {
    if (isTemplateDocument && selectedTemplateId) {
      setSelectedTemplateId("");
    }
  }, [isTemplateDocument, selectedTemplateId]);

  // Validate selected template still exists
  useEffect(() => {
    if (!selectedTemplateId) return;
    const isValid = manageableTemplates.some((doc) => String(doc.id) === selectedTemplateId);
    if (!isValid) setSelectedTemplateId("");
  }, [manageableTemplates, selectedTemplateId]);

  // Helper to apply role + user permissions via follow-up API calls.
  // Used for copy-from-template and upload paths where the create payload can't carry them.
  // Returns the count of failed permission calls so callers can warn the user.
  //
  // Note: cross-initiative role grants are handled differently per path:
  // - Direct create (POST /documents/): backend silently drops invalid roles (no error).
  // - Copy/upload paths (this helper): individual POST calls return 400, counted as failures.
  // This inconsistency is cosmetic — CreateAccessControl filters to valid roles in the UI.
  const applyDocumentPermissions = async (documentId: number): Promise<number> => {
    let failures = 0;
    for (const rg of roleGrants) {
      try {
        await apiClient.post(`/documents/${documentId}/role-permissions`, {
          initiative_role_id: rg.initiative_role_id,
          level: rg.level,
        });
      } catch {
        failures++;
      }
    }
    // Batch user grants by level to use bulk endpoint
    const byLevel = new Map<string, number[]>();
    for (const ug of userGrants) {
      const arr = byLevel.get(ug.level) ?? [];
      arr.push(ug.user_id);
      byLevel.set(ug.level, arr);
    }
    for (const [level, userIds] of byLevel) {
      try {
        await apiClient.post(`/documents/${documentId}/members/bulk`, {
          user_ids: userIds,
          level,
        });
      } catch {
        failures++;
      }
    }
    return failures;
  };

  const createDocument = useMutation({
    mutationFn: async () => {
      const trimmedTitle = newTitle.trim();
      if (!trimmedTitle) throw new Error(t("create.titleRequired"));
      if (!effectiveInitiativeId) throw new Error(t("create.initiativeRequired"));

      let newDocument: DocumentRead;
      let permissionFailures = 0;

      if (selectedTemplateId) {
        newDocument = await (copyDocumentApiV1DocumentsDocumentIdCopyPost(
          Number(selectedTemplateId),
          { target_initiative_id: effectiveInitiativeId, title: trimmedTitle }
        ) as unknown as Promise<DocumentRead>);
      } else {
        newDocument = await (createDocumentApiV1DocumentsPost({
          title: trimmedTitle,
          initiative_id: effectiveInitiativeId,
          is_template: isTemplateDocument,
        }) as unknown as Promise<DocumentRead>);
      }

      // Auto-attach to project if specified
      if (projectId) {
        await attachProjectDocumentApiV1ProjectsProjectIdDocumentsDocumentIdPost(
          projectId,
          newDocument.id
        );
      }

      return { document: newDocument, permissionFailures };
    },
    onSuccess: ({ document, permissionFailures: failures }) => {
      toast.success(projectId ? t("create.createdAttached") : t("create.created"));
      if (failures > 0) {
        toast.warning(t("create.somePermissionsFailed"));
      }
      onOpenChange(false);
      void invalidateAllDocuments();
      if (projectId) {
        void invalidateProject(projectId);
      }
      onSuccess?.(document);
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("create.createError");
      toast.error(message);
    },
  });

  const uploadDocument = useMutation({
    mutationFn: async () => {
      if (!selectedFile) throw new Error(t("create.fileRequired"));
      const trimmedTitle = newTitle.trim();
      if (!trimmedTitle) throw new Error(t("create.titleRequired"));
      if (!effectiveInitiativeId) throw new Error(t("create.initiativeRequired"));

      const newDocument = await (uploadDocumentFileApiV1DocumentsUploadPost({
        file: selectedFile,
        title: trimmedTitle,
        initiative_id: effectiveInitiativeId,
      }) as unknown as Promise<DocumentRead>);

      // Apply permissions before project-attach so they're always applied
      // even if the attach call fails
      const permissionFailures = await applyDocumentPermissions(newDocument.id);

      // Auto-attach to project if specified
      if (projectId) {
        await attachProjectDocumentApiV1ProjectsProjectIdDocumentsDocumentIdPost(
          projectId,
          newDocument.id
        );
      }

      return { document: newDocument, permissionFailures };
    },
    onSuccess: ({ document, permissionFailures: failures }) => {
      toast.success(projectId ? t("create.uploadedAttached") : t("create.uploaded"));
      if (failures > 0) {
        toast.warning(t("create.somePermissionsFailed"));
      }
      onOpenChange(false);
      void invalidateAllDocuments();
      if (projectId) {
        void invalidateProject(projectId);
      }
      onSuccess?.(document);
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("create.uploadError");
      toast.error(message);
    },
  });

  const handleFileSelect = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      const maxSize = 50 * 1024 * 1024;
      if (file.size > maxSize) {
        toast.error(t("create.fileTooLarge"));
        e.target.value = "";
        return;
      }
      setSelectedFile(file);
      if (!newTitle.trim()) {
        const nameWithoutExt = file.name.replace(/\.[^/.]+$/, "");
        setNewTitle(nameWithoutExt);
      }
    }
    e.target.value = "";
  };

  const isCreating = createDocument.isPending || uploadDocument.isPending;
  const canSubmitNew = newTitle.trim() && effectiveInitiativeId && !isCreating;
  const canSubmitUpload = newTitle.trim() && effectiveInitiativeId && selectedFile && !isCreating;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-card max-h-screen w-full max-w-lg overflow-y-auto rounded-2xl border shadow-2xl">
        <DialogHeader>
          <DialogTitle>{t("create.title")}</DialogTitle>
          <DialogDescription>
            {projectId ? t("create.descriptionAttach") : t("create.descriptionStandalone")}
          </DialogDescription>
        </DialogHeader>

        <Tabs
          value={createDialogTab}
          onValueChange={(value) => setCreateDialogTab(value as "new" | "upload")}
        >
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="new" className="flex items-center gap-2">
              <Plus className="h-4 w-4" />
              {t("create.tabNew")}
            </TabsTrigger>
            <TabsTrigger value="upload" className="flex items-center gap-2">
              <Upload className="h-4 w-4" />
              {t("create.tabUpload")}
            </TabsTrigger>
          </TabsList>

          {/* Shared fields: Title and Initiative */}
          <div className="mt-4 space-y-4">
            <div className="space-y-2">
              <Label htmlFor="create-doc-title">{t("create.titleLabel")}</Label>
              <Input
                id="create-doc-title"
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                placeholder={
                  createDialogTab === "upload"
                    ? t("create.titlePlaceholderStandalone")
                    : t("create.titlePlaceholderAttach")
                }
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="create-doc-initiative">{t("create.initiativeLabel")}</Label>
              {initiativeId ? (
                <div className="rounded-md border px-3 py-2 text-sm">
                  {lockedInitiative?.name ?? t("create.selectInitiative")}
                </div>
              ) : (
                <Select value={selectedInitiativeId} onValueChange={setSelectedInitiativeId}>
                  <SelectTrigger id="create-doc-initiative">
                    <SelectValue placeholder={t("create.selectInitiative")} />
                  </SelectTrigger>
                  <SelectContent>
                    {initiatives.map((initiative) => (
                      <SelectItem key={initiative.id} value={String(initiative.id)}>
                        {initiative.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
          </div>

          {/* New document tab content */}
          <TabsContent value="new" className="mt-4 space-y-4">
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="create-doc-template">{t("create.templateLabel")}</Label>
                {selectedTemplateId && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-auto px-2 py-1 text-xs"
                    onClick={() => setSelectedTemplateId("")}
                  >
                    <X className="mr-1 h-3 w-3" />
                    {t("create.clear")}
                  </Button>
                )}
              </div>
              <Select
                value={selectedTemplateId || undefined}
                onValueChange={setSelectedTemplateId}
                disabled={
                  templateDocumentsQuery.isLoading ||
                  manageableTemplates.length === 0 ||
                  isTemplateDocument
                }
              >
                <SelectTrigger id="create-doc-template">
                  <SelectValue
                    placeholder={
                      templateDocumentsQuery.isLoading
                        ? t("create.loadingTemplates")
                        : manageableTemplates.length > 0
                          ? t("create.selectTemplate")
                          : t("create.noTemplates")
                    }
                  />
                </SelectTrigger>
                <SelectContent>
                  {manageableTemplates.map((template) => (
                    <SelectItem key={template.id} value={String(template.id)}>
                      {template.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="bg-muted/40 flex flex-col gap-2 rounded-lg border p-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-sm font-medium">{t("create.saveAsTemplate")}</p>
                <p className="text-muted-foreground text-xs">{t("create.templateDescription")}</p>
              </div>
              <Switch
                id="create-doc-is-template"
                checked={isTemplateDocument}
                onCheckedChange={setIsTemplateDocument}
                aria-label={t("create.templateToggle")}
              />
            </div>
          </TabsContent>

          {/* Upload file tab content */}
          <TabsContent value="upload" className="mt-4 space-y-4">
            <div className="space-y-2">
              <Label>{t("create.fileLabel")}</Label>
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.html,.htm"
                className="hidden"
                onChange={handleFileSelect}
              />
              {selectedFile ? (
                <div className="flex items-center justify-between rounded-lg border p-3">
                  <div className="flex items-center gap-3">
                    <div className="bg-muted flex h-10 w-10 items-center justify-center rounded-lg">
                      {getFileTypeLabel(selectedFile.type, selectedFile.name) === "Excel" ? (
                        <FileSpreadsheet className="h-5 w-5 text-green-600" />
                      ) : getFileTypeLabel(selectedFile.type, selectedFile.name) ===
                        "PowerPoint" ? (
                        <Presentation className="h-5 w-5 text-orange-600" />
                      ) : (
                        <FileText className="h-5 w-5 text-blue-600" />
                      )}
                    </div>
                    <div>
                      <p className="max-w-[200px] truncate text-sm font-medium">
                        {selectedFile.name}
                      </p>
                      <p className="text-muted-foreground text-xs">
                        {getFileTypeLabel(selectedFile.type, selectedFile.name)} •{" "}
                        {formatBytes(selectedFile.size)}
                      </p>
                    </div>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setSelectedFile(null)}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              ) : (
                <Button
                  type="button"
                  variant="outline"
                  className="w-full"
                  onClick={() => fileInputRef.current?.click()}
                >
                  <Upload className="mr-2 h-4 w-4" />
                  {t("create.chooseFile")}
                </Button>
              )}
              <p className="text-muted-foreground text-xs">{t("create.fileHelp")}</p>
            </div>
          </TabsContent>
        </Tabs>

        <Accordion type="single" collapsible>
          <AccordionItem value="advanced" className="border-b-0">
            <AccordionTrigger>{t("common:createAccess.advancedOptions")}</AccordionTrigger>
            <AccordionContent>
              <CreateAccessControl
                initiativeId={effectiveInitiativeId}
                roleGrants={roleGrants}
                onRoleGrantsChange={setRoleGrants}
                userGrants={userGrants}
                onUserGrantsChange={setUserGrants}
                onLoadingChange={setAccessLoading}
              />
            </AccordionContent>
          </AccordionItem>
        </Accordion>

        <DialogFooter>
          {createDialogTab === "new" ? (
            <Button
              type="button"
              onClick={() => createDocument.mutate()}
              disabled={!canSubmitNew || accessLoading}
            >
              {createDocument.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {t("create.creating")}
                </>
              ) : (
                t("create.createDocument")
              )}
            </Button>
          ) : (
            <Button
              type="button"
              onClick={() => uploadDocument.mutate()}
              disabled={!canSubmitUpload || accessLoading}
            >
              {uploadDocument.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {t("create.uploadingFile")}
                </>
              ) : (
                t("create.uploadDocument")
              )}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
