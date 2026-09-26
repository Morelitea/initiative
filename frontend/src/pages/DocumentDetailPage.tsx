import { Link, useParams } from "@tanstack/react-router";
import type { SerializedEditorState } from "lexical";
import {
  ChevronDown,
  ChevronUp,
  ImagePlus,
  ListTree,
  Loader2,
  Maximize2,
  Minimize2,
  PanelRight,
  Save,
  ScrollText,
  SearchX,
  Settings,
  ShieldAlert,
  X,
} from "lucide-react";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { API_BASE_URL } from "@/api/client";
import { notifyMentionsApiV1CGuildIdDocumentsDocumentIdMentionsPost } from "@/api/generated/documents/documents";
import type {
  PropertyDefinitionRead,
  PropertySummary,
  TagSummary,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolCommentsPanel } from "@/components/comments/ToolCommentsPanel";
import {
  DocumentOutlinePanel,
  DocumentOutlineScope,
  useDocumentOutline,
} from "@/components/documents/DocumentOutline";
import { DocumentSidePanel, useDocumentSidePanel } from "@/components/documents/DocumentSidePanel";
import { DocumentSummary } from "@/components/documents/DocumentSummary";
import { DOCUMENT_BODIES } from "@/components/documents/detail/documentBodies";
import { CollaborationStatusBadge } from "@/components/documents/editor/CollaborationStatusBadge";
import { clearWhiteboardSceneCache } from "@/components/documents/whiteboardSceneCache";
import { ToolRelationsPanel } from "@/components/entities/ToolRelationsPanel";
import { AddPropertyButton } from "@/components/properties/AddPropertyButton";
import { PropertyList } from "@/components/properties/PropertyList";
import { StatusMessage } from "@/components/StatusMessage";
import { DocumentDetailSkeleton } from "@/components/skeletons/PageSkeletons";
import { TagPicker } from "@/components/tags/TagPicker";
import { ToolBreadcrumb } from "@/components/tools/ToolBreadcrumb";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import { ImagePicker } from "@/components/ui/image-picker";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAIEnabled } from "@/hooks/useAIEnabled";
import { useAuth } from "@/hooks/useAuth";
import { useCanonicalInitiativeId } from "@/hooks/useCanonicalInitiativeId";
import { useCollaboration } from "@/hooks/useCollaboration";
import { useDocument, useSetDocumentCache, useUpdateDocument } from "@/hooks/useDocuments";
import { useGuilds } from "@/hooks/useGuilds";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";
import { useReadOnOpen } from "@/hooks/useNotifications";
import { useSetDocumentProperties } from "@/hooks/useProperties";
import { useRecordRecentView } from "@/hooks/useRecents";
import { useRelativeTime } from "@/hooks/useRelativeTime";
import { useServerForm } from "@/hooks/useServerForm";
import { useSetToolTags } from "@/hooks/useToolTags";
import { uploadAttachment } from "@/lib/attachmentUtils";
import { toast } from "@/lib/chesterToast";
import { getHttpStatus } from "@/lib/errorMessage";
import { useGuildPath } from "@/lib/guildUrl";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import { findNewMentions } from "@/lib/mentionUtils";
import { getItem, setItem } from "@/lib/storage";
import { initiativeRoute, toolListRoute, toolSettingsRoute } from "@/lib/tools";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { cn } from "@/lib/utils";
import { CollaborationError } from "@/lib/yjs/CollaborationProvider";

