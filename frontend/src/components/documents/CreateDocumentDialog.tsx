import { type ChangeEvent, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileSpreadsheet, FileText, Loader2, Plus, Presentation, Upload, X } from "lucide-react";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
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
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
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
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const { activeGuildId } = useGuilds();

  const [createDialogTab, setCreateDialogTab] = useState<"new" | "upload">("new");
  const [newTitle, setNewTitle] = useState("");
  const [selectedInitiativeId, setSelectedInitiativeId] = useState(
    defaultInitiativeId ? String(defaultInitiativeId) : ""
  );
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [isTemplateDocument, setIsTemplateDocument] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Determine effective initiative ID
  const effectiveInitiativeId =
    initiativeId ?? (selectedInitiativeId ? Number(selectedInitiativeId) : null);

  // Find the locked initiative for display
  const lockedInitiative = useMemo(() => {
    if (!initiativeId) return null;
    return initiatives.find((i) => i.id === initiativeId) ?? null;
  }, [initiativeId, initiatives]);

  // Query templates
  const templateDocumentsQuery = useQuery<DocumentSummary[]>({
    queryKey: ["documents", "templates"],
    queryFn: async () => {
      const response = await apiClient.get<DocumentSummary[]>("/documents/");
      return response.data;
    },
    enabled: open,
  });

  // Filter templates user can access
  const manageableTemplates = useMemo(() => {
    if (!templateDocumentsQuery.data || !user) return [];
    return templateDocumentsQuery.data.filter((doc) => {
      if (!doc.is_template) return false;
      const permission = (doc.permissions ?? []).find((p) => p.user_id === user.id);
      return Boolean(permission);
    });
  }, [templateDocumentsQuery.data, user]);

  // Reset form when dialog closes
  useEffect(() => {
    if (!open) {
      setNewTitle("");
      setSelectedInitiativeId(defaultInitiativeId ? String(defaultInitiativeId) : "");
      setSelectedTemplateId("");
      setIsTemplateDocument(false);
      setSelectedFile(null);
      setCreateDialogTab("new");
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

  const createDocument = useMutation({
    mutationFn: async () => {
      const trimmedTitle = newTitle.trim();
      if (!trimmedTitle) throw new Error("Document title is required");
      if (!effectiveInitiativeId) throw new Error("Please select an initiative");

      let newDocument: DocumentRead;

      if (selectedTemplateId) {
        const response = await apiClient.post<DocumentRead>(
          `/documents/${selectedTemplateId}/copy`,
          { target_initiative_id: effectiveInitiativeId, title: trimmedTitle }
        );
        newDocument = response.data;
      } else {
        const response = await apiClient.post<DocumentRead>("/documents/", {
          title: trimmedTitle,
          initiative_id: effectiveInitiativeId,
          is_template: isTemplateDocument,
        });
        newDocument = response.data;
      }

      // Auto-attach to project if specified
      if (projectId) {
        await apiClient.post(`/projects/${projectId}/documents/${newDocument.id}`, {});
      }

      return newDocument;
    },
    onSuccess: (document) => {
      toast.success(projectId ? "Document created and attached." : "Document created.");
      onOpenChange(false);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["documents", activeGuildId] });
      if (effectiveInitiativeId) {
        void queryClient.invalidateQueries({
          queryKey: ["documents", "initiative", effectiveInitiativeId],
        });
      }
      if (projectId) {
        void queryClient.invalidateQueries({ queryKey: ["project", projectId] });
      }
      onSuccess?.(document);
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : "Unable to create document.";
      toast.error(message);
    },
  });

  const uploadDocument = useMutation({
    mutationFn: async () => {
      if (!selectedFile) throw new Error("Please select a file to upload");
      const trimmedTitle = newTitle.trim();
      if (!trimmedTitle) throw new Error("Document title is required");
      if (!effectiveInitiativeId) throw new Error("Please select an initiative");

      const formData = new FormData();
      formData.append("file", selectedFile);
      formData.append("title", trimmedTitle);
      formData.append("initiative_id", String(effectiveInitiativeId));

      const response = await apiClient.post<DocumentRead>("/documents/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });

      const newDocument = response.data;

      // Auto-attach to project if specified
      if (projectId) {
        await apiClient.post(`/projects/${projectId}/documents/${newDocument.id}`, {});
      }

      return newDocument;
    },
    onSuccess: (document) => {
      toast.success(projectId ? "Document uploaded and attached." : "Document uploaded.");
      onOpenChange(false);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["documents", activeGuildId] });
      if (effectiveInitiativeId) {
        void queryClient.invalidateQueries({
          queryKey: ["documents", "initiative", effectiveInitiativeId],
        });
      }
      if (projectId) {
        void queryClient.invalidateQueries({ queryKey: ["project", projectId] });
      }
      onSuccess?.(document);
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : "Unable to upload document.";
      toast.error(message);
    },
  });

  const handleFileSelect = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      const maxSize = 50 * 1024 * 1024;
      if (file.size > maxSize) {
        toast.error("File is too large. Maximum size is 50 MB.");
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
          <DialogTitle>New document</DialogTitle>
          <DialogDescription>
            {projectId
              ? "Create a new document and automatically attach it to this project."
              : "Documents live inside an initiative and can be attached to projects later."}
          </DialogDescription>
        </DialogHeader>

        <Tabs
          value={createDialogTab}
          onValueChange={(value) => setCreateDialogTab(value as "new" | "upload")}
        >
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="new" className="flex items-center gap-2">
              <Plus className="h-4 w-4" />
              New document
            </TabsTrigger>
            <TabsTrigger value="upload" className="flex items-center gap-2">
              <Upload className="h-4 w-4" />
              Upload file
            </TabsTrigger>
          </TabsList>

          {/* Shared fields: Title and Initiative */}
          <div className="mt-4 space-y-4">
            <div className="space-y-2">
              <Label htmlFor="create-doc-title">Title</Label>
              <Input
                id="create-doc-title"
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                placeholder={
                  createDialogTab === "upload" ? "Document title" : "Product launch brief"
                }
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="create-doc-initiative">Initiative</Label>
              {initiativeId ? (
                <div className="rounded-md border px-3 py-2 text-sm">
                  {lockedInitiative?.name ?? "Selected initiative"}
                </div>
              ) : (
                <Select value={selectedInitiativeId} onValueChange={setSelectedInitiativeId}>
                  <SelectTrigger id="create-doc-initiative">
                    <SelectValue placeholder="Select initiative" />
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
                <Label htmlFor="create-doc-template">Start from template</Label>
                {selectedTemplateId && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-auto px-2 py-1 text-xs"
                    onClick={() => setSelectedTemplateId("")}
                  >
                    <X className="mr-1 h-3 w-3" />
                    Clear
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
                        ? "Loading templates…"
                        : manageableTemplates.length > 0
                          ? "Select template (optional)"
                          : "No templates available"
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
                <p className="text-sm font-medium">Save as template</p>
                <p className="text-muted-foreground text-xs">
                  Template documents are best duplicated or copied into other initiatives.
                </p>
              </div>
              <Switch
                id="create-doc-is-template"
                checked={isTemplateDocument}
                onCheckedChange={setIsTemplateDocument}
                aria-label="Toggle template status"
              />
            </div>
          </TabsContent>

          {/* Upload file tab content */}
          <TabsContent value="upload" className="mt-4 space-y-4">
            <div className="space-y-2">
              <Label>File</Label>
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
                  Choose file
                </Button>
              )}
              <p className="text-muted-foreground text-xs">
                Supported: PDF, Word, Excel, PowerPoint, TXT, HTML (max 50 MB)
              </p>
            </div>
          </TabsContent>
        </Tabs>

        <DialogFooter>
          {createDialogTab === "new" ? (
            <Button type="button" onClick={() => createDocument.mutate()} disabled={!canSubmitNew}>
              {createDocument.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Creating…
                </>
              ) : (
                "Create document"
              )}
            </Button>
          ) : (
            <Button
              type="button"
              onClick={() => uploadDocument.mutate()}
              disabled={!canSubmitUpload}
            >
              {uploadDocument.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Uploading…
                </>
              ) : (
                "Upload document"
              )}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
