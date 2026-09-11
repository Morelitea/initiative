/**
 * Archiving, for anything that can be finished with.
 *
 * The backend serves one pair of endpoints for every archivable kind, so this
 * is one pair of hooks rather than a pair per tool. Pass the kind and the id.
 *
 * Archived content is read-only all the way down, so what a successful call
 * changes is not only the row it named — every list and detail view that could
 * be showing something inside it is stale too, which is why this invalidates
 * broadly rather than by kind.
 */
import {
  archiveEntityApiV1GGuildIdArchiveEntityTypeEntityIdPost,
  unarchiveEntityApiV1GGuildIdUnarchiveEntityTypeEntityIdPost,
} from "@/api/generated/archive/archive";
import type { ArchivableType, ArchiveResponse } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { useGuildMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";

export type ArchiveTarget = { entityType: ArchivableType; entityId: number };

const refresh = () =>
  invalidate(q.allProjects(), q.allTasks(), q.allInitiatives(), q.allDocuments());

export const useArchiveEntity = (options?: MutationOpts<ArchiveResponse, ArchiveTarget>) =>
  useGuildMutation<ArchiveResponse, ArchiveTarget>(
    {
      mutationFn: (guildId, { entityType, entityId }) =>
        archiveEntityApiV1GGuildIdArchiveEntityTypeEntityIdPost(guildId, entityType, entityId),
      invalidate: refresh,
      errorKey: "common:archiveError",
    },
    options
  );

export const useUnarchiveEntity = (options?: MutationOpts<ArchiveResponse, ArchiveTarget>) =>
  useGuildMutation<ArchiveResponse, ArchiveTarget>(
    {
      mutationFn: (guildId, { entityType, entityId }) =>
        unarchiveEntityApiV1GGuildIdUnarchiveEntityTypeEntityIdPost(guildId, entityType, entityId),
      invalidate: refresh,
      errorKey: "common:unarchiveError",
    },
    options
  );
