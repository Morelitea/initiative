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
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { DocumentType, ResourceGrantSchema } from "@/api/generated/initiativeAPI.schemas";
import { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import { CreateAccessSection } from "@/components/access/CreateAccessSection";
import { DEFAULT_GRANTS } from "@/components/access/grants";
import { AsyncCombobox } from "@/components/ui/async-combobox";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { FileDropArea } from "@/components/ui/file-drop";
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
import { Tabs, TabsBar, TabsContent, TabsTrigger } from "@/components/ui/tabs";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useCreateDocument, useUploadDocument } from "@/hooks/useDocuments";
import { useInitiative } from "@/hooks/useInitiatives";
import { useCommunityPickerSuggestions } from "@/hooks/useSearch";
import {
  DOCUMENT_UPLOAD_ACCEPT,
  formatBytes,
  getFileTypeLabel,
  nameWithoutExtension,
} from "@/lib/fileUtils";
import { toast } from "@/lib/mascotToast";
import { matchSmartLinkProvider, SUPPORTED_PROVIDER_BADGES } from "@/lib/smartLinkProviders";
import type { DialogProps } from "@/types/dialog";

type CreateDocumentDialogProps = DialogProps & {
  /** The initiative the document is made in. */
  initiativeId: number;
  /** If provided, the created document will be auto-attached to this project */
  projectId?: number;
  /** Called after successful creation/upload */
  onSuccess?: (document: { id: number }) => void;
  /** A file dropped on the page to open this; the dialog opens on Upload holding it. */
  initialFile?: File | null;
};

/** The document types made from scratch here; files come in by upload, and
 *  smart links from their own tab. */
type NewDocumentType = Exclude<DocumentType, "file" | "smart_link">;

