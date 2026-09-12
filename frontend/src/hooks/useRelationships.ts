/**
 * Reading the graph, from either side of it.
 *
 * The write helpers live in `@/api/relationships` and are called from the hooks
 * that own the thing being changed — a project's attach dialog invalidates the
 * project. What is here is the reads that belong to no one tool, because the
 * question they answer is about a pair of things rather than about either.
 */

import { useQuery } from "@tanstack/react-query";

import {
  type EndpointRef,
  type RelationshipRead,
  RelationshipType,
  type SearchEntityType,
} from "@/api/generated/initiativeAPI.schemas";
import { getListRelationshipsApiV1GGuildIdRelationshipsGetQueryKey } from "@/api/generated/relationships/relationships";
import { listRelated } from "@/api/relationships";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";

/**
 * What links here: the things whose own content names this one.
 *
 * Keyed by the generated helper rather than by hand, so the key carries the
 * `/g/{guildId}` segment `q.relationships()` matches on and a save that changes
 * what a body refers to reaches this cache.
 */
export const useReferencedBy = (
  entity: EndpointRef,
  otherType: SearchEntityType,
  options?: { enabled?: boolean }
) => {
  const guildId = useActiveGuildId();
  const params = {
    entity: `${entity.type}:${entity.id}`,
    relationship_type: RelationshipType.references,
    other_type: otherType,
    direction: "inbound" as const,
  };
  return useQuery<RelationshipRead[]>({
    queryKey: getListRelationshipsApiV1GGuildIdRelationshipsGetQueryKey(guildId, params),
    queryFn: () => listRelated(guildId, entity, otherType, RelationshipType.references, "inbound"),
    ...options,
  });
};
