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
import {
  $createParagraphNode,
  $getRoot,
  $isElementNode,
  $isTextNode,
  $parseSerializedNode,
  type ElementNode,
  type LexicalEditor,
  type LexicalNode,
  type SerializedLexicalNode,
} from "lexical";
import {
  applyUpdate,
  Doc,
  encodeStateAsUpdate,
  encodeStateVector,
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

function load(editor: LexicalEditor, doc: Doc, state: string) {
  applyUpdate(doc, fromHex(state), { isUpdateRemote: true });
  editor.update(() => {}, { discrete: true });
}

/** The editor JSON a Yjs state reads as. Nothing it does is kept. */
function render(state: string): string {
  return withEditor(null, (editor, doc) => {
    load(editor, doc, state);
    modernize(editor);
    return JSON.stringify(editor.getEditorState().toJSON());
  });
}

type Serialized = SerializedLexicalNode & { children?: Serialized[]; text?: string };

/** A node as a comparison sees it: its JSON without default values, which a
 *  parsed node leaves out and a node read from Yjs spells out, and without
 *  `direction`, which the browser works out as it draws the text and the
 *  server, drawing nothing, never does. */
const keyOf = (node: Serialized, without?: "children" | "text") =>
  JSON.stringify(node, (key, value) =>
    key !== "" &&
    (key === without ||
      key === "direction" ||
      value === 0 ||
      value === "" ||
      value === null ||
      value === false ||
      value === "normal")
      ? undefined
      : value
  );

/** Make `nodes`, whose JSON is `was`, read as `next`, keeping the nodes at
 *  either end that are unchanged and reconciling the run between them. */
function $reconcileChildren(parent: ElementNode, was: Serialized[], next: Serialized[]) {
  const nodes = parent.getChildren();
  const wasKeys = was.map((node) => keyOf(node));
  const nextKeys = next.map((node) => keyOf(node));
  let head = 0;
  while (head < was.length && head < next.length && wasKeys[head] === nextKeys[head]) head++;
  let tail = 0;
  while (
    tail < was.length - head &&
    tail < next.length - head &&
    wasKeys[was.length - 1 - tail] === nextKeys[next.length - 1 - tail]
  ) {
    tail++;
  }
  const changed = nodes.slice(head, nodes.length - tail);
  const wasRun = was.slice(head, was.length - tail);
  const nextRun = next.slice(head, next.length - tail);
  if (changed.length === nextRun.length) {
    changed.forEach((node, i) => {
      $reconcile(node, wasRun[i], nextRun[i]);
    });
    return;
  }
  for (const node of changed) node.remove();
  const inserted = nextRun.map((node) => $parseSerializedNode(node));
  const before = head > 0 ? nodes[head - 1] : null;
  if (before) {
    let previous: LexicalNode = before;
    for (const node of inserted) {
      previous.insertAfter(node);
      previous = node;
    }
  } else {
    const first = parent.getFirstChild();
    if (first) for (const node of inserted) first.insertBefore(node);
    else parent.append(...inserted);
  }
}

/** Make `node`, whose JSON is `was`, read as `next`: an element of the same
 *  kind keeps itself and reconciles its children, a text of the same kind has
 *  only its changed characters spliced, and anything else is replaced. */
function $reconcile(node: LexicalNode, was: Serialized, next: Serialized) {
  if (keyOf(was) === keyOf(next)) return;
  if (
    $isElementNode(node) &&
    Array.isArray(was.children) &&
    Array.isArray(next.children) &&
    keyOf(was, "children") === keyOf(next, "children")
  ) {
    $reconcileChildren(node, was.children, next.children);
    return;
  }
  if ($isTextNode(node) && keyOf(was, "text") === keyOf(next, "text")) {
    const from = node.getTextContent();
    const to = next.text ?? "";
    let start = 0;
    while (start < from.length && start < to.length && from[start] === to[start]) start++;
    let end = 0;
    while (
      end < from.length - start &&
      end < to.length - start &&
      from[from.length - 1 - end] === to[to.length - 1 - end]
    ) {
      end++;
    }
    node.spliceText(start, from.length - start - end, to.slice(start, to.length - end));
    return;
  }
  node.replace($parseSerializedNode(next));
}

/**
 * The Yjs update that makes a state read as `json`, written as the named
 * client. Only what changed is rewritten — down to the characters of a text
 * — so it merges with edits made to the same state elsewhere as a person's
 * own typing would.
 */
function apply(state: string, json: string, clientId: number): string {
  return withEditor(clientId, (editor, doc) => {
    load(editor, doc, state);
    const before = encodeStateVector(doc);
    const was = editor.getEditorState().toJSON().root as Serialized;
    const next = (JSON.parse(json) as { root: Serialized }).root;
    editor.update(() => $reconcileChildren($getRoot(), was.children ?? [], next.children ?? []), {
      discrete: true,
    });
    modernize(editor);
    return toHex(encodeStateAsUpdate(doc, before));
  });
}

(globalThis as { serverEditor?: unknown }).serverEditor = { apply, bootstrap, render };
