import {
  $createParagraphNode,
  $createTextNode,
  $getRoot,
  createEditor,
  type LexicalEditor,
} from "lexical";
import { describe, expect, it } from "vitest";

import { SearchEntityType, SmartChipKind } from "@/api/generated/initiativeAPI.schemas";
import {
  $createEntityMentionNode,
  EntityMentionNode,
} from "@/components/ui/editor/nodes/entity-mention-node";
import { $createSmartChipNode, SmartChipNode } from "@/components/ui/editor/nodes/smart-chip-node";
import { collectReferences, documentReferences, nodeReference } from "@/lib/documentReferences";

function inEditor<T>(fn: () => T): T {
  const editor: LexicalEditor = createEditor({
    nodes: [SmartChipNode, EntityMentionNode],
    onError: (error) => {
      throw error;
    },
  });
  let result!: T;
  editor.update(
    () => {
      result = fn();
    },
    { discrete: true }
  );
  return result;
}

describe("what a page asks about", () => {
  it("includes the things it links to, not only its chips", () => {
    // The whole point of live names: a reference nobody asks about can only
    // ever show the words it was written with.
    const ref = inEditor(() =>
      nodeReference($createEntityMentionNode(SearchEntityType.task, 12, "Ship it"))
    );
    expect(ref).toBe("task:12");
  });

  it("asks one question per chip, because the answer names its own thing", () => {
    // A chip's reading comes back with what it is a fact about, so a page of
    // chips costs one reference each and stays inside what one request reads.
    const ref = inEditor(() =>
      nodeReference($createSmartChipNode(SmartChipKind["task:status"], 12, "Ship it"))
    );
    expect(ref).toBe("task:12:status");
  });

  it("ignores a node that names nothing", () => {
    expect(inEditor(() => nodeReference($createTextNode("plain")))).toBeNull();
  });

  it("asks about a thing once, however many times it is named", () => {
    const refs = inEditor(() =>
      collectReferences([
        $createEntityMentionNode(SearchEntityType.task, 12, "Ship it"),
        $createEntityMentionNode(SearchEntityType.task, 12, "Ship it"),
        $createSmartChipNode(SmartChipKind["task:status"], 12, "Ship it"),
      ])
    );
    // The name and the status are different questions; naming it twice is not.
    expect(refs).toEqual(["task:12", "task:12:status"]);
  });

  it("asks the same question however the nodes are ordered", () => {
    const one = inEditor(() =>
      collectReferences([
        $createEntityMentionNode(SearchEntityType.queue, 4, "Intake"),
        $createEntityMentionNode(SearchEntityType.task, 12, "Ship it"),
      ])
    );
    const other = inEditor(() =>
      collectReferences([
        $createEntityMentionNode(SearchEntityType.task, 12, "Ship it"),
        $createEntityMentionNode(SearchEntityType.queue, 4, "Intake"),
      ])
    );
    expect(one).toEqual(other);
  });

  it("ignores ordinary prose", () => {
    expect(inEditor(() => collectReferences([]))).toEqual([]);
  });
});

describe("what a page asks about, read off the page", () => {
  it("finds the references written into a document", () => {
    // The scope asks the editor, not a list handed to it — a walk that comes
    // back empty leaves every chip and every name showing what it was typed as.
    const editor: LexicalEditor = createEditor({
      nodes: [SmartChipNode, EntityMentionNode],
      onError: (error) => {
        throw error;
      },
    });
    editor.update(
      () => {
        const paragraph = $createParagraphNode();
        paragraph.append(
          $createTextNode("see "),
          $createEntityMentionNode(SearchEntityType.task, 12, "Ship it"),
          $createSmartChipNode(SmartChipKind["counter:value"], 4, "Signups")
        );
        $getRoot().append(paragraph);
      },
      { discrete: true }
    );

    expect(documentReferences(editor.getEditorState())).toEqual(["counter:4:value", "task:12"]);
  });
});