export const DocumentDetailPage = () => {
  const { t } = useTranslation(["documents", "properties", "common"]);
  const { guildId: guildIdParam, documentId } = useParams({ strict: false }) as {
    guildId: string;
    documentId: string;
  };
  const parsedId = Number(documentId);
  const setDocumentCache = useSetDocumentCache();
  const { user, token } = useAuth();
  const { activeGuildId } = useGuilds();
  const guildId = Number(guildIdParam);
  const gp = useGuildPath();
  const sidePanel = useDocumentSidePanel();
  const outline = useDocumentOutline();
  const { isEnabled: isAIEnabled } = useAIEnabled();
  const setDocumentTagsMutation = useSetToolTags(Tool.document);
  const [aiSummary, setAiSummary] = useState<string | null>(null);
  const [featuredImageUrl, setFeaturedImageUrl] = useState<string | null>(null);
  const [tags, setTags] = useState<TagSummary[]>([]);
  // Locally-added property definitions that don't yet have a persisted value.
  // Rendered alongside `document.properties` as empty-valued stubs so the user
  // can fill them in; PropertyList's PUT persists them once a value is set.
  const [pendingProperties, setPendingProperties] = useState<PropertyDefinitionRead[]>([]);
  const setDocumentPropertiesMutation = useSetDocumentProperties();
  // Persisted collapse state for the metadata card (mirrors the pattern used
  // by the Documents section on project pages).
  const metadataCollapsedStorageKey = "document:metadataCollapsed";
  const [isMetadataCollapsed, setIsMetadataCollapsed] = useState<boolean>(
    () => getItem(metadataCollapsedStorageKey) === "true"
  );
  const [isUploadingFeaturedImage, setIsUploadingFeaturedImage] = useState(false);
  // What the body last reported, and for which document: the page's copy of
  // the edit, read by the dirty check and the saves. Nothing until the body
  // reports — the editor reads the saved body once, at mount, and this copy is
  // never replaced by a later answer, so the two cannot come to disagree.
  const [edited, setEdited] = useState<{ documentId: number; content: unknown } | null>(null);
  const [autosaveEnabled, setAutosaveEnabled] = useState(true);
  const [collaborationEnabled, setCollaborationEnabled] = useState(true);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const isAutosaveRef = useRef(false);
  // The same, for handlers that run outside a render (the room's handover as
  // the page leaves).
  const editedRef = useRef(edited);
  const collaboratingRef = useRef(false);
  const parsedIdRef = useRef(parsedId);
  parsedIdRef.current = parsedId;
  // What this tab last rendered, for the room to save as the page leaves —
  // with the socket, or with the edits handed over when it is gone.
  const finalCollabContent = useCallback(() => {
    const stored = editedRef.current;
    return stored?.documentId === parsedIdRef.current ? stored.content : undefined;
  }, []);

  // Network status for offline detection
  const { isOnline } = useNetworkStatus();

  const documentQuery = useDocument(Number.isFinite(parsedId) ? parsedId : null);
  const document = documentQuery.data;
  const bodyKind = document ? DOCUMENT_BODIES[document.document_type] : null;
  // Whether this document's room is in play: a body that joins none has no
  // work in a Yjs doc to hand over, and no connection to show.
  const joinsRoom = collaborationEnabled && (!bodyKind || bodyKind.roomSyncMs !== undefined);

  // Collaboration hook - only enable when we have a valid document ID and a
  // body that joins a room. The WebSocket opens lazily when something calls
  // `providerFactory`: Lexical's CollaborationPlugin (inside <Editor>) or a
  // body binding its own editor to the room's Y.Doc. Leaving `enabled` on
  // while the type is still loading matters: gating on the fetched type would
  // delay Lexical's CollaborationPlugin initial mount past the first render
  // where `<Editor>` appears, which regresses the collab bootstrap and leaves
  // Lexical stuck on "Syncing document…".
  const collaboration = useCollaboration({
    socketPath: Number.isFinite(parsedId) ? `documents/${parsedId}/collaborate` : null,
    finalContent: finalCollabContent,
    enabled: joinsRoom && Number.isFinite(parsedId),
    onError: (error) => {
      toast.error(t("detail.collaborationFailed"), {
        description: error.message || t("detail.collaborationFailedDescription"),
      });
      // Only a refusal ends the session. A lost connection leaves the provider
      // trying, and turning collaboration off here would tear down the socket
      // that is going to carry this tab's work back — anything typed during an
      // outage lives in the local doc until the sync handshake hands it over.
      if (!(error instanceof CollaborationError) || !error.recoverable) {
        setCollaborationEnabled(false);
      }
    },
  });

  // The name follows the document until somebody starts renaming it: a
  // refetch — a comment on this document, a window coming back to the front —
  // must not take a half-typed name away, and a rename by somebody else must
  // still arrive while nobody here is typing one.
  const titleField = useServerForm(
    document,
    (loaded) => ({ title: loaded?.name ?? "" }),
    document?.id
  );
  const title = titleField.values.title;
  const setTitle = (next: string) => titleField.set({ title: next });
  // Whether the name field is being typed in right now. Autosave waits it out
  // so the Save button beside the field stays put for as long as it is wanted.
  const [titleHasFocus, setTitleHasFocus] = useState(false);
  // The path supplies the initiative while this loads, but the entity is the
  // authority once it arrives — a URL naming a different one is corrected
  // rather than left to build links into an initiative it isn't in.
  const initiativeId = useCanonicalInitiativeId(document?.initiative_id);
  const relativeUpdatedAt = useRelativeTime(document?.updated_at);

  // Track recently viewed documents so the layout header tabs bar can surface
  // them. Mirrors the pattern in ProjectDetailPage.
  const recordViewMutation = useRecordRecentView("document", guildId);
  const viewedDocumentId = documentQuery.data?.id;
  useReadOnOpen(Tool.document, viewedDocumentId);
  useEffect(() => {
    if (!viewedDocumentId) return;
    recordViewMutation.mutate(viewedDocumentId);
  }, [viewedDocumentId, recordViewMutation.mutate]);

  // Which document the featured image below was filled in from. Filled in
  // once per document, for the reason the body's copy is: a later answer
  // replacing it would leave the page believing it matches the server.
  const seededDocumentRef = useRef<number | null>(null);

  useEffect(() => {
    editedRef.current = null;
    seededDocumentRef.current = null;
  }, [parsedId]);

  // Lock body scroll while the editor is in fullscreen so wheel events
  // over the overlay don't bleed through to the page beneath.
  useEffect(() => {
    if (!isFullscreen) return;
    const body = window.document.body;
    const previousOverflow = body.style.overflow;
    body.style.overflow = "hidden";
    return () => {
      body.style.overflow = previousOverflow;
    };
  }, [isFullscreen]);

  useEffect(() => {
    if (!document) {
      return;
    }
    // Tags are written the moment they are picked, so they go on following the
    // server whether or not the rest has been filled in.
    setTags(document.tags ?? []);
    if (seededDocumentRef.current === document.id) {
      return;
    }
    // Opening a document already in the React Query cache renders it from that
    // snapshot before this mount's fetch has been anywhere. It predates
    // whatever else has happened since, so it is filled in but not committed:
    // every answer up to and including this mount's own is taken, and only
    // that one closes the door.
    if (documentQuery.isFetchedAfterMount) {
      seededDocumentRef.current = document.id;
    }
    setFeaturedImageUrl(document.featured_image_url ?? null);
  }, [document, documentQuery.isFetchedAfterMount]);

  const saved = useMemo(
    () => (document ? DOCUMENT_BODIES[document.document_type].saved(document) : undefined),
    [document]
  );
  const editedBody = edited?.documentId === parsedId ? edited.content : undefined;
  const savedJson = useMemo(() => JSON.stringify(saved), [saved]);
  const editedJson = useMemo(() => JSON.stringify(editedBody), [editedBody]);
  // What a save carries for the body: the edit, or the saved body echoed back.
  const contentForSave = (editedBody ?? saved) as Record<string, unknown>;
  // Server-computed: already capped at "read" when the guild's content is
  // frozen (read_only lifecycle status) or access is via a read-level grant.
  // Write or owner may also moderate the document's comments.
  const canEditDocument = Boolean(user) && Boolean(document?.can.edit);
  // Split by what a save would carry: a rename and the rest of the document
  // are committed on different terms — see the autosave effect.
  const nameIsDirty = Boolean(document) && title?.trim() !== document?.name?.trim();
  const bodyIsDirty =
    (editedBody !== undefined && editedJson !== savedJson) ||
    (document?.featured_image_url ?? null) !== featuredImageUrl;
  const isDirty = canEditDocument && (nameIsDirty || bodyIsDirty);

  const titleIsDirty = canEditDocument && nameIsDirty;

  const updateDocumentCommentCount = (delta: number) => {
    setDocumentCache(parsedId, (previous) => {
      if (!previous) return previous;
      const nextCount = Math.max(0, (previous.comment_count ?? 0) + delta);
      return { ...previous, comment_count: nextCount };
    });
  };

  const saveDocument = useUpdateDocument(parsedId, {
    // Suppress the default error toast when the save failed because we're offline —
    // the persistent offline toast already explains the situation to the user.
    // Using `isOnline` (not `navigator.onLine`) so native WebView users get the
    // same behavior: the Capacitor Network plugin is authoritative on native.
    suppressErrorToast: () => !isOnline,
    onSuccess: (_updated, sent) => {
      // Only if the field still holds the name this save carried: an autosave
      // that started before the last keystroke must not mark it saved. A save
      // that carried no name at all (one made while the field was being typed
      // in) settles nothing.
      if (typeof sent.name === "string") {
        titleField.settle({ title: sent.name });
      }
      if (!isAutosaveRef.current) {
        toast.success(t("detail.saved"));
      }
      // Clear the write-ahead cache — the DB is now up-to-date.
      clearWhiteboardSceneCache(parsedId);
      // Fire-and-forget: notify users who were newly mentioned
      const newMentionIds = findNewMentions(
        saved as SerializedEditorState | undefined,
        editedBody as SerializedEditorState | undefined
      );
      if (newMentionIds.length > 0) {
        notifyMentionsApiV1CGuildIdDocumentsDocumentIdMentionsPost(guildId, parsedId, {
          mentioned_user_ids: newMentionIds,
        }).catch((err) => console.error("Failed to notify mentions:", err));
      }
    },
    onSettled: () => {
      isAutosaveRef.current = false;
    },
  });

  // Updates the ref with the state, so the room's handover never reads an
  // older edit than the one on screen.
  const handleBodyChange = useCallback(
    (content: unknown) => {
      const next = { documentId: parsedId, content };
      editedRef.current = next;
      setEdited(next);
    },
    [parsedId]
  );

  useEffect(() => {
    const resumed = collaboration.isCollaborating && !collaboratingRef.current;
    collaboratingRef.current = collaboration.isCollaborating;
    // The handshake brings this tab's Yjs work back into the room, but the
    // content column moves only when an editor reports a rendering — and after
    // an outage there may be nothing further to type. Report one on arrival.
    if (resumed && canEditDocument) {
      const stored = editedRef.current;
      if (stored && stored.documentId === parsedId) {
        collaboration.sendContent(stored.content);
      }
    }
  }, [
    collaboration.isCollaborating,
    collaboration.sendContent,
    collaboration,
    canEditDocument,
    parsedId,
  ]);

  // Autosave with debounce
  useEffect(() => {
    if (!autosaveEnabled || !canEditDocument || saveDocument.isPending) {
      return;
    }
    // Skip all REST saves while offline — edits remain in local state and will
    // be flushed when the network returns (see reconnect effect below).
    if (!isOnline) {
      return;
    }
    // A rename in progress belongs to the person typing it: taking it retires
    // the Save button beside the field mid-reach. The name waits for the field
    // to be let go — leaving the page still flushes it (see the unmount/unload
    // flush below) — while the body carries on saving on its own schedule.
    const savesName = nameIsDirty && !titleHasFocus;
    // Nothing this pass would write. The collaborating branch below checks
    // this too: the room owns the content column while it is live, but an open
    // document nobody is editing has no rendering to report and no name to send.
    if (!savesName && !bodyIsDirty) {
      return;
    }
    // When collaborating, sync content periodically to keep the content
    // column updated for non-collab readers, at the body's own pace.
    if (collaboration.isCollaborating) {
      const timer = setTimeout(() => {
        // The room is the writer of this document's content column while it
        // is live: it saves the JSON and the Yjs state from one snapshot, so
        // the two always describe the same moment. Every tab reports to it,
        // and it reconciles them.
        collaboration.sendContent(contentForSave);
        isAutosaveRef.current = true;
        saveDocument.mutate({
          ...(savesName ? { name: title?.trim() } : null),
          featured_image_url: featuredImageUrl,
        });
      }, bodyKind?.roomSyncMs ?? 10_000);
      return () => clearTimeout(timer);
    } else {
      const timer = setTimeout(() => {
        isAutosaveRef.current = true;
        saveDocument.mutate({
          ...(savesName ? { name: title?.trim() } : null),
          content: contentForSave,
          featured_image_url: featuredImageUrl,
        });
      }, 2000);
      return () => clearTimeout(timer);
    }
  }, [
    autosaveEnabled,
    nameIsDirty,
    bodyIsDirty,
    canEditDocument,
    saveDocument,
    parsedId,
    title,
    contentForSave,
    featuredImageUrl,
    collaboration.isCollaborating,
    collaboration.sendContent,
    isOnline,
    bodyKind,
    titleHasFocus,
  ]);

  // When connectivity returns after being offline, flush any pending dirty
  // changes immediately. This handles the case where the user stopped typing
  // while offline (so the 2s debounce already cleared) and is necessary
  // because the autosave effect only fires on new edits.
  const prevOnlineRef = useRef(isOnline);
  useEffect(() => {
    const wasOffline = !prevOnlineRef.current;
    prevOnlineRef.current = isOnline;
    if (!wasOffline || !isOnline) return;
    if (!canEditDocument || saveDocument.isPending) return;
    if (joinsRoom) {
      // The work done while offline is in this tab's Yjs doc, and the sync
      // handshake is what carries it over — merged with whatever the rest of
      // the room did meanwhile, rather than written over it. The REST path
      // carries a rendering rather than the work itself, and the server keeps
      // the content column with the room for that reason.
      collaboration.resume();
      return;
    }
    if (!isDirty) return;
    // Do NOT set isAutosaveRef here — we want the success toast to fire so
    // users who edited while offline get explicit confirmation their work
    // was persisted after reconnecting.
    saveDocument.mutate({
      name: title?.trim(),
      content: contentForSave,
      featured_image_url: featuredImageUrl,
    });
  }, [
    isOnline,
    canEditDocument,
    isDirty,
    saveDocument,
    parsedId,
    joinsRoom,
    collaboration,
    title,
    contentForSave,
    featuredImageUrl,
  ]);

  // ── Unmount / unload flush ──────────────────────────────────────────
  // Mirrors the current save payload into a ref so the unmount flush has
  // the most recent data even if the autosave debounce was cancelled
  // mid-flight (e.g. user draws a shape and refreshes within 2 seconds).
  // Without this, the autosave timer is cleared on unmount and the edit
  // is lost. Especially important for whiteboards where a single drawing
  // action comfortably fits inside the debounce window.
  const pendingSavePayloadRef = useRef<{
    documentId: number;
    data: {
      name?: string;
      content: Record<string, unknown>;
      featured_image_url: string | null;
    };
  } | null>(null);
  useEffect(() => {
    if (!canEditDocument || !isDirty) {
      pendingSavePayloadRef.current = null;
      return;
    }
    pendingSavePayloadRef.current = {
      documentId: parsedId,
      data: {
        name: title?.trim(),
        content: contentForSave,
        featured_image_url: featuredImageUrl,
      },
    };
  }, [canEditDocument, isDirty, parsedId, title, contentForSave, featuredImageUrl]);

  // Hold token and activeGuildId in refs so the flush closure always sees
  // the latest values without the effect needing to re-run on JWT rotation.
  // Without this, a token refresh would trigger the cleanup → flush() →
  // null the pending ref, and the ref-populating effect wouldn't re-run
  // (its deps didn't change), silently dropping the next pending save.
  const tokenRef = useRef(token);
  const activeGuildIdRef = useRef(activeGuildId);
  useEffect(() => {
    tokenRef.current = token;
  }, [token]);
  useEffect(() => {
    activeGuildIdRef.current = activeGuildId;
  }, [activeGuildId]);

  useEffect(() => {
    const flush = () => {
      const pending = pendingSavePayloadRef.current;
      if (!pending || !tokenRef.current || !activeGuildIdRef.current) return;
      const isAbsolute = API_BASE_URL.startsWith("http://") || API_BASE_URL.startsWith("https://");
      const baseUrl = isAbsolute ? API_BASE_URL : `${window.location.origin}${API_BASE_URL}`;
      // The guild rides in the path (`/c/{guildId}/`) — guild context is per-tab
      // from the URL; the page required entering this document's guild.
      const url = `${baseUrl}/c/${activeGuildIdRef.current}/documents/${pending.documentId}`;
      fetch(url, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${tokenRef.current}`,
        },
        body: JSON.stringify(pending.data),
        keepalive: true,
      }).catch(() => {});
      pendingSavePayloadRef.current = null;
    };

    const handleBeforeUnload = () => flush();
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => {
      flush();
      window.removeEventListener("beforeunload", handleBeforeUnload);
    };
  }, []);

  // Persistent offline toast with mode-aware copy
  useEffect(() => {
    const TOAST_ID = "editor-offline";
    if (isOnline) {
      toast.dismiss(TOAST_ID);
      return;
    }
    const message = collaboration.isCollaborating
      ? t("detail.offline.collaborative")
      : t("detail.offline.nonCollaborative");
    toast.warning(message, { id: TOAST_ID, duration: Infinity });
    return () => {
      toast.dismiss(TOAST_ID);
    };
  }, [isOnline, collaboration.isCollaborating, t]);

  // Every save the user asks for by hand — the Save button, Ctrl+S, a featured
  // image change — goes through here. While the editing room is live it is
  // the writer of the content column and refuses a body sent any other way,
  // so the body goes to the room and the PATCH carries only the rest, the
  // same split the autosave makes. Whether to save while one is already in
  // flight is the caller's call: the buttons hold off, an image change does
  // not, because it is the only save that change would get.
  const saveNow = useCallback(
    (overrides?: { featured_image_url?: string | null }) => {
      if (!canEditDocument) return;
      const payload = {
        name: title?.trim(),
        featured_image_url: featuredImageUrl,
        ...overrides,
      };
      if (collaboration.isCollaborating) {
        collaboration.sendContent(contentForSave);
        saveDocument.mutate(payload);
        return;
      }
      saveDocument.mutate({ ...payload, content: contentForSave });
    },
    [
      canEditDocument,
      saveDocument,
      title,
      featuredImageUrl,
      contentForSave,
      collaboration.isCollaborating,
      collaboration.sendContent,
    ]
  );

  // Ctrl+S / Cmd+S manual save shortcut
  useEffect(() => {
    if (!canEditDocument) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "s" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        if (!saveDocument.isPending) saveNow();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [canEditDocument, saveDocument.isPending, saveNow]);

  const handleFeaturedImageChange = async (file: File) => {
    if (!canEditDocument) {
      return;
    }
    if (!file.type.startsWith("image/")) {
      toast.error(t("detail.imageFileRequired"));
      return;
    }
    setIsUploadingFeaturedImage(true);
    try {
      const response = await uploadAttachment(guildId, file);
      setFeaturedImageUrl(response.url);
      isAutosaveRef.current = true;
      saveNow({ featured_image_url: response.url });
      toast.success(t("detail.imageUploaded"));
    } catch (error) {
      console.error(error);
      toast.error(t("detail.imageUploadError"));
    } finally {
      setIsUploadingFeaturedImage(false);
    }
  };

  const handleTagsChange = useCallback(
    (newTags: TagSummary[]) => {
      setTags(newTags);
      // Immediately save tag changes to the server
      setDocumentTagsMutation.mutate({
        id: parsedId,
        tagIds: newTags.map((tg) => tg.id),
      });
    },
    [parsedId, setDocumentTagsMutation]
  );

  // Combine server-attached properties with locally-added stubs (definitions
  // the user just picked but hasn't given a value yet). Drop any pending
  // entries that the server has since returned as attached.
  const serverProperties = useMemo<PropertySummary[]>(() => document?.properties ?? [], [document]);
  const serverPropertyIds = useMemo(
    () => new Set(serverProperties.map((p) => p.property_id)),
    [serverProperties]
  );
  const combinedProperties = useMemo<PropertySummary[]>(() => {
    const stubs: PropertySummary[] = pendingProperties
      .filter((def) => !serverPropertyIds.has(def.id))
      .map((def) => ({
        property_id: def.id,
        name: def.name,
        type: def.type,
        options: def.options ?? null,
        value: null,
      }));
    return [...serverProperties, ...stubs];
  }, [serverProperties, pendingProperties, serverPropertyIds]);
  const combinedPropertyIds = useMemo(
    () => combinedProperties.map((p) => p.property_id),
    [combinedProperties]
  );

  useEffect(() => {
    if (pendingProperties.length === 0) return;
    setPendingProperties((prev) => prev.filter((def) => !serverPropertyIds.has(def.id)));
  }, [serverPropertyIds, pendingProperties.length]);

  const handleAddProperty = useCallback(
    (definition: PropertyDefinitionRead) => {
      setPendingProperties((prev) =>
        prev.some((def) => def.id === definition.id) ? prev : [...prev, definition]
      );
      // Persist the attached-but-empty row immediately so the property
      // survives a refresh before the user enters a value. We reuse the
      // replace-all PUT shape: include every currently-attached property
      // plus the newly-added one with value=null.
      if (!Number.isFinite(parsedId) || serverPropertyIds.has(definition.id)) return;
      const values = [
        ...serverProperties.map((p) => ({
          property_id: p.property_id,
          value:
            p.type === "user_reference" && p.value && typeof p.value === "object" && "id" in p.value
              ? (p.value as { id: number }).id
              : (p.value ?? null),
        })),
        { property_id: definition.id, value: null },
      ];
      setDocumentPropertiesMutation.mutate({
        documentId: parsedId,
        values: { values },
      });
    },
    [parsedId, serverProperties, serverPropertyIds, setDocumentPropertiesMutation]
  );

  if (!Number.isFinite(parsedId)) {
    return <p className="text-destructive">{t("detail.invalidId")}</p>;
  }

  if (documentQuery.isLoading) {
    return <DocumentDetailSkeleton label={t("detail.loading")} />;
  }

  if (documentQuery.isError || !document) {
    const status = getHttpStatus(documentQuery.error);
    const backTo = gp(toolListRoute(Tool.document, initiativeId));
    const backLabel = t("detail.backToDocuments");

    if (status === 403) {
      return (
        <StatusMessage
          icon={<ShieldAlert />}
          title={t("detail.noAccess")}
          description={t("detail.noAccessDescription")}
          backTo={backTo}
          backLabel={backLabel}
        />
      );
    }
    return (
      <StatusMessage
        icon={<SearchX />}
        title={t("detail.notFound")}
        description={t("detail.notFoundDescription")}
        backTo={backTo}
        backLabel={backLabel}
      />
    );
  }

  const { Body, Actions, framed, editable, prose } = DOCUMENT_BODIES[document.document_type];
  const showSummaryTab = prose && isAIEnabled;
  const body = (
    <Suspense
      fallback={
        <div className={cn("flex h-96 items-center justify-center", framed && "rounded-xl border")}>
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      }
    >
      {/* Keyed by document alone: entering collaborative mode does not remount —
          the CollaborationPlugin syncs the existing content to Yjs. */}
      <Body
        key={document.id}
        document={document}
        saved={saved}
        canEdit={canEditDocument}
        collaboration={collaboration}
        live={collaborationEnabled && collaboration.isReady}
        settled={documentQuery.isFetchedAfterMount}
        title={title}
        className={cn(isFullscreen && "h-full max-h-none min-h-0 flex-1")}
        onChange={handleBodyChange}
      />
    </Suspense>
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <ToolBreadcrumb
          tool={Tool.document}
          initiativeId={document.initiative_id}
          trail={[{ label: document.name }]}
        />
        <div className="flex items-center gap-2">
          {canEditDocument && (
            <Button asChild variant="outline" size="sm">
              <Link
                to={gp(toolSettingsRoute(Tool.document, initiativeId, document.id))}
                className="inline-flex items-center gap-2"
              >
                <Settings className="h-4 w-4" />
                {t("detail.settings")}
              </Link>
            </Button>
          )}
          {showSummaryTab && (
            <Button
              variant={sidePanel.isOpen ? "secondary" : "outline"}
              size="sm"
              onClick={sidePanel.toggle}
              title={sidePanel.isOpen ? t("detail.closePanel") : t("detail.openPanel")}
            >
              <PanelRight className="h-4 w-4" />
              <span className="sr-only">{t("detail.togglePanel")}</span>
            </Button>
          )}
        </div>
      </div>
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            onFocus={() => setTitleHasFocus(true)}
            onBlur={() => setTitleHasFocus(false)}
            placeholder={t("detail.titlePlaceholder")}
            className="min-w-0 font-semibold text-2xl"
            disabled={!canEditDocument}
          />
          {titleIsDirty ? (
            <Button
              type="button"
              size="sm"
              onClick={() => {
                if (!saveDocument.isPending) saveNow();
              }}
              disabled={saveDocument.isPending}
              className="shrink-0"
            >
              {saveDocument.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              {t("common:save")}
            </Button>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-muted-foreground text-sm">
          {document.initiative ? (
            <Link
              to={gp(initiativeRoute(document.initiative.id))}
              className="inline-flex items-center gap-1 rounded-full border px-3 py-1"
            >
              <InitiativeColorDot color={document.initiative.color} />
              {document.initiative.name}
            </Link>
          ) : null}
          <span>{t("detail.updated", { date: relativeUpdatedAt })}</span>
          {document.is_template ? <Badge variant="outline">{t("detail.template")}</Badge> : null}
        </div>
      </div>
      <div className="space-y-6">
        <Card>
          <Collapsible
            open={!isMetadataCollapsed}
            onOpenChange={(open) => {
              const collapsed = !open;
              setIsMetadataCollapsed(collapsed);
              setItem(metadataCollapsedStorageKey, collapsed.toString());
            }}
          >
            <CardHeader>
              <div className="inline-flex items-center gap-2">
                <CardTitle>{t("detail.metadataTitle")}</CardTitle>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 rounded-full"
                  onClick={() => {
                    setIsMetadataCollapsed((prev) => {
                      const next = !prev;
                      setItem(metadataCollapsedStorageKey, next.toString());
                      return next;
                    });
                  }}
                  aria-label={
                    isMetadataCollapsed ? t("detail.expandMetadata") : t("detail.collapseMetadata")
                  }
                >
                  {isMetadataCollapsed ? (
                    <ChevronDown className="h-4 w-4" />
                  ) : (
                    <ChevronUp className="h-4 w-4" />
                  )}
                </Button>
              </div>
            </CardHeader>
            <CollapsibleContent className="data-[state=closed]:hidden">
              <CardContent className="space-y-6">
                {/* Featured image — hidden for an uploaded image (the image IS the featured image) */}
                {!document.file_content_type?.startsWith("image/") && (
                  <div className="space-y-2">
                    <Label>{t("detail.featuredImage")}</Label>
                    <div className="flex flex-col gap-4 md:flex-row md:items-center">
                      <div className="relative aspect-square w-full overflow-hidden rounded-xl border bg-muted md:w-50">
                        {featuredImageUrl ? (
                          <img
                            src={resolveUploadUrl(featuredImageUrl) ?? undefined}
                            alt=""
                            referrerPolicy="no-referrer"
                            className="h-full w-full object-cover"
                          />
                        ) : (
                          <div className="flex h-full items-center justify-center text-muted-foreground">
                            <ScrollText className="h-10 w-10" />
                          </div>
                        )}
                      </div>
                      <div className="space-y-2">
                        {canEditDocument ? (
                          <div className="flex flex-wrap gap-2">
                            <ImagePicker
                              variant="button"
                              accept="image/*"
                              disabled={isUploadingFeaturedImage}
                              onSelect={handleFeaturedImageChange}
                            >
                              {isUploadingFeaturedImage ? (
                                <>
                                  <Loader2 className="h-4 w-4 animate-spin" />
                                  {t("detail.uploading")}
                                </>
                              ) : (
                                <>
                                  <ImagePlus className="h-4 w-4" />
                                  {t("detail.uploadImage")}
                                </>
                              )}
                            </ImagePicker>
                            {featuredImageUrl ? (
                              <Button
                                type="button"
                                variant="ghost"
                                onClick={() => {
                                  setFeaturedImageUrl(null);
                                  isAutosaveRef.current = true;
                                  saveNow({ featured_image_url: null });
                                }}
                                disabled={isUploadingFeaturedImage}
                              >
                                <X className="h-4 w-4" />
                                {t("detail.removeImage")}
                              </Button>
                            ) : null}
                          </div>
                        ) : null}
                      </div>
                    </div>
                  </div>
                )}

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

                {/* Properties */}
                <div className="space-y-2">
                  <Label>{t("properties:title")}</Label>
                  <PropertyList
                    entityKind="document"
                    entityId={parsedId}
                    properties={combinedProperties}
                    disabled={!canEditDocument}
                    initiativeId={document.initiative_id}
                    canOpen={{ tool: Tool.document, id: document.id }}
                  />
                  <AddPropertyButton
                    initiativeId={document.initiative_id}
                    currentPropertyIds={combinedPropertyIds}
                    onAdd={handleAddProperty}
                    disabled={!canEditDocument}
                  />
                </div>
              </CardContent>
            </CollapsibleContent>
          </Collapsible>
        </Card>

        {framed ? (
          // Scoped to the body editor alone: a comment composer further down
          // the page is an editor too, and its headings are not this
          // document's contents.
          <DocumentOutlineScope>
            <div
              className={cn(
                "flex flex-col gap-4",
                isFullscreen && "fixed inset-0 z-50 m-0! overflow-hidden bg-background p-4"
              )}
            >
              {/* Collaboration status - shown between featured image and editor.
                  Also shown when offline even in non-collaborative mode, so the
                  user sees an explicit offline indicator at the top of the editor. */}
              {/* Wraps rather than overflows: the row carries up to four
                  controls and none of them shrink. */}
              <div className="flex flex-wrap items-center gap-2">
                {prose && (
                  <Button
                    type="button"
                    variant={outline.isOpen ? "secondary" : "ghost"}
                    size="sm"
                    onClick={outline.toggle}
                    aria-expanded={outline.isOpen}
                    title={t(outline.isOpen ? "outline.hide" : "outline.show")}
                  >
                    <ListTree className="h-4 w-4" />
                    {t("outline.title")}
                  </Button>
                )}
                {(joinsRoom || !isOnline) && (
                  <CollaborationStatusBadge
                    connectionStatus={collaboration.connectionStatus}
                    collaborators={collaboration.collaborators}
                    isCollaborating={collaboration.isCollaborating}
                    isSynced={collaboration.isSynced}
                    isOnline={isOnline}
                  />
                )}
                {Actions ? <Actions document={document} /> : null}
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setIsFullscreen((value) => !value)}
                  aria-label={t(isFullscreen ? "detail.exitFullscreen" : "detail.enterFullscreen")}
                  className={cn(!Actions && "ml-auto")}
                >
                  {isFullscreen ? (
                    <Minimize2 className="h-4 w-4" />
                  ) : (
                    <Maximize2 className="h-4 w-4" />
                  )}
                  {t(isFullscreen ? "detail.exitFullscreen" : "detail.enterFullscreen")}
                </Button>
              </div>
              <div className={cn("flex min-w-0 gap-4", isFullscreen && "min-h-0 flex-1")}>
                {prose && (
                  <DocumentOutlinePanel
                    isOpen={outline.isOpen}
                    onOpenChange={outline.setIsOpen}
                    className={cn(
                      "hidden w-64 shrink-0 lg:flex",
                      isFullscreen ? "min-h-0" : "max-h-[80vh]"
                    )}
                  />
                )}
                <div className={cn("flex min-w-0 flex-1 flex-col", isFullscreen && "min-h-0")}>
                  {body}
                </div>
              </div>
              {editable ? (
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
                            onClick={() => saveNow()}
                            disabled={!isDirty || saveDocument.isPending}
                          >
                            {saveDocument.isPending ? (
                              <>
                                <Loader2 className="h-4 w-4 animate-spin" />
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
                            <span className="self-center text-muted-foreground text-sm">
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
              ) : null}
            </div>
          </DocumentOutlineScope>
        ) : (
          body
        )}

        {/* Everything this document is connected to, in place of a read-only
            list of projects and a read-only list of backlinks. The projects half
            was editable only from the project's side, which meant the same fact
            had two renderings and one of them could not be changed. */}
        <ToolRelationsPanel
          tool={Tool.document}
          entity={document}
          canEdit={canEditDocument}
          entityTitle={document.name}
        />

        {/* The thread, at the width of the document it is about — the same
            place every other tool puts it. */}
        <ToolCommentsPanel
          tool={Tool.document}
          entity={document}
          canModerate={canEditDocument}
          onCountChange={updateDocumentCommentCount}
        />
      </div>

      {/* Side panel for the AI summary */}
      {showSummaryTab && (
        <DocumentSidePanel
          isOpen={sidePanel.isOpen}
          onOpenChange={sidePanel.setIsOpen}
          summaryContent={
            <DocumentSummary
              documentId={parsedId}
              summary={aiSummary}
              onSummaryChange={setAiSummary}
            />
          }
        />
      )}
    </div>
  );
};
