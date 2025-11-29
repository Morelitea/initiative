import { type ChangeEvent, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import type { SerializedEditorState } from "lexical";
import { ImagePlus, Loader2, ScrollText, Settings, X } from "lucide-react";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
import {
  DocumentEditor,
  createEmptyEditorState,
  normalizeEditorState,
} from "@/components/editor/DocumentEditor";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import type { DocumentProjectLink, DocumentRead } from "@/types/api";
import { uploadAttachment } from "@/api/attachments";
import { useAuth } from "@/hooks/useAuth";

export const DocumentDetailPage = () => {
  const { documentId } = useParams();
  const parsedId = Number(documentId);
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const [featuredImageUrl, setFeaturedImageUrl] = useState<string | null>(null);
  const [isUploadingFeaturedImage, setIsUploadingFeaturedImage] = useState(false);
  const [title, setTitle] = useState("");
  const [contentState, setContentState] = useState<SerializedEditorState>(createEmptyEditorState());
  const featuredImageInputRef = useRef<HTMLInputElement>(null);

  const documentQuery = useQuery<DocumentRead>({
    queryKey: ["documents", parsedId],
    queryFn: async () => {
      const response = await apiClient.get<DocumentRead>(`/documents/${parsedId}`);
      return response.data;
    },
    enabled: Number.isFinite(parsedId),
  });

  const document = documentQuery.data;
  const normalizedDocumentContent = useMemo(
    () => normalizeEditorState(document?.content),
    [document]
  );

  useEffect(() => {
    if (!document) {
      return;
    }
    setTitle(document.title);
    setContentState(normalizedDocumentContent);
    setFeaturedImageUrl(document.featured_image_url ?? null);
  }, [document, normalizedDocumentContent]);

  const documentContentJson = useMemo(
    () => JSON.stringify(normalizedDocumentContent),
    [normalizedDocumentContent]
  );
  const currentContentJson = useMemo(() => JSON.stringify(contentState), [contentState]);
  const normalizedDocumentFeatured = document?.featured_image_url ?? null;
  const canEditDocument = useMemo(() => {
    if (!document || !user) {
      return false;
    }
    if (user.role === "admin") {
      return true;
    }
    const initiativeMembers = document.initiative?.members ?? [];
    const isManager = initiativeMembers.some(
      (member) => member.user.id === user.id && member.role === "project_manager"
    );
    if (isManager) {
      return true;
    }
    return (document.write_member_ids ?? []).includes(user.id);
  }, [document, user]);
  const isDirty =
    canEditDocument &&
    ((document && title.trim() !== document.title.trim()) ||
      documentContentJson !== currentContentJson ||
      normalizedDocumentFeatured !== featuredImageUrl);

  const saveDocument = useMutation({
    mutationFn: async () => {
      if (!document) {
        throw new Error("Document is not loaded yet.");
      }
      const trimmedTitle = title.trim();
      if (!trimmedTitle) {
        throw new Error("Document title is required");
      }
      const payload = {
        title: trimmedTitle,
        content: contentState,
        featured_image_url: featuredImageUrl,
      };
      const response = await apiClient.patch<DocumentRead>(`/documents/${parsedId}`, payload);
      return response.data;
    },
    onSuccess: (updated) => {
      toast.success("Document saved");
      queryClient.setQueryData(["documents", parsedId], updated);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : "Unable to save document.";
      toast.error(message);
    },
  });

  const handleFeaturedImageChange = async (event: ChangeEvent<HTMLInputElement>) => {
    if (!canEditDocument) {
      return;
    }
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    if (!file.type.startsWith("image/")) {
      toast.error("Please select an image file.");
      return;
    }
    setIsUploadingFeaturedImage(true);
    try {
      const response = await uploadAttachment(file);
      setFeaturedImageUrl(response.url);
      toast.success("Image uploaded. Save the document to apply changes.");
    } catch (error) {
      console.error(error);
      toast.error("Failed to upload image.");
    } finally {
      setIsUploadingFeaturedImage(false);
    }
  };

  const openFeaturedImagePicker = () => {
    if (!canEditDocument) {
      return;
    }
    featuredImageInputRef.current?.click();
  };

  if (!Number.isFinite(parsedId)) {
    return <p className="text-destructive">Invalid document id.</p>;
  }

  if (documentQuery.isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading document…
      </div>
    );
  }

  if (documentQuery.isError || !document) {
    return <p className="text-destructive">Document not found.</p>;
  }

  const attachedProjects: DocumentProjectLink[] = document.projects ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button asChild variant="link" className="px-0">
          <Link to="/documents">← Back to documents</Link>
        </Button>
        {canEditDocument ? (
          <Button asChild variant="outline" size="sm">
            <Link
              to={`/documents/${document.id}/settings`}
              className="inline-flex items-center gap-2"
            >
              <Settings className="h-4 w-4" />
              Document settings
            </Link>
          </Button>
        ) : null}
      </div>
      <div className="space-y-2">
        <Input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Document title"
          className="text-2xl font-semibold"
          disabled={!canEditDocument}
        />
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          {document.initiative ? (
            <span className="inline-flex items-center gap-1 rounded-full border px-3 py-1">
              <InitiativeColorDot color={document.initiative.color} />
              {document.initiative.name}
            </span>
          ) : null}
          <span>
            Updated {formatDistanceToNow(new Date(document.updated_at), { addSuffix: true })}
          </span>
          {document.is_template ? <Badge variant="outline">Template</Badge> : null}
        </div>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Featured image</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-4 md:flex-row md:items-center">
            <div className="relative aspect-square w-full overflow-hidden rounded-xl border bg-muted md:w-50">
              {featuredImageUrl ? (
                <img src={featuredImageUrl} alt="" className="h-full w-full object-cover" />
              ) : (
                <div className="flex h-full items-center justify-center text-muted-foreground">
                  <ScrollText className="h-10 w-10" />
                </div>
              )}
            </div>
            <div className="space-y-2">
              <input
                ref={featuredImageInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={handleFeaturedImageChange}
              />
              {canEditDocument ? (
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={openFeaturedImagePicker}
                    disabled={isUploadingFeaturedImage}
                  >
                    {isUploadingFeaturedImage ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Uploading…
                      </>
                    ) : (
                      <>
                        <ImagePlus className="mr-2 h-4 w-4" />
                        Upload featured image
                      </>
                    )}
                  </Button>
                  {featuredImageUrl ? (
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={() => setFeaturedImageUrl(null)}
                      disabled={isUploadingFeaturedImage}
                    >
                      <X className="mr-2 h-4 w-4" />
                      Remove image
                    </Button>
                  ) : null}
                </div>
              ) : null}
              <p className="text-xs text-muted-foreground">
                Uploads are stored locally under <code>/uploads</code>. Remember to save changes to
                keep your new image.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
      <DocumentEditor
        key={document.id}
        initialState={normalizedDocumentContent}
        onChange={setContentState}
        placeholder="Capture requirements, share decisions, or outline processes…"
        readOnly={!canEditDocument}
        showToolbar={canEditDocument}
      />
      <div className="flex flex-wrap gap-3">
        {canEditDocument ? (
          <>
            <Button
              type="button"
              onClick={() => saveDocument.mutate()}
              disabled={!isDirty || saveDocument.isPending}
            >
              {saveDocument.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Saving…
                </>
              ) : (
                "Save changes"
              )}
            </Button>
            {!isDirty ? (
              <span className="self-center text-sm text-muted-foreground">All changes saved</span>
            ) : null}
          </>
        ) : (
          <p className="text-sm text-muted-foreground">
            You only have read access to this document.
          </p>
        )}
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Attached projects</CardTitle>
        </CardHeader>
        <CardContent>
          {attachedProjects.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              This document is not attached to any projects yet. Attach it from a project detail
              page.
            </p>
          ) : (
            <div className="space-y-2">
              {attachedProjects.map((link) => (
                <div
                  key={`${document.id}-${link.project_id}`}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border px-4 py-3"
                >
                  <div className="space-y-0.5">
                    <Link
                      to={`/projects/${link.project_id}`}
                      className="font-medium hover:underline"
                    >
                      {link.project_name ?? `Project #${link.project_id}`}
                    </Link>
                    <p className="text-xs text-muted-foreground">
                      Attached{" "}
                      {formatDistanceToNow(new Date(link.attached_at), { addSuffix: true })}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};
