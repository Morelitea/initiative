/**
 * Links between things, as the one endpoint that serves all of them.
 *
 * The five per-tool attach routes — a project's documents, a queue item's
 * documents and tasks, an event's documents — were the same request with
 * different kinds in it. These wrappers are where that vocabulary lives, so a
 * calling hook says what it means ("attach this document to this project")
 * rather than assembling a reference string.
 */

import {
  type RelationshipRead,
  RelationshipType,
  SearchEntityType,
} from "@/api/generated/initiativeAPI.schemas";
import {
  createRelationshipApiV1GGuildIdRelationshipsPost,
  listRelationshipsApiV1GGuildIdRelationshipsGet,
  removeRelationshipApiV1GGuildIdRelationshipsRelationshipIdDelete,
  replaceRelationshipSliceApiV1GGuildIdRelationshipsPut,
} from "@/api/generated/relationships/relationships";

/** A thing, as a reference names it: `task:12`. */
const ref = (type: SearchEntityType, id: number) => `${type}:${id}`;

/** Every live `attached` link between one thing and one other kind. */
export const listAttached = (
  guildId: number,
  entityType: SearchEntityType,
  entityId: number,
  otherType: SearchEntityType
): Promise<RelationshipRead[]> =>
  listRelationshipsApiV1GGuildIdRelationshipsGet(guildId, {
    entity: ref(entityType, entityId),
    relationship_type: RelationshipType.attached,
    other_type: otherType,
  });

/** Replace everything of one kind attached to a thing. */
export const setAttached = (
  guildId: number,
  entityType: SearchEntityType,
  entityId: number,
  otherType: SearchEntityType,
  otherIds: number[]
): Promise<RelationshipRead[]> =>
  replaceRelationshipSliceApiV1GGuildIdRelationshipsPut(guildId, otherIds, {
    entity: ref(entityType, entityId),
    relationship_type: RelationshipType.attached,
    other_type: otherType,
  });

export const attachDocumentToProject = async (
  guildId: number,
  projectId: number,
  documentId: number
): Promise<void> => {
  await createRelationshipApiV1GGuildIdRelationshipsPost(guildId, {
    source: { type: SearchEntityType.project, id: projectId },
    relationship_type: RelationshipType.attached,
    target: { type: SearchEntityType.document, id: documentId },
  });
};

export const detachDocumentFromProject = async (
  guildId: number,
  projectId: number,
  documentId: number
): Promise<void> => {
  // A link is removed by its own id, so the pair has to be resolved to one
  // first. The section that will render these carries the ids already; until
  // it does, this is the lookup that used to be the route's path parameters.
  const links = await listAttached(
    guildId,
    SearchEntityType.project,
    projectId,
    SearchEntityType.document
  );
  const link = links.find((row) => row.other.id === documentId);
  if (!link) return;
  await removeRelationshipApiV1GGuildIdRelationshipsRelationshipIdDelete(guildId, link.id);
};
