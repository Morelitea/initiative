/**
 * Whiteboard document editor backed by Excalidraw.
 *
 * - Scene data is stored in `document.content` as {elements, appState, files}.
 * - When `yDoc` is provided, the scene is also mirrored to a single-key Yjs
 *   map (`excalidraw.scene`) so multiple clients stay in sync via the existing
 *   collaboration WebSocket pipeline. Conflict resolution is last-write-wins at
 *   the scene key — an explicit v1 trade-off.
 * - When `yDoc` is null, edits flow through the parent's REST autosave path.
 */
import { useCallback, useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { Excalidraw, CaptureUpdateAction, serializeAsJSON } from "@excalidraw/excalidraw";
import "@excalidraw/excalidraw/index.css";
import type {
  AppState,
  BinaryFiles,
  ExcalidrawImperativeAPI,
  ExcalidrawInitialDataState,
} from "@excalidraw/excalidraw/types";
import type {
  ExcalidrawElement,
  OrderedExcalidrawElement,
} from "@excalidraw/excalidraw/element/types";
import * as Y from "yjs";

import { cn } from "@/lib/utils";
import { useTheme } from "@/hooks/useTheme";

export interface WhiteboardScene {
  elements: readonly ExcalidrawElement[];
  appState: Partial<AppState>;
  files: BinaryFiles;
}

export interface WhiteboardDocumentEditorProps {
  /** Initial scene loaded from document.content (may be empty). */
  initialScene: WhiteboardScene;
  /** True if initialScene came from the localStorage write-ahead cache,
   *  meaning the user has unsaved local edits. When true, the bootstrap
   *  must NOT overwrite the canvas with Yjs sync state, which would clobber
   *  the unsaved work. When false, the bootstrap is free to apply Yjs
   *  state to catch up to a live room where another user has been
   *  editing. */
  initialSceneFromCache?: boolean;
  /** Called on every change with the pruned, persistable scene. */
  onSerializedChange: (scene: WhiteboardScene) => void;
  readOnly?: boolean;
  className?: string;
  /** Live collaboration: an already-attached Yjs doc. Null => REST-only mode. */
  yDoc?: Y.Doc | null;
  /** Whether the Yjs provider has fully synced from the server. */
  isSynced?: boolean;
}

/**
 * Build a stable initial data object that only changes when the scene's
 * identity changes. Excalidraw treats `initialData` as a load-once hint — we
 * never pass a new reference after the first render.
 */
function makeInitialData(scene: WhiteboardScene): ExcalidrawInitialDataState {
  const hasContent = Array.isArray(scene.elements) && scene.elements.length > 0;
  return {
    elements: hasContent ? (scene.elements as OrderedExcalidrawElement[]) : [],
    appState: scene.appState ?? {},
    files: scene.files ?? {},
    scrollToContent: hasContent,
  };
}

export function WhiteboardDocumentEditor({
  initialScene,
  initialSceneFromCache = false,
  onSerializedChange,
  readOnly = false,
  className,
  yDoc = null,
  isSynced = true,
}: WhiteboardDocumentEditorProps) {
  const { t } = useTranslation("documents");
  const { resolvedTheme } = useTheme();

  const excalidrawAPIRef = useRef<ExcalidrawImperativeAPI | null>(null);
  const yMapRef = useRef<Y.Map<string> | null>(null);
  const applyingRemoteRef = useRef(false);
  // Tracks the most recently seen serialized scene (either a local write
  // or a freshly-applied remote update). Used by handleExcalidrawChange to
  // skip no-op propagation and by the Yjs observer to suppress the echo
  // cycle when a remote update triggers a local onChange.
  const prevSerializedRef = useRef<string>("");
  // Separate dedupe for the parent onSerializedChange callback. We need to
  // notify the parent for *both* local edits and remote-applied updates
  // (otherwise the periodic REST content-sync writes a stale snapshot —
  // see the User 2 refresh bug). But we can't notify on every echo
  // onChange or we cause an infinite render loop. This ref tracks the
  // last scene we passed up so we can skip duplicates.
  const lastNotifiedSerializedRef = useRef<string>("");
  // Tracks which Y.Doc we've already bootstrapped so we don't seed twice
  // (e.g. if isSynced flips false → true → false → true on reconnect).
  const seededForDocRef = useRef<Y.Doc | null>(null);
  // Gated true AFTER the post-sync bootstrap seeds the Y.Map. The observer
  // skips all events until this is true, so the stale initial Yjs sync
  // (from persist_room, which can be one edit behind because the last
  // WebSocket message is lost on page unload) never overwrites the correct
  // REST-fetched initialScene that Excalidraw is already displaying.
  const bootstrapDoneRef = useRef(false);

  const collaborative = Boolean(yDoc);

  // Only compute initialData once per mount (the Excalidraw key in the parent
  // forces remount on document switch, so this is safe).
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const initialData = useMemo(() => makeInitialData(initialScene), []);

  // ── Yjs binding ───────────────────────────────────────────────────────
  //
  // NOTE ON BOOTSTRAP: we intentionally do NOT seed the Y.Map here. When the
  // user reconnects to an existing document, the provider's initial sync
  // brings in any server-side updates that happened while they were away.
  // Seeding with the stale `initialScene` before sync completes would race
  // with that incoming state — via last-write-wins on the `scene` key, the
  // seed could clobber legitimate updates. The bootstrap happens later in
  // a separate effect gated on `isSynced`.
  useEffect(() => {
    if (!yDoc) return;
    const yMap = yDoc.getMap<string>("excalidraw");
    yMapRef.current = yMap;
    // Reset bootstrap guards whenever the Y.Doc changes (e.g. navigating
    // between whiteboards).
    seededForDocRef.current = null;
    bootstrapDoneRef.current = false;

    const handleRemoteChange = (event: Y.YMapEvent<string>) => {
      // Skip our own writes — Excalidraw already has them
      if (event.transaction.local) return;
      // Skip events from the initial Yjs sync. The server's yjs_state can
      // be one edit behind document.content (the last WebSocket message is
      // lost on page unload, while the keepalive PATCH survives). Applying
      // the stale sync state would overwrite the correct REST-fetched scene
      // that Excalidraw is already displaying. Only LIVE updates from other
      // users (which arrive after the bootstrap seeds the Y.Map) should be
      // applied.
      if (!bootstrapDoneRef.current) return;
      const raw = yMap.get("scene");
      if (!raw || !excalidrawAPIRef.current) return;
      try {
        const parsed = JSON.parse(raw) as {
          elements: readonly OrderedExcalidrawElement[];
          appState?: Partial<AppState>;
          files?: BinaryFiles;
        };
        // Critical: seed prevSerializedRef BEFORE calling updateScene.
        // Excalidraw's updateScene schedules onChange asynchronously; when
        // it fires, handleExcalidrawChange compares the serialized scene
        // to prevSerializedRef and bails out if they match — which breaks
        // the echo cycle that would otherwise interrupt the drawing user's
        // in-progress drag (e.g. a pencil stroke).
        prevSerializedRef.current = raw;
        applyingRemoteRef.current = true;

        // Add files FIRST, then update the scene. If we reversed this order,
        // Excalidraw would see image elements referencing fileIds that aren't
        // in the files map yet and lock in placeholder rendering — later
        // addFiles calls don't re-trigger those elements to repaint.
        if (parsed.files) {
          const fileArr = Object.values(parsed.files);
          if (fileArr.length > 0) {
            excalidrawAPIRef.current.addFiles(fileArr);
          }
        }

        excalidrawAPIRef.current.updateScene({
          elements: parsed.elements,
          // Cast is safe: Excalidraw only merges the subset of fields we pass.
          appState: parsed.appState as Partial<AppState> as AppState,
          captureUpdate: CaptureUpdateAction.NEVER,
        });
      } catch (err) {
        console.error("Failed to apply remote whiteboard update:", err);
        applyingRemoteRef.current = false;
        return;
      }
      // Clear the flag on a microtask so it stays set through Excalidraw's
      // async onChange callback — a synchronous reset in a finally block
      // would clear it before the echo callback runs, making the guard in
      // handleExcalidrawChange dead code. prevSerializedRef is the primary
      // dedupe; this flag is defense-in-depth against future serializer
      // changes that could desync the byte-level comparison.
      queueMicrotask(() => {
        applyingRemoteRef.current = false;
      });
    };

    yMap.observe(handleRemoteChange);
    return () => {
      yMap.unobserve(handleRemoteChange);
      yMapRef.current = null;
    };
  }, [yDoc]);

  // ── Post-sync bootstrap ──────────────────────────────────────────────
  // After the initial Yjs sync completes, decide whether to apply the
  // Y.Map state to Excalidraw. The decision hinges on whether the
  // initialScene we're already displaying came from unsaved local edits
  // (localStorage cache) or from the server (REST content column).
  //
  // • initialSceneFromCache === true:
  //     The user has unsaved local edits. Applying the Yjs state would
  //     clobber them — the Yjs state is likely behind by one edit because
  //     WebSockets don't support keepalive on page unload, so the last
  //     edit never reached the server before the previous disconnect.
  //     Skip the apply.
  //
  // • initialSceneFromCache === false:
  //     No unsaved local work. The Yjs state in the room is authoritative
  //     for live collaboration — if another user is connected and has
  //     been editing, the Y.Map holds their current scene. Apply it so
  //     the joining user catches up immediately instead of waiting for
  //     the other user's next edit.
  //
  // Either way, set bootstrapDoneRef so the observer starts processing
  // subsequent live updates from other users.
  useEffect(() => {
    if (!yDoc || !isSynced) return;
    if (seededForDocRef.current === yDoc) return;
    seededForDocRef.current = yDoc;

    if (!initialSceneFromCache && excalidrawAPIRef.current) {
      const yMap = yDoc.getMap<string>("excalidraw");
      const raw = yMap.get("scene");
      if (raw) {
        try {
          const parsed = JSON.parse(raw) as {
            elements: readonly OrderedExcalidrawElement[];
            appState?: Partial<AppState>;
            files?: BinaryFiles;
          };
          prevSerializedRef.current = raw;
          applyingRemoteRef.current = true;
          if (parsed.files) {
            const fileArr = Object.values(parsed.files);
            if (fileArr.length > 0) {
              excalidrawAPIRef.current.addFiles(fileArr);
            }
          }
          excalidrawAPIRef.current.updateScene({
            elements: parsed.elements,
            appState: parsed.appState as Partial<AppState> as AppState,
            captureUpdate: CaptureUpdateAction.NEVER,
          });
          queueMicrotask(() => {
            applyingRemoteRef.current = false;
          });
        } catch (err) {
          console.error("Failed to apply post-sync whiteboard state:", err);
          applyingRemoteRef.current = false;
        }
      }
    }

    bootstrapDoneRef.current = true;
  }, [yDoc, isSynced, initialSceneFromCache]);

  // ── Local change handler ─────────────────────────────────────────────
  // Excalidraw fires onChange on every re-render (unlike Lexical which
  // debounces internally). We must skip Yjs writes when the serialized
  // scene hasn't actually changed, otherwise we cause an infinite loop:
  // onChange → setWhiteboardScene → re-render → onChange → …
  //
  // CRUCIAL: we must still call `onSerializedChange` for remote-triggered
  // onChange events (where applyingRemoteRef is set or the dedupe matches).
  // Without that, the parent's whiteboardScene state never updates with
  // remote changes, causing the periodic 10s REST content-sync to PATCH a
  // stale local snapshot — which eventually rolls user 1's view backward
  // and corrupts what gets persisted to document.content for refreshes.
  const handleExcalidrawChange = useCallback(
    (elements: readonly OrderedExcalidrawElement[], appState: AppState, files: BinaryFiles) => {
      // Use Excalidraw's "database" serializer to strip ephemeral appState
      // (selection, collaborators, cursor, zoom-to-fit, etc.). NOTE: this
      // mode deliberately strips the files map — it sets `files: undefined`
      // in the output — so we merge the binaries back in manually below.
      // Otherwise images would round-trip as empty frames.
      const serialized = serializeAsJSON(elements, appState, files, "database");
      const parsed = JSON.parse(serialized) as WhiteboardScene;

      // Only keep file entries that are still referenced by an element so
      // deleted images don't bloat storage forever.
      const referencedFileIds = new Set<string>();
      for (const el of elements) {
        const maybeFileId = (el as { fileId?: string | null }).fileId;
        if (maybeFileId) referencedFileIds.add(maybeFileId);
      }
      const filteredFiles: BinaryFiles = {};
      for (const [id, file] of Object.entries(files)) {
        if (referencedFileIds.has(id)) filteredFiles[id] = file;
      }
      parsed.files = filteredFiles;

      // Re-serialize with files present for the dedupe comparisons and
      // downstream writes.
      const serializedWithFiles = JSON.stringify(parsed);

      // Notify the parent only when the serialized scene actually changed
      // since the last notification. This dedupe is independent of the Yjs
      // dedupe below: we want the parent to see remote-applied updates
      // (so REST content-sync isn't stale), but we must not call the
      // parent on every echo render or we cause an infinite loop.
      if (serializedWithFiles !== lastNotifiedSerializedRef.current) {
        lastNotifiedSerializedRef.current = serializedWithFiles;
        onSerializedChange(parsed);
      }

      // Skip the Yjs write if either (a) we're currently applying a remote
      // update, or (b) the serialized scene matches what we last saw. Both
      // conditions indicate this onChange is an echo of state we already
      // know about, and writing it back to Yjs would interrupt the original
      // sender's in-progress drag.
      if (applyingRemoteRef.current) return;
      if (serializedWithFiles === prevSerializedRef.current) return;
      prevSerializedRef.current = serializedWithFiles;

      // Mirror to Yjs when collaborative
      if (yMapRef.current) {
        yMapRef.current.set("scene", serializedWithFiles);
      }
    },
    [onSerializedChange]
  );

  return (
    <div
      className={cn(
        "bg-background relative h-[80vh] w-full overflow-hidden rounded-lg border shadow",
        className
      )}
    >
      {collaborative && !isSynced && (
        <div className="bg-background/80 absolute inset-0 z-50 flex items-center justify-center">
          <div className="text-muted-foreground flex items-center gap-2">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span>{t("whiteboard.syncing")}</span>
          </div>
        </div>
      )}
      <Excalidraw
        excalidrawAPI={(api) => {
          excalidrawAPIRef.current = api;
        }}
        initialData={initialData}
        onChange={handleExcalidrawChange}
        viewModeEnabled={readOnly}
        isCollaborating={collaborative}
        theme={resolvedTheme}
      />
    </div>
  );
}
