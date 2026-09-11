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
import { listRelated } from "@/api/relationships";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";

/** What links here: the things whose own content names this one. */
export const useReferencedBy = (
  entity: EndpointRef,
  otherType: SearchEntityType,
  options?: { enabled?: boolean }
) => {
  const guildId = useActiveGuildId();
  return useQuery<RelationshipRead[]>({
    queryKey: ["/api/v1/relationships", guildId, entity.type, entity.id, otherType, "inbound"],
    queryFn: () => listRelated(guildId, entity, otherType, RelationshipType.references, "inbound"),
    ...options,
  });
};
