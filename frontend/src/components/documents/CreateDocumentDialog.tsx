import { type ChangeEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  FileCode,
  FileSpreadsheet,
  FileText,
  ImageIcon,
  Link as LinkIcon,
  Loader2,
  Plus,
  Presentation,
  Upload,
  X,
} from "lucide-react";
import { matchSmartLinkProvider, SUPPORTED_PROVIDER_BADGES } from "@/lib/smartLinkProviders";
import { useTranslation } from "react-i18next";

import { toast } from "@/lib/chesterToast";
import { useAllDocumentIds, useCreateDocument, useUploadDocument } from "@/hooks/useDocuments";
import { useInitiative } from "@/hooks/useInitiatives";
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
import type { DocumentRead, InitiativeRead } from "@/api/generated/initiativeAPI.schemas";
import type { DialogProps } from "@/types/dialog";

type CreateDocumentDialogProps = DialogProps & {
  /** If provided, the initiative is locked and cannot be changed */
  initiativeId?: number;
  /** If provided, pre-selects this initiative (but user can change it) */
  defaultInitiativeId?: number;
  /** If provided, the created document will be auto-attached to this project */
  projectId?: number;
  /** Called after successful creation/upload */
  onSuccess?: (document: DocumentRead) => void;
  /** List of initiatives user can create documents in (required if initiativeId not provided) */
  initiatives?: InitiativeRead[];
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

  const [createDialogTab, setCreateDialogTab] = useState<"new" | "upload" | "smartLink">("new");
  const [newTitle, setNewTitle] = useState("");
  const [selectedInitiativeId, setSelectedInitiativeId] = useState(
    defaultInitiativeId ? String(defaultInitiativeId) : ""
  );
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [isTemplateDocument, setIsTemplateDocument] = useState(false);
  const [newDocumentType, setNewDocumentType] = useState<"native" | "whiteboard" | "spreadsheet">(
    "native"
  );
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [smartLinkUrl, setSmartLinkUrl] = useState("");
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
  const initiativeQuery = useInitiative(
    open && !!initiativeId && !lockedInitiativeFromList ? initiativeId! : null
  );

  const lockedInitiative = lockedInitiativeFromList ?? initiativeQuery.data ?? null;

  // Query templates
  const templateDocumentsQuery = useAllDocumentIds({ enabled: open });

  // Filter templates — backend already enforces access control via RLS.
  // Also filter by the currently selected document type so we don't let users
  // copy a Lexical template into a whiteboard slot (or vice versa).
  const manageableTemplates = useMemo(() => {
    if (!templateDocumentsQuery.data || !Array.isArray(templateDocumentsQuery.data)) return [];
    return templateDocumentsQuery.data.filter(
      (doc) => doc.is_template && doc.document_type === newDocumentType
    );
  }, [templateDocumentsQuery.data, newDocumentType]);

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
      setNewDocumentType("native");
      setSelectedFile(null);
      setSmartLinkUrl("");
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

  // Clear template when the document type changes so we don't accidentally
  // copy a native template into a whiteboard (or vice versa).
  useEffect(() => {
    setSelectedTemplateId("");
  }, [newDocumentType]);

  // Validate selected template still exists
  useEffect(() => {
    if (!selectedTemplateId) return;
    const isValid = manageableTemplates.some((doc) => String(doc.id) === selectedTemplateId);
    if (!isValid) setSelectedTemplateId("");
  }, [manageableTemplates, selectedTemplateId]);

  const createDocument = useCreateDocument({
    onSuccess: (document) => {
      toast.success(projectId ? t("create.createdAttached") : t("create.created"));
      onOpenChange(false);
      onSuccess?.(document);
    },
  });

  const uploadDocument = useUploadDocument({
    onSuccess: (document) => {
      toast.success(projectId ? t("create.uploadedAttached") : t("create.uploaded"));
      onOpenChange(false);
      onSuccess?.(document);
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
  const trimmedSmartLinkUrl = smartLinkUrl.trim();
  const smartLinkProviderMatch = useMemo(
    () => (trimmedSmartLinkUrl ? matchSmartLinkProvider(trimmedSmartLinkUrl) : null),
    [trimmedSmartLinkUrl]
  );
  const smartLinkUrlIsHttp = /^https?:\/\//.test(trimmedSmartLinkUrl);
  const canSubmitSmartLink = Boolean(
    newTitle.trim() && effectiveInitiativeId && smartLinkUrlIsHttp && !isCreating
  );

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
          onValueChange={(value) => setCreateDialogTab(value as "new" | "upload" | "smartLink")}
        >
          <TabsList className="grid w-full grid-cols-3">
            <TabsTrigger value="new" className="flex items-center gap-2">
              <Plus className="h-4 w-4" />
              {t("create.tabNew")}
            </TabsTrigger>
            <TabsTrigger value="upload" className="flex items-center gap-2">
              <Upload className="h-4 w-4" />
              {t("create.tabUpload")}
            </TabsTrigger>
            <TabsTrigger value="smartLink" className="flex items-center gap-2">
              <LinkIcon className="h-4 w-4" />
              {t("create.tabSmartLink")}
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
              <Label htmlFor="create-doc-type">{t("create.documentTypeLabel")}</Label>
              <Select
                value={newDocumentType}
                onValueChange={(value) =>
                  setNewDocumentType(value as "native" | "whiteboard" | "spreadsheet")
                }
              >
                <SelectTrigger id="create-doc-type">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="native">{t("create.documentTypeText")}</SelectItem>
                  <SelectItem value="whiteboard">{t("create.documentTypeWhiteboard")}</SelectItem>
                  <SelectItem value="spreadsheet">{t("create.documentTypeSpreadsheet")}</SelectItem>
                </SelectContent>
              </Select>
            </div>
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
                accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.html,.htm,.png,.jpg,.jpeg,.gif,.webp,.svg,.md,.markdown"
                className="hidden"
                onChange={handleFileSelect}
              />
              {selectedFile ? (
                <div className="flex items-center justify-between rounded-lg border p-3">
                  <div className="flex items-center gap-3">
                    <div className="bg-muted flex h-10 w-10 items-center justify-center rounded-lg">
                      {getFileTypeLabel(selectedFile.type, selectedFile.name) === "Image" ? (
                        <ImageIcon className="h-5 w-5 text-emerald-500" />
                      ) : getFileTypeLabel(selectedFile.type, selectedFile.name) === "Markdown" ? (
                        <FileCode className="h-5 w-5 text-indigo-500" />
                      ) : getFileTypeLabel(selectedFile.type, selectedFile.name) === "Excel" ? (
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
              <p className="text-muted-foreground text-xs whitespace-pre-line">
                {t("create.fileHelp")}
              </p>
            </div>
          </TabsContent>

          {/* Smart link tab content */}
          <TabsContent value="smartLink" className="mt-4 space-y-4">
            <div className="space-y-2">
              <Label htmlFor="create-doc-smart-link-url">{t("create.smartLinkUrlLabel")}</Label>
              <Input
                id="create-doc-smart-link-url"
                type="url"
                value={smartLinkUrl}
                onChange={(e) => setSmartLinkUrl(e.target.value)}
                placeholder={t("create.smartLinkUrlPlaceholder")}
                autoComplete="off"
              />
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground text-xs">
                  {t("create.smartLinkSupportedProviders")}
                </span>
                <div className="text-muted-foreground flex flex-wrap items-center gap-2">
                  {SUPPORTED_PROVIDER_BADGES.map((p) => (
                    <span key={p.id} title={p.label} aria-label={p.label} className="inline-flex">
                      <p.icon className="h-4 w-4" aria-hidden="true" />
                    </span>
                  ))}
                </div>
              </div>
              {smartLinkProviderMatch ? (
                <div className="text-muted-foreground flex items-start gap-2 text-xs">
                  <smartLinkProviderMatch.icon className="mt-0.5 h-4 w-4 shrink-0" />
                  {smartLinkProviderMatch.canEmbed ? (
                    <span>
                      {t("create.smartLinkProviderDetected", {
                        provider: smartLinkProviderMatch.label,
                      })}
                    </span>
                  ) : smartLinkProviderMatch.embedHintKey ? (
                    <span>
                      <span className="font-medium">
                        {t("create.smartLinkNeedsEmbedUrl", {
                          provider: smartLinkProviderMatch.label,
                        })}
                      </span>{" "}
                      {t(smartLinkProviderMatch.embedHintKey)}
                    </span>
                  ) : (
                    <span>{t("create.smartLinkGenericNote")}</span>
                  )}
                </div>
              ) : null}
              <p className="text-muted-foreground text-xs">{t("create.smartLinkDisclaimer")}</p>
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
              onClick={() => {
                const trimmedTitle = newTitle.trim();
                if (!trimmedTitle || !effectiveInitiativeId) return;
                createDocument.mutate({
                  title: trimmedTitle,
                  initiative_id: effectiveInitiativeId,
                  is_template: isTemplateDocument,
                  template_id: selectedTemplateId ? Number(selectedTemplateId) : undefined,
                  project_id: projectId,
                  document_type: newDocumentType,
                  role_grants: roleGrants,
                  user_grants: userGrants,
                });
              }}
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
          ) : createDialogTab === "upload" ? (
            <Button
              type="button"
              onClick={() => {
                if (!selectedFile || !effectiveInitiativeId) return;
                const trimmedTitle = newTitle.trim();
                if (!trimmedTitle) return;
                uploadDocument.mutate({
                  file: selectedFile,
                  title: trimmedTitle,
                  initiative_id: effectiveInitiativeId,
                  project_id: projectId,
                  role_grants: roleGrants,
                  user_grants: userGrants,
                });
              }}
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
          ) : (
            <Button
              type="button"
              onClick={() => {
                const trimmedTitle = newTitle.trim();
                if (!trimmedTitle || !effectiveInitiativeId) return;
                if (!smartLinkUrlIsHttp) return;
                createDocument.mutate({
                  title: trimmedTitle,
                  initiative_id: effectiveInitiativeId,
                  project_id: projectId,
                  document_type: "smart_link",
                  content: { url: trimmedSmartLinkUrl },
                  role_grants: roleGrants,
                  user_grants: userGrants,
                });
              }}
              disabled={!canSubmitSmartLink || accessLoading}
            >
              {createDocument.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {t("create.creating")}
                </>
              ) : (
                t("create.createSmartLink")
              )}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
