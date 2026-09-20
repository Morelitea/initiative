import { useMemo } from "react";

import type { RelationshipRead, SmartChipState } from "@/api/generated/initiativeAPI.schemas";
import { currentStates, useSmartChipStates } from "@/hooks/useSmartChips";
import { chipAspect, chipKindsFor, chipRef } from "@/lib/smartChips";

/**
 * The one fact worth showing about each kind of far end.
 *
 * A kind offers several — a task has a status, an assignee, a due date and a
 * priority — and a list of links has room for one. Status is what a reader of a
 * list of links is asking about: whether the thing is done, when it happens,
 * how far along it is.
 */
const HEADLINE_ASPECT = ["status", "progress", "when", "value"];

/** The chip reference for one far end, or null where its kind shows nothing. */
const headlineRef = (type: RelationshipRead["other"]["type"], id: number): string | null => {
  const kinds = chipKindsFor(type);
  for (const aspect of HEADLINE_ASPECT) {
    const kind = kinds.find((candidate) => chipAspect(candidate) === aspect);
    if (kind) return chipRef(kind, id);
  }
  return null;
};

/**
 * What every far end of a set of edges is currently doing, keyed by `type:id`.
 *
 * A list of links is a list of names, and a name does not say whether the task
 * is finished or when the event is. This asks the server the same way a
 * document's chips do — one batched request for the lot, re-read on a timer —
 * so the panel says what things are now rather than what they were called when
 * somebody linked them.
 */
export const useRelatedStates = (edges: RelationshipRead[], enabled = true) => {
  const refs = useMemo(() => {
    const found: string[] = [];
    for (const edge of edges) {
      const ref = headlineRef(edge.other.type, edge.other.id);
      if (ref) found.push(ref);
    }
    return [...new Set(found)];
  }, [edges]);

  const { data } = useSmartChipStates(refs, enabled && refs.length > 0);

  return useMemo(() => {
    const byRef = currentStates(data?.items ?? [], refs);
    const byEnd = new Map<string, SmartChipState>();
    for (const edge of edges) {
      const ref = headlineRef(edge.other.type, edge.other.id);
      const state = ref ? byRef.get(ref) : undefined;
      if (state) byEnd.set(`${edge.other.type}:${edge.other.id}`, state);
    }
    return byEnd;
  }, [data, refs, edges]);
};
