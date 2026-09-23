/**
 * The owner's intake settings: which community receives operations work,
 * which project each stream lands in, and who somebody is told to contact.
 *
 * Every hook here is behind `config.manage` on the server. The read carries
 * every stream whether bound or not, so the page renders the full set rather
 * than only what somebody already configured.
 */

import { useQuery } from "@tanstack/react-query";

import type {
  IntakeBindingRead,
  IntakeBindingUpsert,
  IntakeContactUpdate,
  IntakeOptionsRead,
  IntakeSettingsRead,
  IntakeStream,
  OperationsGuildUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import {
  deleteBindingApiV1SettingsIntakeStreamDelete,
  getReadIntakeOptionsApiV1SettingsIntakeOptionsGetQueryKey,
  getReadIntakeSettingsApiV1SettingsIntakeGetQueryKey,
  importBlueprintApiV1SettingsIntakeStreamBlueprintPost,
  readIntakeOptionsApiV1SettingsIntakeOptionsGet,
  readIntakeSettingsApiV1SettingsIntakeGet,
  updateGeneralContactApiV1SettingsIntakeContactPut,
  updateOperationsGuildApiV1SettingsIntakeGuildPut,
  updateStreamContactApiV1SettingsIntakeStreamContactPut,
  upsertBindingApiV1SettingsIntakeStreamPut,
} from "@/api/generated/intake/intake";
import { invalidate, q } from "@/api/query-keys";
import { useApiMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

/** Where each stream lands, and when it last opened a case. */
export const useIntakeSettings = (options?: QueryOpts<IntakeSettingsRead>) =>
  useQuery<IntakeSettingsRead>({
    queryKey: getReadIntakeSettingsApiV1SettingsIntakeGetQueryKey(),
    queryFn: () => readIntakeSettingsApiV1SettingsIntakeGet(),
    ...options,
  });

/** The operations community's initiatives, projects and statuses, for the pickers. */
export const useIntakeOptions = (options?: QueryOpts<IntakeOptionsRead>) =>
  useQuery<IntakeOptionsRead>({
    queryKey: getReadIntakeOptionsApiV1SettingsIntakeOptionsGetQueryKey(),
    queryFn: () => readIntakeOptionsApiV1SettingsIntakeOptionsGet(),
    ...options,
  });

/**
 * Both reads are invalidated by every write: naming a community changes what
 * the pickers can offer, and binding a stream changes what the list shows.
 */
const refreshIntake = () => invalidate(q.intakeSettings(), q.intakeOptions());

export const useUpdateOperationsGuild = (
  options?: MutationOpts<IntakeSettingsRead, OperationsGuildUpdate>
) =>
  useApiMutation<IntakeSettingsRead, OperationsGuildUpdate>(
    {
      mutationFn: (data) => updateOperationsGuildApiV1SettingsIntakeGuildPut(data),
      invalidate: refreshIntake,
    },
    options
  );

export const useUpsertIntakeBinding = (
  options?: MutationOpts<IntakeBindingRead, { stream: IntakeStream; body: IntakeBindingUpsert }>
) =>
  useApiMutation<IntakeBindingRead, { stream: IntakeStream; body: IntakeBindingUpsert }>(
    {
      mutationFn: ({ stream, body }) => upsertBindingApiV1SettingsIntakeStreamPut(stream, body),
      invalidate: refreshIntake,
    },
    options
  );

export const useImportIntakeBlueprint = (
  options?: MutationOpts<IntakeBindingRead, { stream: IntakeStream; initiativeId: number }>
) =>
  useApiMutation<IntakeBindingRead, { stream: IntakeStream; initiativeId: number }>(
    {
      mutationFn: ({ stream, initiativeId }) =>
        importBlueprintApiV1SettingsIntakeStreamBlueprintPost(stream, {
          initiative_id: initiativeId,
        }),
      invalidate: refreshIntake,
    },
    options
  );

export const useDeleteIntakeBinding = (options?: MutationOpts<void, IntakeStream>) =>
  useApiMutation<void, IntakeStream>(
    {
      mutationFn: (stream) => deleteBindingApiV1SettingsIntakeStreamDelete(stream),
      invalidate: refreshIntake,
    },
    options
  );

/** The deployment's catch-all contact address; `null` clears it. */
export const useUpdateIntakeGeneralContact = (
  options?: MutationOpts<IntakeSettingsRead, IntakeContactUpdate>
) =>
  useApiMutation<IntakeSettingsRead, IntakeContactUpdate>(
    {
      mutationFn: (data) => updateGeneralContactApiV1SettingsIntakeContactPut(data),
      invalidate: refreshIntake,
    },
    options
  );

/** One stream's own contact address; `null` clears it back to the general one. */
export const useUpdateIntakeStreamContact = (
  options?: MutationOpts<IntakeSettingsRead, { stream: IntakeStream; body: IntakeContactUpdate }>
) =>
  useApiMutation<IntakeSettingsRead, { stream: IntakeStream; body: IntakeContactUpdate }>(
    {
      mutationFn: ({ stream, body }) =>
        updateStreamContactApiV1SettingsIntakeStreamContactPut(stream, body),
      invalidate: refreshIntake,
    },
    options
  );
