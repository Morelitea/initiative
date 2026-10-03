/**
 * Filing a ticket — asking for help, reporting something.
 *
 * One way in for every kind. Whether a kind can be filed from where the reader
 * is, or only written to by email, or neither, is the server's one answer per
 * kind; nothing here reasons about bindings or entitlements.
 */

import { useQuery } from "@tanstack/react-query";

import type {
  ModerationTicketCreate,
  SupportTicketCreate,
  TicketAccepted,
  TicketAvailability,
} from "@/api/generated/initiativeAPI.schemas";
import {
  fileTicket,
  getReadTicketAvailabilityQueryKey,
  readTicketAvailability,
} from "@/api/generated/tickets/tickets";
import { useApiMutation } from "@/hooks/useApiMutation";
import { docsUrl } from "@/lib/links";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

/** Where somebody is sent when there is neither a form nor an address. */
export const FAQ_URL = docsUrl("faq/");

/** One filing, told apart by its stream. */
export type TicketCreate = SupportTicketCreate | ModerationTicketCreate;

/**
 * What every kind of ticket offers the reader, standing in `communityId`.
 *
 * Asked once per community and left alone: what a deployment has set up does
 * not change while somebody is looking at a sidebar, and a wrong answer costs
 * a refusal the form already handles.
 */
export const useTicketAvailability = (
  communityId: number | null,
  options?: QueryOpts<TicketAvailability>
) => {
  const params = communityId == null ? undefined : { community_id: communityId };
  return useQuery<TicketAvailability>({
    queryKey: getReadTicketAvailabilityQueryKey(params),
    queryFn: () => readTicketAvailability(params),
    staleTime: 5 * 60 * 1000,
    ...options,
  });
};

export const useFileTicket = (options?: MutationOpts<TicketAccepted, TicketCreate>) =>
  useApiMutation<TicketAccepted, TicketCreate>(
    {
      // Nothing of the reader's changes by filing, so nothing is invalidated:
      // the case lands in a project they have no part in.
      mutationFn: (body) => fileTicket(body),
    },
    options
  );
