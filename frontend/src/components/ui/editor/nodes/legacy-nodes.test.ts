import { createEditor } from "lexical";
import { describe, expect, it } from "vitest";

import { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import {
  $isEntityMentionNode,
  EntityMentionNode,
} from "@/components/ui/editor/nodes/entity-mention-node";
import { LEGACY_NODES, registerLegacyNodes } from "@/components/ui/editor/nodes/legacy-nodes";

const text = (extra: Record<string, unknown>) => ({
  detail: 0,
  format: 0,
  mode: "normal",
  style: "",
  version: 1,
  ...extra,
});

/** What one node of a stored document is, once today's editor has opened it. */
type Opened = { type: string; text: string; entityType?: string; entityId?: number };

function opened(children: Record<string, unknown>[]): Opened[] {
  const editor = createEditor({
    nodes: [EntityMentionNode, ...LEGACY_NODES],
    onError: (error) => {
      throw error;
    },
  });
  editor.setEditorState(
    editor.parseEditorState(
      JSON.stringify({
        root: {
          children: [
            { children, direction: null, format: "", indent: 0, type: "paragraph", version: 1 },
          ],
          direction: null,
          format: "",
          indent: 0,
          type: "root",
          version: 1,
        },
      })
    )
  );
  registerLegacyNodes(editor);

  const found: Opened[] = [];
  editor.getEditorState().read(() => {
    for (const node of editor.getEditorState()._nodeMap.values()) {
      if (node.getType() === "root" || node.getType() === "paragraph") continue;
      found.push({
        type: node.getType(),
        text: node.getTextContent(),
        ...($isEntityMentionNode(node)
          ? { entityType: node.getEntityType(), entityId: node.getEntityId() }
          : {}),
      });
    }
  });
  return found;
}

describe("a document written before references were one thing", () => {
  it("reads a stored hashtag as the word it looks like", () => {
    // `#` is the reference trigger now, and the picker reads what is being
    // typed out of ordinary text — a hashtag of its own is not that.
    expect(opened([text({ type: "hashtag", text: "#launch" })])).toEqual([
      { type: "text", text: "#launch" },
    ]);
  });

  it("reads a resolved wikilink as the reference it always was", () => {
    expect(
      opened([
        text({ type: "wikilink", text: "Roadmap", documentId: 12, documentTitle: "Roadmap" }),
      ])
    ).toEqual([
      {
        type: "entity-mention",
        text: "Roadmap",
        entityType: SearchEntityType.document,
        entityId: 12,
      },
    ]);
  });

  it("keeps the words of a wikilink that never resolved", () => {
    // It names nothing, so there is nothing to carry over but what it says.
    expect(
      opened([
        text({ type: "wikilink", text: "Nowhere", documentId: null, documentTitle: "Nowhere" }),
      ])
    ).toEqual([{ type: "text", text: "Nowhere" }]);
  });
});
