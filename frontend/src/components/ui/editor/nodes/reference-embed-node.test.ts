import { buildEditorFromExtensions } from "@lexical/extension";
import { $convertFromMarkdownString, $convertToMarkdownString } from "@lexical/markdown";
import { RichTextExtension } from "@lexical/rich-text";
import {
  $createParagraphNode,
  $createTextNode,
  $getRoot,
  defineExtension,
  type LexicalEditor,
} from "lexical";
import { describe, expect, it } from "vitest";

import { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import {
  $createEntityMentionNode,
  $isEntityMentionNode,
  EntityMentionNode,
} from "@/components/ui/editor/nodes/entity-mention-node";
import {
  $isReferenceEmbedNode,
  $showAsEmbed,
  $showAsLink,
  ReferenceEmbedNode,
} from "@/components/ui/editor/nodes/reference-embed-node";
import { EMBED } from "@/components/ui/editor/transformers/markdown-embed-transformer";

function makeEditor(): LexicalEditor {
  return buildEditorFromExtensions(
    defineExtension({
      name: "@test/embeds",
      dependencies: [RichTextExtension],
      nodes: [EntityMentionNode, ReferenceEmbedNode],
      onError: (error) => {
        throw error;
      },
    })
  );
}

const types = (editor: LexicalEditor) =>
  editor.getEditorState().read(() =>
    $getRoot()
      .getChildren()
      .map((child) => child.getType())
  );

describe("an embed in markdown", () => {
  it("is Obsidian's `![[ ]]`, carrying the reference and the name", () => {
    const editor = makeEditor();
    const source = "![[task:12|Roll call]]";
    let exported = "";
    editor.update(() => $convertFromMarkdownString(source, [EMBED]), { discrete: true });
    editor.getEditorState().read(() => {
      const embed = $getRoot().getFirstChild();
      expect($isReferenceEmbedNode(embed)).toBe(true);
      if (!$isReferenceEmbedNode(embed)) return;
      expect([embed.getEntityType(), embed.getEntityId(), embed.getTextContent()]).toEqual([
        SearchEntityType.task,
        12,
        "Roll call",
      ]);
      exported = $convertToMarkdownString([EMBED]);
    });
    expect(exported).toBe(source);
  });

  it("stays text when it names no kind of thing", () => {
    const editor = makeEditor();
    editor.update(() => $convertFromMarkdownString("![[spell:3|Fireball]]", [EMBED]), {
      discrete: true,
    });
    expect(types(editor)).toEqual(["paragraph"]);
  });
});

describe("switching between a link and an embed", () => {
  it("moves a link mid-sentence onto a line of its own, and back", () => {
    const editor = makeEditor();
    editor.update(
      () => {
        const link = $createEntityMentionNode(SearchEntityType.task, 12, "Roll call");
        $getRoot()
          .clear()
          .append($createParagraphNode().append($createTextNode("see "), link));
        $showAsEmbed(link);
      },
      { discrete: true }
    );
    // The sentence keeps its words; the embed follows it, with a line after
    // to keep writing on.
    expect(types(editor)).toEqual(["paragraph", "reference-embed", "paragraph"]);

    editor.update(
      () => {
        const embed = $getRoot().getChildAtIndex(1);
        if ($isReferenceEmbedNode(embed)) $showAsLink(embed);
      },
      { discrete: true }
    );
    editor.getEditorState().read(() => {
      const line = $getRoot().getChildAtIndex(1);
      expect(line?.getType()).toBe("paragraph");
      const link = $getRoot().getChildAtIndex(1)?.getFirstChild?.();
      expect($isEntityMentionNode(link) && link.getEntityId()).toBe(12);
    });
  });

  it("takes the line over when the link was all that was on it", () => {
    const editor = makeEditor();
    editor.update(
      () => {
        const link = $createEntityMentionNode(SearchEntityType.queue, 4, "Intake");
        $getRoot().clear().append($createParagraphNode().append(link));
        $showAsEmbed(link);
      },
      { discrete: true }
    );
    expect(types(editor)).toEqual(["reference-embed", "paragraph"]);
  });
});
