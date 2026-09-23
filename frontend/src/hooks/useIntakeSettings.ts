/**
 * The owner's intake settings: which community receives operations work, and
 * who somebody is told to contact.
 *
 * Every hook here is behind `config.manage` on the server. Where each stream
 * lands inside that community is the community's own setting, read and written
 * through `useGuildIntake`.
 */

import { useQuery } from "@tanstack/react-query";

import type {
  IntakeContactUpdate,
  IntakeSettingsRead,
  IntakeStream,
  OperationsGuildUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getReadIntakeSettingsApiV1SettingsIntakeGetQueryKey,
  readIntakeSettingsApiV1SettingsIntakeGet,
  updateGeneralContactApiV1SettingsIntakeContactPut,
  updateOperationsGuildApiV1SettingsIntakeGuildPut,
  updateStreamContactApiV1SettingsIntakeStreamContactPut,
} from "@/api/generated/intake/intake";
import { invalidate, q } from "@/api/query-keys";
import { useApiMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

/** Which community, which streams it receives, and who to contact. */
export const useIntakeSettings = (options?: QueryOpts<IntakeSettingsRead>) =>
  useQuery<IntakeSettingsRead>({
    queryKey: getReadIntakeSettingsApiV1SettingsIntakeGetQueryKey(),
    queryFn: () => readIntakeSettingsApiV1SettingsIntakeGet(),
    ...options,
  });

const refreshIntake = () => invalidate(q.intakeSettings());

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
