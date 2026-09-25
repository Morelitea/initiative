import { useNavigate } from "@tanstack/react-router";
import type { SerializedEditorState } from "lexical";
import { ExternalLink, Loader2 } from "lucide-react";
import { type ComponentType, lazy, useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { importSpreadsheetFileApiV1CGuildIdDocumentsDocumentIdSpreadsheetImportPost } from "@/api/generated/documents/documents";
import type { DocumentRead, DocumentType } from "@/api/generated/initiativeAPI.schemas";
import { SearchEntityType, Tool } from "@/api/generated/initiativeAPI.schemas";
import type { SmartLinkContent } from "@/components/documents/SmartLinkDocumentViewer";
import type { SpreadsheetContent } from "@/components/documents/SpreadsheetDocumentEditor";
import type { WhiteboardScene } from "@/components/documents/WhiteboardDocumentEditor";
import {
  loadWhiteboardScene,
  stampWhiteboardSceneCache,
  type WhiteboardSceneLoad,
} from "@/components/documents/whiteboardSceneCache";
import { CreateReferencedThingDialog } from "@/components/references/CreateReferencedThingDialog";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import type { UseCollaborationResult } from "@/hooks/useCollaboration";
import { useGuilds } from "@/hooks/useGuilds";
import { normalizeEditorState } from "@/lib/editorState";
import { useGuildPath } from "@/lib/guildUrl";
import { supportsEntityMentions } from "@/lib/mentions";
import { hasOwnerAccess } from "@/lib/permissions";
import { referenceRef } from "@/lib/smartChips";
import type { SpreadsheetSheetContent } from "@/lib/spreadsheet/content";
import { toolDetailRoute } from "@/lib/tools";
import { getUserDisplayName } from "@/lib/userDisplay";
import { cn } from "@/lib/utils";

const Editor = lazy(() =>
  import("@/components/documents/editor/editor").then((m) => ({ default: m.Editor }))
);
const FileDocumentViewer = lazy(() =>
  import("@/components/documents/FileDocumentViewer").then((m) => ({
    default: m.FileDocumentViewer,
  }))
);
const SpreadsheetDocumentEditor = lazy(() =>
  import("@/components/documents/SpreadsheetDocumentEditor").then((m) => ({
    default: m.SpreadsheetDocumentEditor,
  }))
);
const WhiteboardDocumentEditor = lazy(() =>
  import("@/components/documents/WhiteboardDocumentEditor").then((m) => ({
    default: m.WhiteboardDocumentEditor,
  }))
);
const SmartLinkDocumentViewer = lazy(() =>
  import("@/components/documents/SmartLinkDocumentViewer").then((m) => ({
    default: m.SmartLinkDocumentViewer,
  }))
);

/** What the document page hands every body. The page keys it by document. */
export interface DocumentBodyProps {
  document: DocumentRead;
  /** The saved body, in the shape this type reports edits in. */
  saved: unknown;
  canEdit: boolean;
  collaboration: UseCollaborationResult;
  /** Live collaboration is on and its room is ready. */
  live: boolean;
  /** The fetch behind `document` has come back since the page opened. */
  settled: boolean;
  title: string;
  className?: string;
  /** Reports what the body now holds — the edit the page saves. */
  onChange: (content: unknown) => void;
}

/** One document type's body, and what the page around it does for that type.
 *  A capability left out is one the type does not have. */
export interface DocumentBody {
  Body: ComponentType<DocumentBodyProps>;
  /** The saved body, as the dirty check and a save carrying no edit read it. */
  saved: (document: DocumentRead) => unknown;
  /** Controls of its own in the editor's toolbar row, before fullscreen. */
  Actions?: ComponentType<{ document: DocumentRead }>;
  /** Sits in the editor frame: toolbar and fullscreen. */
  framed?: boolean;
  /** Edited on this page, so the frame carries the save bar. */
  editable?: boolean;
  /**
   * Joins the document's live room, sending it this tab's rendering this
   * often so the content column stays current for readers outside it. Prose
   * waits longer — people type many characters a second — while a drawing
   * action or a cell edit fits in the window, and a longer one would only
   * leave the column stale.
   */
  roomSyncMs?: number;
  /** Prose: headings to navigate and an AI summary. */
  prose?: boolean;
}

/** The signed-in user as presence shows them. Memoized so awareness effects
 *  key on the identity rather than an object made every render. */
const usePresenceUser = () => {
  const { user } = useAuth();
  return useMemo(
    () => (user ? { id: user.id, name: getUserDisplayName(user, "Anonymous") } : null),
    [user]
  );
};

/**
 * The room's Yjs doc and awareness, for a body that binds its own editor to
 * them. Asking the factory reuses the provider or opens it, the way Lexical's
 * CollaborationPlugin does for prose; useCollaboration owns its lifecycle, so
 * there is nothing to clean up here.
 */
const useRoomProvider = ({ providerFactory }: UseCollaborationResult, live: boolean) => {
  type Provider = ReturnType<NonNullable<typeof providerFactory>>;
  const [provider, setProvider] = useState<Provider | null>(null);
  useEffect(() => {
    setProvider(live && providerFactory ? providerFactory("main", new Map()) : null);
  }, [live, providerFactory]);
  return live ? provider : null;
};

const NativeBody = ({
  document,
  saved,
  canEdit,
  collaboration,
  live,
  className,
  onChange,
}: DocumentBodyProps) => {
  const navigate = useNavigate();
  const gp = useGuildPath();
  // `[[ ]]` found nothing and offered to make it. The dialog owns which kind
  // and whether this writer may; the reference it answers with goes straight
  // into the sentence, so making something never costs the writer their place.
  const [creating, setCreating] = useState<{
    name: string;
    onCreated: (entityType: SearchEntityType, entityId: number, name: string) => void;
  } | null>(null);

  const handleWikilinkNavigate = useCallback(
    (targetDocumentId: number) => {
      void navigate({
        to: gp(toolDetailRoute(Tool.document, document.initiative_id, targetDocumentId)),
      });
    },
    [navigate, gp, document.initiative_id]
  );
  const handleCreateReferencedThing = useCallback(
    (name: string, onCreated: NonNullable<typeof creating>["onCreated"]) =>
      setCreating({ name, onCreated }),
    []
  );

  return (
    <>
      <Editor
        editorSerializedState={saved as SerializedEditorState}
        onSerializedChange={onChange}
        readOnly={!canEdit}
        showToolbar={canEdit}
        className={cn("max-h-[80vh] bg-card", className)}
        collaborative={live}
        providerFactory={collaboration.providerFactory}
        // Always track changes so the page's copy stays updated for periodic saves
        trackChanges={true}
        isSynced={collaboration.isSynced}
        initiativeId={document.initiative_id}
        subject={referenceRef(SearchEntityType.document, document.id)}
        supportsEntityMentions={supportsEntityMentions(document.document_type)}
        onWikilinkNavigate={handleWikilinkNavigate}
        onCreateReferencedThing={handleCreateReferencedThing}
      />
      {creating && (
        <CreateReferencedThingDialog
          name={creating.name}
          initiativeId={document.initiative_id}
          onCreated={(made) => {
            creating.onCreated(made.entityType, made.entityId, made.name);
            setCreating(null);
          }}
          onClose={() => setCreating(null)}
        />
      )}
    </>
  );
};

const WhiteboardBody = ({
  document,
  canEdit,
  collaboration,
  live,
  settled,
  className,
  onChange,
}: DocumentBodyProps) => {
  const room = useRoomProvider(collaboration, live);
  const currentUser = usePresenceUser();
  // The editor reads its scene once, at mount, so it waits for this. The
  // write-ahead cache wins only while it is strictly newer than
  // document.updated_at, and a cached snapshot's timestamp makes any local
  // cache look newer than it is — so the scene is loaded once the fetch has
  // settled. (An errored fetch settles too, so offline still falls back to the
  // cached document.)
  const [load, setLoad] = useState<WhiteboardSceneLoad | null>(null);
  useEffect(() => {
    if (load || !settled) return;
    const next = loadWhiteboardScene(
      document.id,
      document.updated_at,
      document.content as Partial<WhiteboardScene> | null
    );
    setLoad(next);
    // A cached scene is edits the server has not seen: unsaved work.
    if (next.fromCache) onChange(next.scene);
  }, [load, settled, document, onChange]);

  // Only genuine local edits stamp the write-ahead cache: remote-applied
  // updates flow through here too (the periodic REST sync needs them), and
  // stamping on those would leave every watching session holding a
  // fresh-looking cache that a later revisit would prefer over the live room.
  const handleChange = useCallback(
    (scene: WhiteboardScene, opts?: { isLocal: boolean }) => {
      onChange(scene);
      if (opts?.isLocal === false) return;
      stampWhiteboardSceneCache(document.id, scene);
    },
    [onChange, document.id]
  );

  if (!load) {
    return (
      <div className="flex h-96 items-center justify-center rounded-xl border">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }
  return (
    <WhiteboardDocumentEditor
      initialScene={load.scene}
      initialSceneFromCache={load.fromCache}
      onSerializedChange={handleChange}
      readOnly={!canEdit}
      yDoc={room?.doc ?? null}
      isSynced={collaboration.isSynced}
      // The server roster includes ourselves — only *other* users make the
      // room's Yjs state authoritative over a local write-ahead cache.
      hasOtherCollaborators={collaboration.collaborators.some((c) => c.user_id !== currentUser?.id)}
      collaboratorsReady={collaboration.collaboratorsReady}
      awareness={room?.awareness ?? null}
      currentUser={currentUser}
      className={className}
    />
  );
};

const SpreadsheetBody = ({
  document,
  saved,
  canEdit,
  collaboration,
  live,
  title,
  className,
  onChange,
}: DocumentBodyProps) => {
  const room = useRoomProvider(collaboration, live);
  const currentUser = usePresenceUser();
  const { activeGuildId } = useGuilds();
  // Reading a file is the host's job — it knows which document and guild the
  // editor is showing. What comes back is sheets; the editor adds them to its
  // live workbook itself, in one transaction.
  const importSheets = useCallback(
    async (file: File) => {
      if (!activeGuildId) return [];
      const result =
        await importSpreadsheetFileApiV1CGuildIdDocumentsDocumentIdSpreadsheetImportPost(
          activeGuildId,
          document.id,
          { file }
        );
      return result.sheets as unknown as SpreadsheetSheetContent[];
    },
    [activeGuildId, document.id]
  );

  return (
    <SpreadsheetDocumentEditor
      initialContent={saved as SpreadsheetContent}
      onContentChange={onChange}
      documentTitle={title || document.name}
      readOnly={!canEdit}
      yDoc={room?.doc ?? null}
      isSynced={collaboration.isSynced}
      awareness={room?.awareness ?? null}
      currentUser={currentUser}
      onImportFile={canEdit ? importSheets : undefined}
      className={cn("max-h-[70vh]", className)}
    />
  );
};

const SmartLinkBody = ({ document, className }: DocumentBodyProps) => (
  <SmartLinkDocumentViewer
    content={document.content as unknown as SmartLinkContent | null}
    className={className}
  />
);

const SmartLinkActions = ({ document }: { document: DocumentRead }) => {
  const { t } = useTranslation("documents");
  const url = (document.content as { url?: unknown } | null)?.url;
  if (typeof url !== "string") return null;
  return (
    <Button asChild type="button" variant="ghost" size="sm" className="ml-auto">
      <a href={url} target="_blank" rel="noopener noreferrer">
        <ExternalLink className="h-4 w-4" />
        {t("smartLink.openInNewTab")}
      </a>
    </Button>
  );
};

const FileBody = ({ document, canEdit }: DocumentBodyProps) =>
  document.file_url ? (
    <FileDocumentViewer
      documentId={document.id}
      guildId={document.guild_id}
      fileUrl={document.file_url}
      contentType={document.file_content_type}
      originalFilename={document.original_filename}
      fileSize={document.file_size}
      canEdit={canEdit}
      isOwner={hasOwnerAccess(document.my_permission_level)}
    />
  ) : null;

// Spreadsheet and whiteboard content is not a Lexical tree: passed through
// the normalizer it would come back empty, read as an edit against the real
// content, and fire an autosave on every open.
const rawContent = (document: DocumentRead): unknown => document.content ?? {};
const lexicalContent = (document: DocumentRead): unknown =>
  normalizeEditorState(document.content as unknown as SerializedEditorState | null | undefined);

/** Every document type's body. A new type is one entry here. */
export const DOCUMENT_BODIES: Record<DocumentType, DocumentBody> = {
  native: {
    Body: NativeBody,
    saved: lexicalContent,
    framed: true,
    editable: true,
    roomSyncMs: 10_000,
    prose: true,
  },
  whiteboard: {
    Body: WhiteboardBody,
    saved: rawContent,
    framed: true,
    editable: true,
    roomSyncMs: 2000,
  },
  spreadsheet: {
    Body: SpreadsheetBody,
    saved: rawContent,
    framed: true,
    editable: true,
    roomSyncMs: 2000,
  },
  // Nothing on this page edits the link: a save echoes the content back so a
  // rename or a featured-image change does not rewrite the URL.
  smart_link: {
    Body: SmartLinkBody,
    saved: (document) => document.content,
    Actions: SmartLinkActions,
    framed: true,
  },
  file: { Body: FileBody, saved: lexicalContent },
};