export const CreateDocumentDialog = ({
  open,
  onOpenChange,
  initiativeId,
  projectId,
  onSuccess,
  initialFile = null,
}: CreateDocumentDialogProps) => {
  const { t } = useTranslation(["documents", "common"]);
  const { maxUploadBytes } = useAppConfig();

  const [createDialogTab, setCreateDialogTab] = useState<"new" | "upload" | "smartLink">("new");
  const [newTitle, setNewTitle] = useState("");
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  // Server search only returns matches for the live query, so the picker can't
  // look the selected template's title up from the current page — remember it.
  const [selectedTemplateLabel, setSelectedTemplateLabel] = useState<string | null>(null);
  const [templateSearch, setTemplateSearch] = useState("");
  const [isTemplateDocument, setIsTemplateDocument] = useState(false);
  const [newDocumentType, setNewDocumentType] = useState<NewDocumentType>("native");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [smartLinkUrl, setSmartLinkUrl] = useState("");
  const [grants, setGrants] = useState<ResourceGrantSchema[]>([...DEFAULT_GRANTS]);

  const initiative = useInitiative(open ? initiativeId : null).data;

  // Template picker — the shared lookup, asked for blueprints, only while the
  // dialog is open. It opens on the templates most recently worked on, which is
  // the only way it can say that this community has any.
  const templates = useCommunityPickerSuggestions(templateSearch, {
    types: [SearchEntityType.document],
    is_template: true,
    enabled: open && !isTemplateDocument,
  });

  const templateItems = useMemo(
    () =>
      templates.items.map((doc) => ({
        value: String(doc.entity_id),
        label: doc.title,
      })),
    [templates.items]
  );

  const clearTemplate = useCallback(() => {
    setSelectedTemplateId("");
    setSelectedTemplateLabel(null);
  }, []);

  // Reset form when dialog closes
  useEffect(() => {
    if (open) {
      // Opened by a drop: the file is the whole of what was asked for.
      if (initialFile) {
        setCreateDialogTab("upload");
        setSelectedFile(initialFile);
        setNewTitle(nameWithoutExtension(initialFile.name));
      }
    } else {
      setNewTitle("");
      clearTemplate();
      setIsTemplateDocument(false);
      setNewDocumentType("native");
      setSelectedFile(null);
      setSmartLinkUrl("");
      setCreateDialogTab("new");
      setGrants([...DEFAULT_GRANTS]);
    }
  }, [open, initialFile, clearTemplate]);

  // Clear template when "save as template" is toggled on
  useEffect(() => {
    if (isTemplateDocument && selectedTemplateId) {
      clearTemplate();
    }
  }, [isTemplateDocument, selectedTemplateId, clearTemplate]);

  // Clear template when the document type changes so we don't accidentally
  // copy a native template into a whiteboard (or vice versa).
  useEffect(() => {
    clearTemplate();
  }, [newDocumentType, clearTemplate]);

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

  const handleFileSelect = (file: File) => {
    if (maxUploadBytes !== null && file.size > maxUploadBytes) {
      toast.error(t("create.fileTooLarge"));
      return;
    }
    setSelectedFile(file);
    if (!newTitle.trim()) {
      setNewTitle(nameWithoutExtension(file.name));
    }
  };

  const isCreating = createDocument.isPending || uploadDocument.isPending;
  const canSubmitNew = newTitle.trim() && !isCreating;
  const canSubmitUpload = newTitle.trim() && selectedFile && !isCreating;
  const trimmedSmartLinkUrl = smartLinkUrl.trim();
  const smartLinkProviderMatch = useMemo(
    () => (trimmedSmartLinkUrl ? matchSmartLinkProvider(trimmedSmartLinkUrl) : null),
    [trimmedSmartLinkUrl]
  );
  const smartLinkUrlIsHttp = /^https?:\/\//.test(trimmedSmartLinkUrl);
  const canSubmitSmartLink = Boolean(newTitle.trim() && smartLinkUrlIsHttp && !isCreating);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-full rounded-2xl border bg-card shadow-2xl sm:max-w-lg">
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
          <TabsBar>
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
          </TabsBar>

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
              <Label>{t("create.initiativeLabel")}</Label>
              <div className="rounded-md border px-3 py-2 text-sm">
                {initiative?.name ?? t("common:loading")}
              </div>
            </div>
          </div>

          {/* New document tab content */}
          <TabsContent value="new" className="mt-4 space-y-4">
            <div className="space-y-2">
              <Label htmlFor="create-doc-type">{t("create.documentTypeLabel")}</Label>
              <Select
                value={newDocumentType}
                onValueChange={(value) => setNewDocumentType(value as NewDocumentType)}
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
                <Label>{t("create.templateLabel")}</Label>
                {selectedTemplateId && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-auto px-2 py-1 text-xs"
                    onClick={clearTemplate}
                  >
                    <X className="h-3 w-3" />
                    {t("create.clear")}
                  </Button>
                )}
              </div>
              <AsyncCombobox
                items={templateItems}
                value={selectedTemplateId || null}
                selectedLabel={selectedTemplateLabel}
                onValueChange={(value) => {
                  setSelectedTemplateId(value);
                  setSelectedTemplateLabel(
                    templateItems.find((item) => item.value === value)?.label ?? null
                  );
                }}
                onSearchChange={setTemplateSearch}
                loading={templates.isFetching}
                disabled={isTemplateDocument}
                placeholder={t("create.selectTemplate")}
                searchPlaceholder={t("create.searchTemplates")}
                emptyMessage={t("create.noTemplates")}
                aria-label={t("create.templateLabel")}
              />
            </div>
            <div className="flex flex-col gap-2 rounded-lg border bg-muted/40 p-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="font-medium text-sm">{t("create.saveAsTemplate")}</p>
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
              {selectedFile ? (
                <div className="flex items-center justify-between rounded-lg border p-3">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted">
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
                      <p className="max-w-[200px] truncate font-medium text-sm">
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
                <FileDropArea
                  accept={DOCUMENT_UPLOAD_ACCEPT}
                  onFile={handleFileSelect}
                  prompt={t("create.dropPrompt")}
                />
              )}
              <p className="whitespace-pre-line text-muted-foreground text-xs">
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
                <div className="flex flex-wrap items-center gap-2 text-muted-foreground">
                  {SUPPORTED_PROVIDER_BADGES.map((p) => (
                    <span
                      key={p.id}
                      title={p.label}
                      aria-label={p.label}
                      className="inline-flex"
                      role="img"
                    >
                      <p.icon className="h-4 w-4" aria-hidden="true" />
                    </span>
                  ))}
                </div>
              </div>
              {smartLinkProviderMatch ? (
                <div className="flex items-start gap-2 text-muted-foreground text-xs">
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

        <CreateAccessSection
          initiativeId={initiativeId}
          grants={grants}
          onChange={setGrants}
          defaultOpen={false}
        />

        <DialogFooter>
          {createDialogTab === "new" ? (
            <Button
              type="button"
              onClick={() => {
                const trimmedTitle = newTitle.trim();
                if (!trimmedTitle) return;
                createDocument.mutate({
                  name: trimmedTitle,
                  initiative_id: initiativeId,
                  is_template: isTemplateDocument,
                  template_id: selectedTemplateId ? Number(selectedTemplateId) : undefined,
                  project_id: projectId,
                  document_type: newDocumentType,
                  grants,
                });
              }}
              disabled={!canSubmitNew}
            >
              {createDocument.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
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
                const trimmedTitle = newTitle.trim();
                if (!selectedFile || !trimmedTitle) return;
                uploadDocument.mutate({
                  file: selectedFile,
                  name: trimmedTitle,
                  initiative_id: initiativeId,
                  project_id: projectId,
                  grants,
                });
              }}
              disabled={!canSubmitUpload}
            >
              {uploadDocument.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
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
                if (!trimmedTitle || !smartLinkUrlIsHttp) return;
                createDocument.mutate({
                  name: trimmedTitle,
                  initiative_id: initiativeId,
                  project_id: projectId,
                  document_type: "smart_link",
                  content: { url: trimmedSmartLinkUrl },
                  grants,
                });
              }}
              disabled={!canSubmitSmartLink}
            >
              {createDocument.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
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
