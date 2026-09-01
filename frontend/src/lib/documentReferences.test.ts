import { createEditor, type LexicalEditor } from "lexical";
import { describe, expect, it } from "vitest";

import { BadgeKind, SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import { $createBadgeNode, BadgeNode } from "@/components/ui/editor/nodes/badge-node";
import {
  $createEntityMentionNode,
  EntityMentionNode,
} from "@/components/ui/editor/nodes/entity-mention-node";
import { collectReferences, nodeReference } from "@/lib/documentReferences";

function inEditor<T>(fn: () => T): T {
  const editor: LexicalEditor = createEditor({
    nodes: [BadgeNode, EntityMentionNode],
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

  it("includes its chips", () => {
    const ref = inEditor(() =>
      nodeReference($createBadgeNode(BadgeKind["task:status"], 12, "Ship it"))
    );
    expect(ref).toBe("task:12:status");
  });

  it("asks about a thing once, however many times it is named", () => {
    const refs = inEditor(() =>
      collectReferences([
        $createEntityMentionNode(SearchEntityType.task, 12, "Ship it"),
        $createEntityMentionNode(SearchEntityType.task, 12, "Ship it"),
        $createBadgeNode(BadgeKind["task:status"], 12, "Ship it"),
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
