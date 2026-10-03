/**
 * The document editor without a page, for the server.
 *
 * Built on its own by `scripts/build-editor-server.mjs` and run in an embedded
 * engine (`backend/app/services/editor_worker.py`), so the server reads and
 * writes a document's Yjs state with the same nodes, in the same shape, as the
 * browser does. It binds a headless editor to a Yjs document the way Lexical
 * documents for a server (`@lexical/yjs` with a provider that does nothing).
 *
 * States cross the boundary as hex, and the caller names the Yjs client a
 * state is written as.
 */
import { buildEditorFromExtensions } from "@lexical/extension";
import {
  type Binding,
  createBinding,
  type Provider,
  syncLexicalUpdateToYjs,
  syncYjsChangesToLexical,
} from "@lexical/yjs";
import { $createParagraphNode, $getRoot, type LexicalEditor } from "lexical";
import {
  applyUpdate,
  Doc,
  encodeStateAsUpdate,
  type Transaction,
  type YEvent,
  type Text as YText,
} from "yjs";

import { documentExtension } from "@/components/documents/editor/document-extension";
import { registerLegacyNodes } from "@/components/ui/editor/nodes/legacy-nodes";

/** The id the browser's `CollaborationPlugin` binds under. */
const ROOT_ID = "main";

const toHex = (bytes: Uint8Array) =>
  Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");

const fromHex = (hex: string) => {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < bytes.length; i++) {
    bytes[i] = Number.parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  }
  return bytes;
};

function silentProvider(): Provider {
  const nothing = () => {};
  return {
    awareness: {
      getLocalState: () => null,
      getStates: () => new Map(),
      off: nothing,
      on: nothing,
      setLocalState: nothing,
      setLocalStateField: nothing,
    },
    connect: nothing,
    disconnect: nothing,
    off: nothing,
    on: nothing,
  } as unknown as Provider;
}

function withEditor<T>(clientId: number | null, use: (editor: LexicalEditor, doc: Doc) => T): T {
  const editor = buildEditorFromExtensions(
    documentExtension({ collaborative: true, editable: false })
  );
  const doc = new Doc();
  if (clientId !== null) doc.clientID = clientId;
  const provider = silentProvider();
  const binding: Binding = createBinding(editor, provider, ROOT_ID, doc, new Map([[ROOT_ID, doc]]));
  const stopUpdates = editor.registerUpdateListener(
    ({ dirtyElements, dirtyLeaves, editorState, normalizedNodes, prevEditorState, tags }) => {
      if (!tags.has("skip-collab")) {
        syncLexicalUpdateToYjs(
          binding,
          provider,
          prevEditorState,
          editorState,
          dirtyElements,
          dirtyLeaves,
          normalizedNodes,
          tags
        );
      }
    }
  );
  const observer = (events: Array<YEvent<YText>>, transaction: Transaction) => {
    if (transaction.origin !== binding) {
      syncYjsChangesToLexical(binding, provider, events, false);
    }
  };
  binding.root.getSharedType().observeDeep(observer);
  try {
    return use(editor, doc);
  } finally {
    binding.root.getSharedType().unobserveDeep(observer);
    stopUpdates();
    editor.dispose();
  }
}

/** Rewrite the legacy nodes a document holds as current content, as the
 * browser's editor does when it opens one. */
const modernize = (editor: LexicalEditor) => registerLegacyNodes(editor)();

/**
 * A document's Yjs state, from its editor JSON, or with one empty paragraph
 * when it has none — what the browser's editor starts a new document with.
 */
function bootstrap(json: string | null, clientId: number): string {
  return withEditor(clientId, (editor, doc) => {
    if (json === null) {
      editor.update(() => $getRoot().append($createParagraphNode()), { discrete: true });
    } else {
      editor.setEditorState(editor.parseEditorState(json), { tag: "history-merge" });
      modernize(editor);
    }
    return toHex(encodeStateAsUpdate(doc));
  });
}

/** The editor JSON a Yjs state reads as. Nothing it does is kept. */
function render(state: string): string {
  return withEditor(null, (editor, doc) => {
    applyUpdate(doc, fromHex(state), { isUpdateRemote: true });
    editor.update(() => {}, { discrete: true });
    modernize(editor);
    return JSON.stringify(editor.getEditorState().toJSON());
  });
}

(globalThis as { serverEditor?: unknown }).serverEditor = { bootstrap, render };
