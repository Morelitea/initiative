/**
 * Links between things, as the one endpoint that serves all of them.
 *
 * The five per-tool attach routes — a project's documents, a queue item's
 * documents and tasks, an event's documents — were the same request with
 * different kinds in it. So is everything here: what varies between attaching a
 * document to a project and a task to a queue item is which two things are
 * named, and that is an argument.
 */

import {
  type EndpointRef,
  type RelationshipCreate,
  type RelationshipRead,
  RelationshipType,
  type SearchEntityType,
} from "@/api/generated/initiativeAPI.schemas";
import {
  createRelationshipApiV1CGuildIdRelationshipsPost,
  listRelationshipsApiV1CGuildIdRelationshipsGet,
  removeRelationshipApiV1CGuildIdRelationshipsRelationshipIdDelete,
  replaceRelationshipSliceApiV1CGuildIdRelationshipsPut,
} from "@/api/generated/relationships/relationships";

/** A thing, as a reference names it: `task:12`. */
const ref = (end: EndpointRef) => `${end.type}:${end.id}`;

/**
 * Which way a link runs relative to the thing being asked about.
 *
 * `both` is what an attach section wants — a link either way is the same
 * attachment. The two sides are separate questions only for the relations where
 * direction carries meaning: what this page names, and what names it.
 */
export type Direction = "inbound" | "outbound" | "both";

/**
 * Live links touching one thing.
 *
 * Both narrowings are optional, and passing neither asks the question a
 * relations surface actually has: *everything* connected to this, however it
 * runs. Each row says its own type and which way it points, so seven headings
 * are seven filters over one answer rather than seven requests.
 */
export const listRelated = (
  guildId: number,
  entity: EndpointRef,
  otherType: SearchEntityType | null = null,
  relationshipType: RelationshipType | null = null,
  direction: Direction = "both"
): Promise<RelationshipRead[]> =>
  listRelationshipsApiV1CGuildIdRelationshipsGet(guildId, {
    entity: ref(entity),
    relationship_type: relationshipType,
    other_type: otherType,
    direction,
  });

/** Link two things. */
export const relate = async (
  guildId: number,
  source: EndpointRef,
  target: EndpointRef,
  relationshipType: RelationshipType = RelationshipType.attached
): Promise<RelationshipRead> =>
  createRelationshipApiV1CGuildIdRelationshipsPost(guildId, {
    source,
    relationship_type: relationshipType,
    target,
  });

/**
 * Record one edge exactly as stated.
 *
 * The caller has already decided which end is the source — which is the whole
 * of what a directional relation means — so this passes it through rather than
 * assuming, as {@link relate} does, that the anchor describes the pair.
 */
export const createRelationship = (
  guildId: number,
  body: RelationshipCreate
): Promise<RelationshipRead> => createRelationshipApiV1CGuildIdRelationshipsPost(guildId, body);

/** Replace everything of one kind linked to a thing. */
export const setRelated = (
  guildId: number,
  entity: EndpointRef,
  otherType: SearchEntityType,
  otherIds: number[],
  relationshipType: RelationshipType = RelationshipType.attached
): Promise<RelationshipRead[]> =>
  replaceRelationshipSliceApiV1CGuildIdRelationshipsPut(guildId, otherIds, {
    entity: ref(entity),
    relationship_type: relationshipType,
    other_type: otherType,
  });

/**
 * Unlink two things.
 *
 * A link is removed by its own id, so the pair is resolved to one first. A
 * surface that renders links already holds their ids and should call
 * {@link removeRelationship} directly; this is for the callers that know the
 * two things and not the link between them.
 */
export const unrelate = async (
  guildId: number,
  entity: EndpointRef,
  other: EndpointRef,
  relationshipType: RelationshipType = RelationshipType.attached
): Promise<void> => {
  const links = await listRelated(guildId, entity, other.type, relationshipType);
  const link = links.find((row) => row.other.id === other.id);
  if (!link) return;
  await removeRelationship(guildId, link.id);
};

/** Remove a link by its own id. */
export const removeRelationship = (guildId: number, relationshipId: number): Promise<void> =>
  removeRelationshipApiV1CGuildIdRelationshipsRelationshipIdDelete(guildId, relationshipId);
