import { type ChangeEvent, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import type { SerializedEditorState } from "lexical";
import { ImagePlus, Loader2, ScrollText, Settings, X } from "lucide-react";
import { toast } from "sonner";

import { API_BASE_URL, apiClient } from "@/api/client";
import { createEmptyEditorState, normalizeEditorState } from "@/components/editor/DocumentEditor";
import { Editor } from "@/components/editor-x/editor";
import { CollaborationStatusBadge } from "@/components/editor-x/CollaborationStatusBadge";
import { findNewMentions } from "@/lib/mentionUtils";
import { useCollaboration } from "@/hooks/useCollaboration";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import type { Comment, DocumentProjectLink, DocumentRead } from "@/types/api";
import { uploadAttachment } from "@/api/attachments";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import { CommentSection } from "@/components/comments/CommentSection";

export const DocumentDetailPage = () => {
  const { documentId } = useParams({ strict: false }) as { documentId: string };
  const parsedId = Number(documentId);
  const queryClient = useQueryClient();
  const { user, token } = useAuth();
  const { activeGuildId } = useGuilds();
  const [featuredImageUrl, setFeaturedImageUrl] = useState<string | null>(null);
  const [isUploadingFeaturedImage, setIsUploadingFeaturedImage] = useState(false);
  const [title, setTitle] = useState("");
  const [contentState, setContentState] = useState<SerializedEditorState>(createEmptyEditorState());
  const [autosaveEnabled, setAutosaveEnabled] = useState(true);
  const [collaborationEnabled, setCollaborationEnabled] = useState(true);
  const isAutosaveRef = useRef(false);
  const featuredImageInputRef = useRef<HTMLInputElement>(null);
  // Refs for sendBeacon - need latest values in event handlers
  const contentStateRef = useRef(contentState);
  const collaboratingRef = useRef(false);

  // Collaboration hook - only enable when we have a valid document ID
  const collaboration = useCollaboration({
    documentId: parsedId,
    enabled: collaborationEnabled && Number.isFinite(parsedId),
    onError: () => {
      // Silently fall back to autosave mode on collaboration error
      setCollaborationEnabled(false);
    },
  });

  const documentQuery = useQuery<DocumentRead>({
    queryKey: ["documents", parsedId],
    queryFn: async () => {
      const response = await apiClient.get<DocumentRead>(`/documents/${parsedId}`);
      return response.data;
    },
    enabled: Number.isFinite(parsedId),
  });

  const commentsQueryKey = ["comments", "document", parsedId];
  const commentsQuery = useQuery<Comment[]>({
    queryKey: commentsQueryKey,
    enabled: Number.isFinite(parsedId),
    queryFn: async () => {
      const response = await apiClient.get<Comment[]>("/comments/", {
        params: { document_id: parsedId },
      });
      return response.data;
    },
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
    ((document && title?.trim() !== document?.title?.trim()) ||
      documentContentJson !== currentContentJson ||
      normalizedDocumentFeatured !== featuredImageUrl);

  const commentsCanModerate = useMemo(() => {
    if (!document || !user) {
      return false;
    }
    if (user.role === "admin") {
      return true;
    }
    const initiativeMembers = document.initiative?.members ?? [];
    return initiativeMembers.some(
      (member) => member.user.id === user.id && member.role === "project_manager"
    );
  }, [document, user]);

  const mentionableUsers = useMemo(() => {
    return document?.initiative?.members?.map((member) => member.user) ?? [];
  }, [document?.initiative?.members]);

  const updateDocumentCommentCount = (delta: number) => {
    queryClient.setQueryData<DocumentRead>(["documents", parsedId], (previous) => {
      if (!previous) {
        return previous;
      }
      const nextCount = Math.max(0, (previous.comment_count ?? 0) + delta);
      return { ...previous, comment_count: nextCount };
    });
  };

  const handleCommentCreated = (comment: Comment) => {
    queryClient.setQueryData<Comment[]>(commentsQueryKey, (previous) => {
      if (!previous) {
        return [comment];
      }
      return [...previous, comment];
    });
    updateDocumentCommentCount(1);
  };

  const handleCommentDeleted = (commentId: number) => {
    queryClient.setQueryData<Comment[]>(commentsQueryKey, (previous) => {
      if (!previous) {
        return previous;
      }
      return previous.filter((comment) => comment.id !== commentId);
    });
    updateDocumentCommentCount(-1);
  };

  const saveDocument = useMutation({
    mutationFn: async () => {
      if (!document) {
        throw new Error("Document is not loaded yet.");
      }
      const trimmedTitle = title?.trim();
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
      if (!isAutosaveRef.current) {
        toast.success("Document saved");
      }
      isAutosaveRef.current = false;
      queryClient.setQueryData(["documents", parsedId], updated);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      // Fire-and-forget: notify users who were newly mentioned
      const newMentionIds = findNewMentions(normalizedDocumentContent, contentState);
      if (newMentionIds.length > 0) {
        apiClient
          .post(`/documents/${parsedId}/mentions`, { mentioned_user_ids: newMentionIds })
          .catch((err) => console.error("Failed to notify mentions:", err));
      }
    },
    onError: (error) => {
      isAutosaveRef.current = false;
      const message = error instanceof Error ? error.message : "Unable to save document.";
      toast.error(message);
    },
  });

  // Keep refs updated for sendBeacon
  useEffect(() => {
    contentStateRef.current = contentState;
  }, [contentState]);

  useEffect(() => {
    collaboratingRef.current = collaboration.isCollaborating;
  }, [collaboration.isCollaborating]);

  // Autosave with debounce
  useEffect(() => {
    if (!autosaveEnabled || !canEditDocument || saveDocument.isPending) {
      return;
    }
    // When collaborating, sync content less frequently (every 10s) to keep content column updated
    // When not collaborating, use normal autosave behavior (2s debounce when dirty)
    if (collaboration.isCollaborating) {
      const timer = setTimeout(() => {
        isAutosaveRef.current = true;
        saveDocument.mutate();
      }, 10000);
      return () => clearTimeout(timer);
    } else {
      if (!isDirty) {
        return;
      }
      const timer = setTimeout(() => {
        isAutosaveRef.current = true;
        saveDocument.mutate();
      }, 2000);
      return () => clearTimeout(timer);
    }
  }, [
    autosaveEnabled,
    isDirty,
    canEditDocument,
    saveDocument,
    title,
    contentState,
    featuredImageUrl,
    collaboration.isCollaborating,
  ]);

  // Sync content via sendBeacon on page unload to ensure content column stays updated
  // This is critical when users navigate away or close the tab during collaboration
  useEffect(() => {
    if (!canEditDocument || !token || !activeGuildId) {
      return;
    }

    const syncContentBeacon = () => {
      // Only sync if we were collaborating (content might have changed via Yjs)
      if (!collaboratingRef.current) {
        return;
      }

      // Build the sync URL
      const isAbsolute = API_BASE_URL.startsWith("http://") || API_BASE_URL.startsWith("https://");
      const baseUrl = isAbsolute ? API_BASE_URL : `${window.location.origin}${API_BASE_URL}`;
      const syncUrl = `${baseUrl}/collaboration/documents/${parsedId}/sync-content?token=${encodeURIComponent(token)}&guild_id=${activeGuildId}`;

      // Send content via sendBeacon (reliable even on page unload)
      const content = contentStateRef.current;
      const blob = new Blob([JSON.stringify(content)], { type: "application/json" });
      navigator.sendBeacon(syncUrl, blob);
    };

    // Handle tab close / navigation
    const handleBeforeUnload = () => {
      syncContentBeacon();
    };

    // Handle tab visibility change (switching tabs)
    const handleVisibilityChange = () => {
      if (globalThis.document.visibilityState === "hidden") {
        syncContentBeacon();
      }
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    globalThis.document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      window.removeEventListener("beforeunload", handleBeforeUnload);
      globalThis.document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [parsedId, token, activeGuildId, canEditDocument]);

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
      <div className="text-muted-foreground flex items-center gap-2 text-sm">
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
        <Breadcrumb>
          <BreadcrumbList>
            {document.initiative && (
              <>
                <BreadcrumbItem>
                  <BreadcrumbLink asChild>
                    <Link
                      to="/initiatives/$initiativeId"
                      params={{ initiativeId: String(document.initiative.id) }}
                    >
                      {document.initiative.name}
                    </Link>
                  </BreadcrumbLink>
                </BreadcrumbItem>
                <BreadcrumbSeparator />
              </>
            )}
            <BreadcrumbItem>
              <BreadcrumbPage>{document.title}</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>
        <div className="flex items-center gap-3">
          {canEditDocument ? (
            <Button asChild variant="outline" size="sm">
              <Link
                to="/documents/$documentId/settings"
                params={{ documentId: String(document.id) }}
                className="inline-flex items-center gap-2"
              >
                <Settings className="h-4 w-4" />
                Document settings
              </Link>
            </Button>
          ) : null}
        </div>
      </div>
      <div className="space-y-2">
        <Input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Document title"
          className="text-2xl font-semibold"
          disabled={!canEditDocument}
        />
        <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-sm">
          {document.initiative ? (
            <Link
              to="/initiatives/$initiativeId"
              params={{ initiativeId: String(document.initiative.id) }}
              className="inline-flex items-center gap-1 rounded-full border px-3 py-1"
            >
              <InitiativeColorDot color={document.initiative.color} />
              {document.initiative.name}
            </Link>
          ) : null}
          <span>
            Updated {formatDistanceToNow(new Date(document.updated_at), { addSuffix: true })}
          </span>
          {document.is_template ? <Badge variant="outline">Template</Badge> : null}
        </div>
      </div>
      <div className="flex flex-col gap-6 xl:flex-row">
        <div className="flex-1 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Featured image</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-col gap-4 md:flex-row md:items-center">
                <div className="bg-muted relative aspect-square w-full overflow-hidden rounded-xl border md:w-50">
                  {featuredImageUrl ? (
                    <img
                      src={resolveUploadUrl(featuredImageUrl) ?? undefined}
                      alt=""
                      className="h-full w-full object-cover"
                    />
                  ) : (
                    <div className="text-muted-foreground flex h-full items-center justify-center">
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
                  <p className="text-muted-foreground text-xs">
                    Uploads are stored locally under <code>/uploads</code>. Remember to save changes
                    to keep your new image.
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
          {/* Collaboration status - shown between featured image and editor */}
          {collaborationEnabled && (
            <CollaborationStatusBadge
              connectionStatus={collaboration.connectionStatus}
              collaborators={collaboration.collaborators}
              isCollaborating={collaboration.isCollaborating}
            />
          )}
          {/* <DocumentEditor
            key={document.id}
            initialState={normalizedDocumentContent}
            onChange={setContentState}
            placeholder="Capture requirements, share decisions, or outline processes…"
            readOnly={!canEditDocument}
            showToolbar={canEditDocument}
          /> */}
          {/*
            Key is just document.id - we don't remount when entering collaborative mode.
            The CollaborationPlugin handles syncing the existing content to Yjs.
          */}
          <Editor
            key={document.id}
            editorSerializedState={normalizedDocumentContent}
            onSerializedChange={setContentState}
            readOnly={!canEditDocument}
            showToolbar={canEditDocument}
            className="max-h-[80vh]"
            mentionableUsers={mentionableUsers}
            documentName={title}
            collaborative={collaborationEnabled && collaboration.isReady}
            providerFactory={collaboration.providerFactory}
            // Always track changes so contentState stays updated for periodic saves
            trackChanges={true}
          />
          <div className="flex flex-wrap items-center gap-3">
            {canEditDocument ? (
              <>
                {/* When collaboration is active, changes sync in real-time */}
                {collaboration.isCollaborating ? (
                  <span className="text-muted-foreground text-sm">
                    Changes sync automatically with collaborators
                  </span>
                ) : (
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
                    <div className="flex items-center gap-2">
                      <Checkbox
                        id="autosave"
                        checked={autosaveEnabled}
                        onCheckedChange={(checked) => setAutosaveEnabled(checked === true)}
                      />
                      <Label htmlFor="autosave" className="cursor-pointer text-sm">
                        Autosave
                      </Label>
                    </div>
                    {!isDirty ? (
                      <span className="text-muted-foreground self-center text-sm">
                        All changes saved
                      </span>
                    ) : null}
                  </>
                )}
                {/* Always show collaboration toggle */}
                <div className="flex items-center gap-2">
                  <Checkbox
                    id="collaboration"
                    checked={collaborationEnabled}
                    onCheckedChange={(checked) => setCollaborationEnabled(checked === true)}
                  />
                  <Label htmlFor="collaboration" className="cursor-pointer text-sm">
                    Live collaboration
                  </Label>
                </div>
              </>
            ) : (
              <p className="text-muted-foreground text-sm">
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
                <p className="text-muted-foreground text-sm">
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
                          to="/projects/$projectId"
                          params={{ projectId: String(link.project_id) }}
                          className="font-medium hover:underline"
                        >
                          {link.project_name ?? `Project #${link.project_id}`}
                        </Link>
                        <p className="text-muted-foreground text-xs">
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
        <div className="space-y-2 xl:w-96">
          {commentsQuery.isError ? (
            <p className="text-destructive text-sm">Unable to load comments right now.</p>
          ) : null}
          <CommentSection
            entityType="document"
            entityId={parsedId}
            comments={commentsQuery.data ?? []}
            isLoading={commentsQuery.isLoading}
            onCommentCreated={handleCommentCreated}
            onCommentDeleted={handleCommentDeleted}
            canModerate={commentsCanModerate}
            initiativeId={document.initiative_id}
          />
        </div>
      </div>
    </div>
  );
};
