import {
  type ChangeEvent,
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { formatDistanceToNow } from "date-fns";
import type { SerializedEditorState } from "lexical";
import { ImagePlus, Loader2, PanelRight, ScrollText, Settings, X } from "lucide-react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";

import { API_BASE_URL } from "@/api/client";
import { notifyMentionsApiV1DocumentsDocumentIdMentionsPost } from "@/api/generated/documents/documents";
import { useDocument, useSetDocumentCache, useUpdateDocument } from "@/hooks/useDocuments";
import { useComments, useCommentsCache } from "@/hooks/useComments";
import { createEmptyEditorState, normalizeEditorState } from "@/lib/editorState";
import { CollaborationStatusBadge } from "@/components/documents/editor/CollaborationStatusBadge";
import { CommentSection } from "@/components/comments/CommentSection";
import { CreateWikilinkDocumentDialog } from "@/components/documents/CreateWikilinkDocumentDialog";
import { DocumentBacklinks } from "@/components/documents/DocumentBacklinks";
import { DocumentSidePanel, useDocumentSidePanel } from "@/components/documents/DocumentSidePanel";
import { DocumentSummary } from "@/components/documents/DocumentSummary";
import { TagPicker } from "@/components/tags/TagPicker";
import { useSetDocumentTags } from "@/hooks/useTags";

// Lazy load heavy components
const Editor = lazy(() =>
  import("@/components/documents/editor/editor").then((m) => ({ default: m.Editor }))
);
const FileDocumentViewer = lazy(() =>
  import("@/components/documents/FileDocumentViewer").then((m) => ({
    default: m.FileDocumentViewer,
  }))
);
import { findNewMentions } from "@/lib/mentionUtils";
import { useGuildPath } from "@/lib/guildUrl";
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
import type {
  CommentRead,
  DocumentProjectLink,
  TagSummary,
} from "@/api/generated/initiativeAPI.schemas";
import { uploadAttachment } from "@/lib/attachmentUtils";
import { useAIEnabled } from "@/hooks/useAIEnabled";
import { useAuth } from "@/hooks/useAuth";
import { useDateLocale } from "@/hooks/useDateLocale";
import { useGuilds } from "@/hooks/useGuilds";

export const DocumentDetailPage = () => {
  const { t } = useTranslation("documents");
  const dateLocale = useDateLocale();
  const { documentId } = useParams({ strict: false }) as { documentId: string };
  const parsedId = Number(documentId);
  const navigate = useNavigate();
  const setDocumentCache = useSetDocumentCache();
  const { user, token } = useAuth();
  const { activeGuildId } = useGuilds();
  const gp = useGuildPath();
  const sidePanel = useDocumentSidePanel();
  const { isEnabled: isAIEnabled } = useAIEnabled();
  const setDocumentTagsMutation = useSetDocumentTags();
  const [aiSummary, setAiSummary] = useState<string | null>(null);
  const [featuredImageUrl, setFeaturedImageUrl] = useState<string | null>(null);
  const [tags, setTags] = useState<TagSummary[]>([]);
  const [isUploadingFeaturedImage, setIsUploadingFeaturedImage] = useState(false);
  const [title, setTitle] = useState("");
  const [contentState, setContentState] = useState<SerializedEditorState>(createEmptyEditorState());
  const [autosaveEnabled, setAutosaveEnabled] = useState(true);
  const [collaborationEnabled, setCollaborationEnabled] = useState(true);
  const isAutosaveRef = useRef(false);
  const featuredImageInputRef = useRef<HTMLInputElement>(null);
  // Refs for sendBeacon - need latest values in event handlers
  const contentStateRef = useRef<{ documentId: number; content: SerializedEditorState } | null>(
    null
  );
  const collaboratingRef = useRef(false);
  const syncContentBeaconRef = useRef<(() => void) | null>(null);

  // Wikilink dialog state
  const [wikilinkDialogOpen, setWikilinkDialogOpen] = useState(false);
  const [wikilinkTitle, setWikilinkTitle] = useState("");
  const wikilinkUpdateCallbackRef = useRef<((documentId: number) => void) | null>(null);

  // Collaboration hook - only enable when we have a valid document ID
  const collaboration = useCollaboration({
    documentId: parsedId,
    enabled: collaborationEnabled && Number.isFinite(parsedId),
    onError: (error) => {
      // Show toast and fall back to autosave mode on collaboration error
      toast.error(t("detail.collaborationFailed"), {
        description: error.message || t("detail.collaborationFailedDescription"),
      });
      setCollaborationEnabled(false);
    },
  });

  const documentQuery = useDocument(Number.isFinite(parsedId) ? parsedId : null);

  const commentsQueryParams = { document_id: parsedId };
  const commentsCache = useCommentsCache(commentsQueryParams);
  const commentsQuery = useComments(commentsQueryParams, {
    enabled: Number.isFinite(parsedId),
  });

  const document = documentQuery.data;
  const normalizedDocumentContent = useMemo(
    () => normalizeEditorState(document?.content as SerializedEditorState | null | undefined),
    [document]
  );

  // Clear content state ref when document ID changes
  // The ref now tracks which document the content belongs to
  useEffect(() => {
    contentStateRef.current = null;
  }, [parsedId]);

  useEffect(() => {
    if (!document) {
      return;
    }
    setTitle(document.title);
    setContentState(normalizedDocumentContent);
    setFeaturedImageUrl(document.featured_image_url ?? null);
    setTags(document.tags ?? []);
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
    const myLevel = document.my_permission_level;
    return myLevel === "owner" || myLevel === "write";
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
    // Pure DAC: users with write or owner permission can moderate comments
    const myLevel = document.my_permission_level;
    return myLevel === "owner" || myLevel === "write";
  }, [document, user]);

  const mentionableUsers = useMemo(() => {
    return document?.initiative?.members?.map((member) => member.user) ?? [];
  }, [document?.initiative?.members]);

  // Check if user can create documents in this initiative
  const canCreateDocuments = useMemo(() => {
    if (!document?.initiative || !user) {
      return false;
    }
    // Check if user has create_docs permission via their role
    const membership = document.initiative.members?.find((m) => m.user?.id === user.id);
    if (!membership) {
      return false;
    }
    // can_create_docs is populated from the initiative membership role
    return membership.can_create_docs ?? false;
  }, [document?.initiative, user]);

  // Wikilink navigation handler
  const handleWikilinkNavigate = useCallback(
    (targetDocumentId: number) => {
      void navigate({
        to: gp(`/documents/${targetDocumentId}`),
      });
    },
    [navigate, gp]
  );

  // Wikilink create handler - opens dialog and stores update callback
  const handleWikilinkCreate = useCallback(
    (docTitle: string, onCreated: (documentId: number) => void) => {
      setWikilinkTitle(docTitle);
      wikilinkUpdateCallbackRef.current = onCreated;
      setWikilinkDialogOpen(true);
    },
    []
  );

  // After creating document via wikilink, update the wikilink then navigate
  const handleWikilinkDocumentCreated = useCallback(
    (newDocumentId: number) => {
      // Update the wikilink with the new document ID before navigating
      if (wikilinkUpdateCallbackRef.current) {
        wikilinkUpdateCallbackRef.current(newDocumentId);
        wikilinkUpdateCallbackRef.current = null;
      }
      // Capture collaboration state and document ID NOW, before navigation changes them
      const wasCollaborating = collaboratingRef.current;
      const sourceDocumentId = parsedId;
      // Explicitly sync content before navigating to ensure wikilinks are saved
      // Use setTimeout(0) to allow OnChangePlugin to fire first
      setTimeout(() => {
        // Sync directly using captured values (they may have changed by now)
        const stored = contentStateRef.current;
        if (
          wasCollaborating &&
          token &&
          activeGuildId &&
          stored &&
          stored.documentId === sourceDocumentId
        ) {
          const isAbsolute =
            API_BASE_URL.startsWith("http://") || API_BASE_URL.startsWith("https://");
          const baseUrl = isAbsolute ? API_BASE_URL : `${window.location.origin}${API_BASE_URL}`;
          const syncUrl = `${baseUrl}/collaboration/documents/${sourceDocumentId}/sync-content?token=${encodeURIComponent(token)}&guild_id=${activeGuildId}`;
          fetch(syncUrl, {
            method: "POST",
            body: JSON.stringify(stored.content),
            headers: { "Content-Type": "application/json" },
            keepalive: true,
          }).catch(() => {});
        }
        void navigate({
          to: gp(`/documents/${newDocumentId}`),
        });
      }, 0);
    },
    [navigate, gp, token, activeGuildId, parsedId]
  );

  const updateDocumentCommentCount = (delta: number) => {
    setDocumentCache(parsedId, (previous) => {
      if (!previous) return previous;
      const nextCount = Math.max(0, (previous.comment_count ?? 0) + delta);
      return { ...previous, comment_count: nextCount };
    });
  };

  const handleCommentCreated = (comment: CommentRead) => {
    commentsCache.addComment(comment);
    updateDocumentCommentCount(1);
  };

  const handleCommentDeleted = (commentId: number) => {
    commentsCache.removeComment(commentId);
    updateDocumentCommentCount(-1);
  };

  const handleCommentUpdated = (updatedComment: CommentRead) => {
    commentsCache.updateComment(updatedComment);
  };

  const saveDocument = useUpdateDocument({
    onSuccess: () => {
      if (!isAutosaveRef.current) {
        toast.success(t("detail.saved"));
      }
      // Fire-and-forget: notify users who were newly mentioned
      const newMentionIds = findNewMentions(normalizedDocumentContent, contentState);
      if (newMentionIds.length > 0) {
        notifyMentionsApiV1DocumentsDocumentIdMentionsPost(parsedId, {
          mentioned_user_ids: newMentionIds,
        }).catch((err) => console.error("Failed to notify mentions:", err));
      }
    },
    onSettled: () => {
      isAutosaveRef.current = false;
    },
  });

  // Handle content change - update both state and ref synchronously
  // This ensures contentStateRef is always up-to-date for sendBeacon
  // We track which document the content belongs to, to prevent syncing stale content
  const handleContentChange = useCallback(
    (newContent: SerializedEditorState) => {
      contentStateRef.current = { documentId: parsedId, content: newContent };
      setContentState(newContent);
    },
    [parsedId]
  );

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
        saveDocument.mutate({
          documentId: parsedId,
          data: {
            title: title?.trim(),
            content: contentState as unknown as Record<string, unknown>,
            featured_image_url: featuredImageUrl,
          },
        });
      }, 10000);
      return () => clearTimeout(timer);
    } else {
      if (!isDirty) {
        return;
      }
      const timer = setTimeout(() => {
        isAutosaveRef.current = true;
        saveDocument.mutate({
          documentId: parsedId,
          data: {
            title: title?.trim(),
            content: contentState as unknown as Record<string, unknown>,
            featured_image_url: featuredImageUrl,
          },
        });
      }, 2000);
      return () => clearTimeout(timer);
    }
  }, [
    autosaveEnabled,
    isDirty,
    canEditDocument,
    saveDocument,
    parsedId,
    title,
    contentState,
    featuredImageUrl,
    collaboration.isCollaborating,
  ]);

  // Sync content via sendBeacon on page unload to ensure content column stays updated
  // This is critical when users navigate away or close the tab during collaboration
  useEffect(() => {
    if (!canEditDocument || !token || !activeGuildId) {
      syncContentBeaconRef.current = null;
      return;
    }

    const syncContentBeacon = () => {
      // Only sync if we were collaborating (content might have changed via Yjs)
      if (!collaboratingRef.current) {
        return;
      }

      // Only sync if we have content for THIS document (prevents syncing stale content)
      const stored = contentStateRef.current;
      if (!stored || stored.documentId !== parsedId) {
        return;
      }

      // Build the sync URL
      const isAbsolute = API_BASE_URL.startsWith("http://") || API_BASE_URL.startsWith("https://");
      const baseUrl = isAbsolute ? API_BASE_URL : `${window.location.origin}${API_BASE_URL}`;
      const syncUrl = `${baseUrl}/collaboration/documents/${parsedId}/sync-content?token=${encodeURIComponent(token)}&guild_id=${activeGuildId}`;

      // Send content via fetch with keepalive (more reliable than sendBeacon, less likely to be blocked)
      fetch(syncUrl, {
        method: "POST",
        body: JSON.stringify(stored.content),
        headers: { "Content-Type": "application/json" },
        keepalive: true, // Ensures request completes even if page unloads
      }).catch(() => {}); // Silently ignore errors on page unload
    };

    // Store ref so it can be called from other handlers
    syncContentBeaconRef.current = syncContentBeacon;

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
      // Sync content when navigating away (component unmount or document change)
      syncContentBeacon();
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
      toast.error(t("detail.imageFileRequired"));
      return;
    }
    setIsUploadingFeaturedImage(true);
    try {
      const response = await uploadAttachment(file);
      setFeaturedImageUrl(response.url);
      isAutosaveRef.current = true;
      saveDocument.mutate({
        documentId: parsedId,
        data: {
          title: title?.trim(),
          content: contentState as unknown as Record<string, unknown>,
          featured_image_url: response.url,
        },
      });
      toast.success(t("detail.imageUploaded"));
    } catch (error) {
      console.error(error);
      toast.error(t("detail.imageUploadError"));
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

  const handleTagsChange = useCallback(
    (newTags: TagSummary[]) => {
      setTags(newTags);
      // Immediately save tag changes to the server
      setDocumentTagsMutation.mutate({
        documentId: parsedId,
        tagIds: newTags.map((tg) => tg.id),
      });
    },
    [parsedId, setDocumentTagsMutation]
  );

  if (!Number.isFinite(parsedId)) {
    return <p className="text-destructive">{t("detail.invalidId")}</p>;
  }

  if (documentQuery.isLoading) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("detail.loading")}
      </div>
    );
  }

  if (documentQuery.isError || !document) {
    return <p className="text-destructive">{t("detail.notFound")}</p>;
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
                    <Link to={gp(`/initiatives/${document.initiative.id}`)}>
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
        <div className="flex items-center gap-2">
          {canEditDocument && (
            <Button asChild variant="outline" size="sm">
              <Link
                to={gp(`/documents/${document.id}/settings`)}
                className="inline-flex items-center gap-2"
              >
                <Settings className="h-4 w-4" />
                {t("detail.settings")}
              </Link>
            </Button>
          )}
          <Button
            variant={sidePanel.isOpen ? "secondary" : "outline"}
            size="sm"
            onClick={sidePanel.toggle}
            title={sidePanel.isOpen ? t("detail.closePanel") : t("detail.openPanel")}
          >
            <PanelRight className="h-4 w-4" />
            <span className="sr-only">{t("detail.togglePanel")}</span>
          </Button>
        </div>
      </div>
      <div className="space-y-2">
        <Input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder={t("detail.titlePlaceholder")}
          className="text-2xl font-semibold"
          disabled={!canEditDocument}
        />
        <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-sm">
          {document.initiative ? (
            <Link
              to={gp(`/initiatives/${document.initiative.id}`)}
              className="inline-flex items-center gap-1 rounded-full border px-3 py-1"
            >
              <InitiativeColorDot color={document.initiative.color} />
              {document.initiative.name}
            </Link>
          ) : null}
          <span>
            {t("detail.updated", {
              date: formatDistanceToNow(new Date(document.updated_at), {
                addSuffix: true,
                locale: dateLocale,
              }),
            })}
          </span>
          {document.is_template ? <Badge variant="outline">{t("detail.template")}</Badge> : null}
        </div>
      </div>
      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>{t("detail.metadataTitle")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Featured image */}
            <div className="space-y-2">
              <Label>{t("detail.featuredImage")}</Label>
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
                            {t("detail.uploading")}
                          </>
                        ) : (
                          <>
                            <ImagePlus className="mr-2 h-4 w-4" />
                            {t("detail.uploadImage")}
                          </>
                        )}
                      </Button>
                      {featuredImageUrl ? (
                        <Button
                          type="button"
                          variant="ghost"
                          onClick={() => {
                            setFeaturedImageUrl(null);
                            isAutosaveRef.current = true;
                            saveDocument.mutate({
                              documentId: parsedId,
                              data: {
                                title: title?.trim(),
                                content: contentState as unknown as Record<string, unknown>,
                                featured_image_url: null,
                              },
                            });
                          }}
                          disabled={isUploadingFeaturedImage}
                        >
                          <X className="mr-2 h-4 w-4" />
                          {t("detail.removeImage")}
                        </Button>
                      ) : null}
                    </div>
                  ) : null}
                  <p className="text-muted-foreground text-xs">{t("detail.uploadHelpText")}</p>
                </div>
              </div>
            </div>

            {/* Tags */}
            <div className="space-y-2">
              <Label>{t("detail.tagsLabel")}</Label>
              <TagPicker
                selectedTags={tags}
                onChange={handleTagsChange}
                disabled={!canEditDocument}
                placeholder={t("detail.tagsPlaceholder")}
              />
            </div>
          </CardContent>
        </Card>

        {/* File document viewer */}
        {document.document_type === "file" && document.file_url ? (
          <Suspense
            fallback={
              <div className="flex h-96 items-center justify-center">
                <Loader2 className="text-muted-foreground h-8 w-8 animate-spin" />
              </div>
            }
          >
            <FileDocumentViewer
              fileUrl={document.file_url}
              contentType={document.file_content_type}
              originalFilename={document.original_filename}
              fileSize={document.file_size}
            />
          </Suspense>
        ) : (
          <>
            {/* Collaboration status - shown between featured image and editor */}
            {collaborationEnabled && (
              <CollaborationStatusBadge
                connectionStatus={collaboration.connectionStatus}
                collaborators={collaboration.collaborators}
                isCollaborating={collaboration.isCollaborating}
                isSynced={collaboration.isSynced}
              />
            )}
            {/*
              Key is just document.id - we don't remount when entering collaborative mode.
              The CollaborationPlugin handles syncing the existing content to Yjs.
            */}
            <Suspense
              fallback={
                <div className="flex h-96 items-center justify-center rounded-xl border">
                  <Loader2 className="text-muted-foreground h-8 w-8 animate-spin" />
                </div>
              }
            >
              <Editor
                key={parsedId}
                editorSerializedState={normalizedDocumentContent}
                onSerializedChange={handleContentChange}
                readOnly={!canEditDocument}
                showToolbar={canEditDocument}
                className="max-h-[80vh]"
                mentionableUsers={mentionableUsers}
                documentName={title}
                collaborative={collaborationEnabled && collaboration.isReady}
                providerFactory={collaboration.providerFactory}
                // Always track changes so contentState stays updated for periodic saves
                trackChanges={true}
                isSynced={collaboration.isSynced}
                // Wikilinks support
                initiativeId={document.initiative_id}
                onWikilinkNavigate={handleWikilinkNavigate}
                onWikilinkCreate={handleWikilinkCreate}
              />
            </Suspense>
            <div className="flex flex-wrap items-center gap-3">
              {canEditDocument ? (
                <>
                  {/* When collaboration is active, changes sync in real-time */}
                  {collaboration.isCollaborating ? (
                    <span className="text-muted-foreground text-sm">
                      {t("detail.collaborationDescription")}
                    </span>
                  ) : (
                    <>
                      <Button
                        type="button"
                        onClick={() =>
                          saveDocument.mutate({
                            documentId: parsedId,
                            data: {
                              title: title?.trim(),
                              content: contentState as unknown as Record<string, unknown>,
                              featured_image_url: featuredImageUrl,
                            },
                          })
                        }
                        disabled={!isDirty || saveDocument.isPending}
                      >
                        {saveDocument.isPending ? (
                          <>
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            {t("detail.saving")}
                          </>
                        ) : (
                          t("detail.saveChanges")
                        )}
                      </Button>
                      <div className="flex items-center gap-2">
                        <Checkbox
                          id="autosave"
                          checked={autosaveEnabled}
                          onCheckedChange={(checked) => setAutosaveEnabled(checked === true)}
                        />
                        <Label htmlFor="autosave" className="cursor-pointer text-sm">
                          {t("detail.autosave")}
                        </Label>
                      </div>
                      {!isDirty ? (
                        <span className="text-muted-foreground self-center text-sm">
                          {t("detail.allChangesSaved")}
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
                      {t("detail.liveCollaboration")}
                    </Label>
                  </div>
                </>
              ) : (
                <p className="text-muted-foreground text-sm">{t("detail.readOnly")}</p>
              )}
            </div>
          </>
        )}

        <Card>
          <CardHeader>
            <CardTitle>{t("detail.attachedProjects")}</CardTitle>
          </CardHeader>
          <CardContent>
            {attachedProjects.length === 0 ? (
              <p className="text-muted-foreground text-sm">{t("detail.noAttachedProjects")}</p>
            ) : (
              <div className="space-y-2">
                {attachedProjects.map((link) => (
                  <div
                    key={`${document.id}-${link.project_id}`}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-lg border px-4 py-3"
                  >
                    <div className="space-y-0.5">
                      <Link
                        to={gp(`/projects/${link.project_id}`)}
                        className="font-medium hover:underline"
                      >
                        {link.project_name ?? t("detail.projectFallback", { id: link.project_id })}
                      </Link>
                      <p className="text-muted-foreground text-xs">
                        {t("detail.attached", {
                          date: formatDistanceToNow(new Date(link.attached_at), {
                            addSuffix: true,
                            locale: dateLocale,
                          }),
                        })}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Backlinks - documents that link to this one */}
        <DocumentBacklinks documentId={parsedId} />
      </div>

      {/* Side panel for AI summary and comments */}
      <DocumentSidePanel
        isOpen={sidePanel.isOpen}
        onOpenChange={sidePanel.setIsOpen}
        showSummaryTab={document.document_type !== "file" && isAIEnabled}
        summaryContent={
          <DocumentSummary
            documentId={parsedId}
            summary={aiSummary}
            onSummaryChange={setAiSummary}
          />
        }
        commentsContent={
          <>
            {commentsQuery.isError && (
              <p className="text-destructive mb-4 text-sm">{t("detail.commentsLoadError")}</p>
            )}
            <CommentSection
              entityType="document"
              entityId={parsedId}
              comments={commentsQuery.data ?? []}
              isLoading={commentsQuery.isLoading}
              onCommentCreated={handleCommentCreated}
              onCommentDeleted={handleCommentDeleted}
              onCommentUpdated={handleCommentUpdated}
              canModerate={commentsCanModerate}
              initiativeId={document.initiative_id}
            />
          </>
        }
      />

      {/* Wikilink create document dialog */}
      <CreateWikilinkDocumentDialog
        open={wikilinkDialogOpen}
        onOpenChange={setWikilinkDialogOpen}
        title={wikilinkTitle}
        initiativeId={document.initiative_id}
        canCreate={canCreateDocuments}
        onCreated={handleWikilinkDocumentCreated}
      />
    </div>
  );
};
