/**
 * Asking whoever runs this deployment for help.
 *
 * Whether a community's members may is an operator entitlement, and something
 * has to be bound to receive what they send — the server folds both into one
 * answer, so nothing here reasons about either.
 */

import { useQuery } from "@tanstack/react-query";

import type {
  SupportAvailability,
  SupportRequestAccepted,
  SupportRequestCreate,
} from "@/api/generated/initiativeAPI.schemas";
import {
  askForHelpApiV1CGuildIdSupportPost,
  getSupportAvailabilityApiV1CGuildIdSupportGetQueryKey,
  supportAvailabilityApiV1CGuildIdSupportGet,
} from "@/api/generated/support/support";
import { useApiMutation } from "@/hooks/useApiMutation";
import { docsUrl } from "@/lib/links";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

/** Where somebody is sent when this community takes no help requests. */
export const FAQ_URL = docsUrl("faq/");

/**
 * Whether to offer the form here rather than the FAQ.
 *
 * Asked once per community and left alone: an operator entitlement does not
 * change while somebody is looking at a sidebar, and a wrong answer costs a
 * refusal the form already handles.
 */
export const useSupportAvailability = (
  guildId: number | null,
  options?: QueryOpts<SupportAvailability>
) =>
  useQuery<SupportAvailability>({
    queryKey: getSupportAvailabilityApiV1CGuildIdSupportGetQueryKey(guildId ?? 0),
    queryFn: () => supportAvailabilityApiV1CGuildIdSupportGet(guildId as number),
    enabled: guildId != null,
    staleTime: 5 * 60 * 1000,
    ...options,
  });

export const useAskForHelp = (
  guildId: number,
  options?: MutationOpts<SupportRequestAccepted, SupportRequestCreate>
) =>
  useApiMutation<SupportRequestAccepted, SupportRequestCreate>(
    {
      // Nothing of the reader's is changed by asking, so nothing is invalidated:
      // the case lands in a project they have no part in.
      mutationFn: (body) => askForHelpApiV1CGuildIdSupportPost(guildId, body),
    },
    options
  );
