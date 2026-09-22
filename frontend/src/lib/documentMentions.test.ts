import {
  $createParagraphNode,
  $createTextNode,
  $getRoot,
  createEditor,
  type LexicalEditor,
} from "lexical";
import { describe, expect, it } from "vitest";

import { $createMentionNode, MentionNode } from "@/components/ui/editor/nodes/mention-node";
import { collectMentionedUserIds, documentMentionedUserIds } from "@/lib/documentMentions";

function makeEditor(): LexicalEditor {
  return createEditor({
    nodes: [MentionNode],
    onError: (error) => {
      throw error;
    },
  });
}

function inEditor<T>(fn: () => T): T {
  const editor = makeEditor();
  let result!: T;
  editor.update(
    () => {
      result = fn();
    },
    { discrete: true }
  );
  return result;
}

describe("who a document asks about", () => {
  it("names everyone it mentions", () => {
    const ids = inEditor(() =>
      collectMentionedUserIds([$createMentionNode("Ada", 4), $createMentionNode("Grace", 9)])
    );

    expect(ids).toEqual([4, 9]);
  });

  it("asks about a person once, however often they are named", () => {
    const ids = inEditor(() =>
      collectMentionedUserIds([
        $createMentionNode("Ada", 4),
        $createMentionNode("Ada", 4),
        $createMentionNode("Ada", 4),
      ])
    );

    expect(ids).toEqual([4]);
  });

  it("asks the same question however the mentions are ordered", () => {
    const one = inEditor(() =>
      collectMentionedUserIds([$createMentionNode("Grace", 9), $createMentionNode("Ada", 4)])
    );
    const other = inEditor(() =>
      collectMentionedUserIds([$createMentionNode("Ada", 4), $createMentionNode("Grace", 9)])
    );

    expect(one).toEqual(other);
  });

  it("skips a mention that names nobody", () => {
    // Pasted, or written before ids were stored. There is no one to ask about,
    // and asking about `null` would be asking about everyone.
    const ids = inEditor(() => collectMentionedUserIds([$createMentionNode("Ada")]));

    expect(ids).toEqual([]);
  });

  it("finds mentions wherever in the document they sit", () => {
    const editor = makeEditor();
    editor.update(
      () => {
        const first = $createParagraphNode();
        first.append($createTextNode("thanks "), $createMentionNode("Ada", 4));
        const second = $createParagraphNode();
        second.append($createMentionNode("Grace", 9), $createTextNode(" too"));
        $getRoot().append(first, second);
      },
      { discrete: true }
    );

    expect(documentMentionedUserIds(editor.getEditorState())).toEqual([4, 9]);
  });
});

describe("what a mention keeps when it is stored", () => {
  it("round-trips the person and the name it was written with", () => {
    const serialized = inEditor(() => $createMentionNode("Ada Lovelace", 4).exportJSON());

    expect(serialized).toMatchObject({
      type: "mention",
      mentionName: "Ada Lovelace",
      mentionUserId: 4,
      // The export renderers degrade a node carrying `text` to its text, and
      // the search index reads it. A PDF cannot poll for the current name.
      text: "Ada Lovelace",
    });
  });

  it("reads a mention written before it drew its own chip", () => {
    // What a `TextNode` mention serialized: the same three fields, plus text
    // formatting this node has no use for.
    const node = inEditor(() =>
      MentionNode.importJSON({
        type: "mention",
        version: 1,
        mentionName: "Ada Lovelace",
        mentionUserId: 4,
        text: "Ada Lovelace",
        format: 0,
        detail: 0,
        mode: "segmented",
        style: "",
      } as never)
    );

    expect(node.getMentionUserId()).toBe(4);
    expect(node.getTextContent()).toBe("Ada Lovelace");
  });
});
