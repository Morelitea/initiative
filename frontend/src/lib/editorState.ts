import type { SerializedEditorState, SerializedLexicalNode } from "lexical";

const createEmptyParagraphNode = (): SerializedLexicalNode =>
  ({
    children: [],
    direction: null,
    format: "",
    indent: 0,
    type: "paragraph",
    version: 1,
  }) as SerializedLexicalNode;

export const createEmptyEditorState = (): SerializedEditorState => ({
  root: {
    children: [createEmptyParagraphNode()],
    direction: null,
    format: "",
    indent: 0,
    type: "root",
    version: 1,
  } as SerializedEditorState["root"],
});

export const EMPTY_EDITOR_STATE: SerializedEditorState = createEmptyEditorState();

export const normalizeEditorState = (
  state?: SerializedEditorState | null
): SerializedEditorState => {
  // Check if state is a valid Lexical editor state with a root property
  const isValidEditorState =
    state &&
    typeof state === "object" &&
    "root" in state &&
    state.root &&
    typeof state.root === "object";

  const base = isValidEditorState ? (state as SerializedEditorState) : createEmptyEditorState();
  const cloned = JSON.parse(JSON.stringify(base)) as SerializedEditorState;
  if (!Array.isArray(cloned.root.children) || cloned.root.children.length === 0) {
    cloned.root.children = [createEmptyParagraphNode()];
  }
  return cloned;
};
