/**
 * What a comment points at.
 *
 * A comment is markdown, and its references are written into the text —
 * `#task[Ship it](12)`, `@[Ada](4)`. The label in there is what the writer saw
 * when they wrote it, so it is a fallback rather than the answer: what a reader
 * should see is what the thing is called now.
 *
 * This finds them so a whole thread can be resolved in one request, rather than
 * each comment asking for itself.
 */

import type { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import { typeForTrigger } from "@/lib/mentions";
import { referenceRef } from "@/lib/smartChips";

//: `#task[Label](12)` — the trigger word, then a label, then the id.
const ENTITY_PATTERN = /#([\w-]+)\[[^\]]*\]\((\d+)\)/g;
//: `@[Ada](4)`.
const USER_PATTERN = /@\[[^\]]*\]\((\d+)\)/g;

export interface CommentReferences {
  /** `task:12` for every thing named, ready to be read together. */
  refs: string[];
  /** Everyone mentioned, so their current names can be read together. */
  userIds: number[];
}

/** Every reference across a whole thread, deduplicated. */
export const collectCommentReferences = (contents: string[]): CommentReferences => {
  const refs = new Set<string>();
  const userIds = new Set<number>();

  for (const content of contents) {
    for (const [, trigger, id] of content.matchAll(ENTITY_PATTERN)) {
      const entityType = typeForTrigger(trigger);
      // A trigger this build does not know is left alone: the comment still
      // renders, showing the words it was written with.
      if (entityType) refs.add(referenceRef(entityType as SearchEntityType, Number(id)));
    }
    for (const [, id] of content.matchAll(USER_PATTERN)) {
      userIds.add(Number(id));
    }
  }

  return { refs: [...refs].sort(), userIds: [...userIds].sort((a, b) => a - b) };
};
