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
  it("keeps the person and not their name, however it was made", () => {
    // The picker hands over the name it showed; the node drops it.
    const serialized = inEditor(() => $createMentionNode("Ada Lovelace", 4).exportJSON());

    expect(serialized).toMatchObject({
      type: "mention",
      mentionName: "",
      mentionUserId: 4,
      text: "",
    });
  });

  it("keeps the name of somebody with no account, which is all it has", () => {
    const serialized = inEditor(() => $createMentionNode("Ada Lovelace").exportJSON());

    expect(serialized).toMatchObject({ mentionName: "Ada Lovelace", mentionUserId: null });
  });

  it("reads a mention written with a name, and lets the name go", () => {
    // What a `TextNode` mention serialized, and what every mention did before
    // names were left out: the same three fields, plus text formatting this
    // node has no use for.
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
    expect(node.getTextContent()).toBe("");
  });
});
