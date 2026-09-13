/**
 * The graph, from either side of it.
 *
 * These belong to no one tool, because the question they answer is about a pair
 * of things rather than about either: the same hook serves a project's
 * attachments, a task's dependencies and a document's backlinks.
 *
 * The per-tool attach hooks in `useProjects` / `useQueues` stay, because they
 * keep a shape their own callers already expect. What is different here is that
 * a write says which tool sits at *each* end and refreshes both.
 */

import { useQueries, useQuery } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";

import {
  type EndpointRef,
  type RelatedEnd,
  type RelationshipCreate,
  type RelationshipRead,
  RelationshipType,
  SearchEntityType,
  type Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { getListRelationshipsApiV1GGuildIdRelationshipsGetQueryKey } from "@/api/generated/relationships/relationships";
import { invalidate, q } from "@/api/query-keys";
import { createRelationship, listRelated, removeRelationship } from "@/api/relationships";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";

/**
 * Every live edge touching one thing, whichever way it runs.
 *
 * One request, because each row says its own type and the side it runs relative
 * to this thing — so a surface showing seven headings filters one answer rather
 * than asking seven times. See `groupEdges` in `@/lib/relationships`.
 */
export const useRelationshipsFor = (entity: EndpointRef, options?: { enabled?: boolean }) => {
  const guildId = useActiveGuildId();
  const params = {
    entity: `${entity.type}:${entity.id}`,
    relationship_type: null,
    other_type: null,
    direction: "both" as const,
  };
  return useQuery<RelationshipRead[]>({
    queryKey: getListRelationshipsApiV1GGuildIdRelationshipsGetQueryKey(guildId, params),
    queryFn: () => listRelated(guildId, entity, null, null, "both"),
    ...options,
  });
};

/** A tool and which one of them — what a cache entry for the shims is keyed by. */
export interface ToolRef {
  tool: Tool;
  id: number;
}

/** The tool a far end is addressed inside, where it named one. */
const toolRefOf = (end: RelatedEnd): ToolRef | null =>
  end.tool && end.tool_id != null ? { tool: end.tool, id: end.tool_id } : null;

/**
 * What changing a link invalidates: the graph, and the tool at each end of it.
 *
 * Both ends, because a link is a fact about a pair and several tools still
 * serialise their own side of one — a project lists its documents, a document
 * lists its projects, a queue item its documents and tasks. Those shapes read
 * differently the moment an edge moves, whichever end was clicked.
 */
const invalidateEdge = (...ends: (ToolRef | null | undefined)[]) =>
  invalidate(
    q.relationships(),
    ...ends.filter((end): end is ToolRef => Boolean(end)).map((end) => q.tool(end.tool, end.id))
  );

/**
 * Record one edge.
 *
 * Takes the edge already stated as source → target: which end is the source is
 * the whole of what a directional relation means, and `edgeFor` in
 * `@/lib/relationships` is what decides it.
 */
export const useRelate = (
  anchor?: ToolRef | null,
  options?: MutationOpts<RelationshipRead, RelationshipCreate>
) =>
  useGuildMutation<RelationshipRead, RelationshipCreate>(
    {
      mutationFn: (guildId, body) => createRelationship(guildId, body),
      invalidate: (data) => invalidateEdge(anchor, toolRefOf(data.other)),
      errorKey: "relations:addError",
    },
    options
  );

/**
 * Take one edge back.
 *
 * Given the whole row rather than its id, so the far end's tool can be
 * invalidated too — the row is already on screen wherever this is called.
 */
export const useUnrelate = (
  anchor?: ToolRef | null,
  options?: MutationOpts<void, RelationshipRead>
) =>
  useGuildMutation<void, RelationshipRead>(
    {
      mutationFn: (guildId, row) => removeRelationship(guildId, row.id),
      invalidate: (_data, row) => invalidateEdge(anchor, toolRefOf(row.other)),
      errorKey: "relations:removeError",
    },
    options
  );

/** How far out the graph will walk. */
export const MAX_HOPS = 3;

/**
 * How many things a hop may ask about.
 *
 * Each one is a request, and a thing at the centre of a busy initiative can name
 * a great many. Without a ceiling, "show me three hops" is an unbounded fan-out
 * over somebody's whole community — and a picture of a thousand nodes says less
 * than a picture of forty anyway, so the limit costs nothing that was worth
 * drawing. The nearest are kept: what came back first is what the thing itself
 * names, before anything further out.
 */
export const HOP_BUDGET = 40;

/** One thing in a neighbourhood, and how many hops out it was found. */
export interface GraphNode {
  ref: EndpointRef;
  end: RelatedEnd;
  depth: number;
}

/** One link in a neighbourhood, as the pair of things it joins. */
export interface GraphEdge {
  id: number;
  from: string;
  to: string;
  relationship_type: RelationshipRead["relationship_type"];
  direction: string;
  provenance: string;
}

export interface Neighbourhood {
  nodes: GraphNode[];
  edges: GraphEdge[];
  isLoading: boolean;
}

const keyOf = (ref: { type: SearchEntityType; id: number }) => `${ref.type}:${ref.id}`;

/**
 * Everything within `hops` of one thing.
 *
 * The endpoint answers for one thing at a time, so a second hop is a request per
 * neighbour found in the first. That is the honest cost of walking a graph whose
 * every step is gated: each of those requests is what proves the reader may see
 * that far. React Query holds them, so opening the same neighbourhood again is
 * free, and a hop nobody asked for is never fetched.
 *
 * Capped at {@link MAX_HOPS}, and written as a fixed number of levels rather
 * than a loop, because the number of hooks a component calls cannot vary between
 * renders. Three is also about as much as a picture this size can say.
 */
export const useRelationsNeighbourhood = (
  entity: EndpointRef,
  hops: number,
  options?: { enabled?: boolean; includeTags?: boolean }
): Neighbourhood => {
  const guildId = useActiveGuildId();
  const enabled = options?.enabled ?? true;
  const includeTags = options?.includeTags ?? false;

  /**
   * Labels, left out unless asked for — and left out *here* rather than when
   * drawing, which is the whole point. A tag is shared by everything carrying
   * it, so walking through one reaches the whole community in a hop: leaving it
   * in the picture and out of the walk would be the worst of both.
   */
  const keep = useCallback(
    (row: RelationshipRead) =>
      includeTags ||
      (row.relationship_type !== RelationshipType.tagged_with &&
        row.other.type !== SearchEntityType.tag),
    [includeTags]
  );

  /** One entity's edges, as a query `useQueries` can be handed. */
  const ask = (ref: EndpointRef, active: boolean) => ({
    queryKey: getListRelationshipsApiV1GGuildIdRelationshipsGetQueryKey(guildId, {
      entity: keyOf(ref),
      relationship_type: null,
      other_type: null,
      direction: "both" as const,
    }),
    queryFn: () => listRelated(guildId, ref, null, null, "both"),
    enabled: active,
  });

  // Three levels, written out. `useQueries` takes a list that may change length,
  // so the fan-out is fine; what cannot change is how many times it is called.
  const first = useQueries({ queries: [ask(entity, enabled)] });
  const firstRows = useMemo(() => (first[0]?.data ?? []).filter(keep), [first[0]?.data, keep]);

  const secondRefs = useMemo(
    () =>
      hops >= 2
        ? firstRows.slice(0, HOP_BUDGET).map((row) => ({ type: row.other.type, id: row.other.id }))
        : [],
    [firstRows, hops]
  );
  const second = useQueries({
    queries: secondRefs.map((ref) => ask(ref, enabled && hops >= 2)),
  });

  const thirdRefs = useMemo(() => {
    if (hops < 3) return [];
    const seen = new Set([keyOf(entity), ...secondRefs.map(keyOf)]);
    const next: EndpointRef[] = [];
    for (const query of second) {
      for (const row of (query.data ?? []).filter(keep)) {
        if (next.length >= HOP_BUDGET) return next;
        const ref = { type: row.other.type, id: row.other.id };
        if (seen.has(keyOf(ref))) continue;
        seen.add(keyOf(ref));
        next.push(ref);
      }
    }
    return next;
  }, [second, secondRefs, entity, hops, keep]);
  const third = useQueries({
    queries: thirdRefs.map((ref) => ask(ref, enabled && hops >= 3)),
  });

  return useMemo(() => {
    const nodes = new Map<string, GraphNode>();
    const edges = new Map<number, GraphEdge>();

    const absorb = (anchor: EndpointRef, rows: RelationshipRead[], depth: number) => {
      for (const row of rows.filter(keep)) {
        const far = { type: row.other.type, id: row.other.id };
        const key = keyOf(far);
        const found = nodes.get(key);
        // Kept at the shortest way round: a thing two hops out one way and one
        // hop out another is one hop out.
        if (!found || found.depth > depth) {
          nodes.set(key, { ref: far, end: row.other, depth });
        }
        edges.set(row.id, {
          id: row.id,
          from: keyOf(anchor),
          to: key,
          relationship_type: row.relationship_type,
          direction: row.direction,
          provenance: row.provenance,
        });
      }
    };

    absorb(entity, firstRows, 1);
    if (hops >= 2) {
      secondRefs.forEach((ref, index) => {
        absorb(ref, second[index]?.data ?? [], 2);
      });
    }
    if (hops >= 3) {
      thirdRefs.forEach((ref, index) => {
        absorb(ref, third[index]?.data ?? [], 3);
      });
    }
    nodes.delete(keyOf(entity));

    return {
      nodes: [...nodes.values()],
      edges: [...edges.values()],
      isLoading:
        (first[0]?.isLoading ?? false) ||
        second.some((query) => query.isLoading) ||
        third.some((query) => query.isLoading),
    };
  }, [entity, firstRows, secondRefs, second, thirdRefs, third, first[0]?.isLoading, hops, keep]);
};
