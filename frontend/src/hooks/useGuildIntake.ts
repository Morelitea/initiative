/**
 * The operations community's intake: which of its projects each stream of
 * operations work lands in.
 *
 * Every hook here is the community's superadmin's, on the community's own
 * routes, and only in the community the platform names — every other one
 * answers 404, which is how the settings layout knows whether to offer the tab.
 */

import { useQuery } from "@tanstack/react-query";

import type {
  IntakeBindingRead,
  IntakeBindingsRead,
  IntakeBindingUpsert,
  IntakeOptionsRead,
  IntakeStream,
} from "@/api/generated/initiativeAPI.schemas";
import {
  deleteIntakeBindingApiV1GGuildIdIntakeStreamDelete,
  getReadIntakeBindingsApiV1GGuildIdIntakeGetQueryKey,
  getReadIntakeOptionsApiV1GGuildIdIntakeOptionsGetQueryKey,
  importIntakeBlueprintApiV1GGuildIdIntakeStreamBlueprintPost,
  readIntakeBindingsApiV1GGuildIdIntakeGet,
  readIntakeOptionsApiV1GGuildIdIntakeOptionsGet,
  upsertIntakeBindingApiV1GGuildIdIntakeStreamPut,
} from "@/api/generated/intake/intake";
import { invalidate, q } from "@/api/query-keys";
import { useApiMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

/**
 * Where each stream lands, and when it last opened a case. A 404 is an answer
 * rather than a failure — this is not the operations community — so it is not
 * retried.
 */
export const useGuildIntake = (guildId: number, options?: QueryOpts<IntakeBindingsRead>) =>
  useQuery<IntakeBindingsRead>({
    queryKey: getReadIntakeBindingsApiV1GGuildIdIntakeGetQueryKey(guildId),
    queryFn: () => readIntakeBindingsApiV1GGuildIdIntakeGet(guildId),
    retry: false,
    ...options,
  });

/** This community's initiatives, projects and statuses, for the pickers. */
export const useGuildIntakeOptions = (guildId: number, options?: QueryOpts<IntakeOptionsRead>) =>
  useQuery<IntakeOptionsRead>({
    queryKey: getReadIntakeOptionsApiV1GGuildIdIntakeOptionsGetQueryKey(guildId),
    queryFn: () => readIntakeOptionsApiV1GGuildIdIntakeOptionsGet(guildId),
    ...options,
  });

/**
 * Both reads are invalidated by every write: a blueprint adds a project the
 * pickers offer, and binding a stream changes what the list shows.
 */
const refreshIntake = () => invalidate(q.intakeBindings());

export const useUpsertIntakeBinding = (
  guildId: number,
  options?: MutationOpts<IntakeBindingRead, { stream: IntakeStream; body: IntakeBindingUpsert }>
) =>
  useApiMutation<IntakeBindingRead, { stream: IntakeStream; body: IntakeBindingUpsert }>(
    {
      mutationFn: ({ stream, body }) =>
        upsertIntakeBindingApiV1GGuildIdIntakeStreamPut(guildId, stream, body),
      invalidate: refreshIntake,
    },
    options
  );

export const useImportIntakeBlueprint = (
  guildId: number,
  options?: MutationOpts<IntakeBindingRead, { stream: IntakeStream; initiativeId: number }>
) =>
  useApiMutation<IntakeBindingRead, { stream: IntakeStream; initiativeId: number }>(
    {
      mutationFn: ({ stream, initiativeId }) =>
        importIntakeBlueprintApiV1GGuildIdIntakeStreamBlueprintPost(guildId, stream, {
          initiative_id: initiativeId,
        }),
      invalidate: refreshIntake,
    },
    options
  );

export const useDeleteIntakeBinding = (
  guildId: number,
  options?: MutationOpts<void, IntakeStream>
) =>
  useApiMutation<void, IntakeStream>(
    {
      mutationFn: (stream) => deleteIntakeBindingApiV1GGuildIdIntakeStreamDelete(guildId, stream),
      invalidate: refreshIntake,
    },
    options
  );
