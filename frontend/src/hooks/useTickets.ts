/**
 * Filing a ticket — asking for help, reporting something.
 *
 * One way in for every kind. Whether a kind can be filed from where the reader
 * is, or only written to by email, or neither, is the server's one answer per
 * kind; nothing here reasons about bindings or entitlements.
 */

import { useQuery } from "@tanstack/react-query";

import type {
  FiledTicketDetailRead,
  FiledTicketList,
  ModerationTicketCreate,
  SupportTicketCreate,
  TaskCaseRead,
  TicketAccepted,
  TicketAvailability,
} from "@/api/generated/initiativeAPI.schemas";
import { getReadTaskCaseQueryKey, readTaskCase } from "@/api/generated/tasks/tasks";
import {
  fileTicket,
  getListFiledTicketsQueryKey,
  getReadFiledTicketQueryKey,
  getReadTicketAvailabilityQueryKey,
  listFiledTickets,
  readFiledTicket,
  readTicketAvailability,
  replyToFiledTicket,
} from "@/api/generated/tickets/tickets";
import { invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useApiMutation } from "@/hooks/useApiMutation";
import { docsUrl } from "@/lib/links";
import { queryClient } from "@/lib/queryClient";
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
      mutationFn: (body) => fileTicket(body),
      // A filing with somebody to answer it joins the reader's own tickets.
      invalidate: () => invalidate(q.filedTickets()),
    },
    options
  );

/** The tickets the reader filed, most recently moved first. */
export const useFiledTickets = (options?: QueryOpts<FiledTicketList>) =>
  useQuery<FiledTicketList>({
    queryKey: getListFiledTicketsQueryKey(),
    queryFn: () => listFiledTickets(),
    ...options,
  });

/** One ticket the reader filed, with what has been said to them about it. */
export const useFiledTicket = (taskId: number, options?: QueryOpts<FiledTicketDetailRead>) =>
  useQuery<FiledTicketDetailRead>({
    queryKey: getReadFiledTicketQueryKey(taskId),
    queryFn: () => readFiledTicket(taskId),
    ...options,
  });

/** Answer on a ticket the reader filed. The answer comes back as the ticket. */
export const useReplyToTicket = (
  taskId: number,
  options?: MutationOpts<FiledTicketDetailRead, string>
) =>
  useApiMutation<FiledTicketDetailRead, string>(
    {
      mutationFn: (body) => replyToFiledTicket(taskId, { body }),
      invalidate: (ticket) => {
        queryClient.setQueryData(getReadFiledTicketQueryKey(taskId), ticket);
        return invalidate(q.filedTickets());
      },
      errorKey: "intake:tickets.replyError",
    },
    options
  );

/** The case behind a task in the active community, for the people working it.
 *  A task no stream opened answers 404, which is the usual answer. */
export const useTaskCase = (taskId: number) => {
  const communityId = useActiveCommunityId();
  return useQuery<TaskCaseRead>({
    queryKey: getReadTaskCaseQueryKey(communityId, taskId),
    queryFn: () => readTaskCase(communityId, taskId),
    enabled: Number.isFinite(taskId),
    // Most tasks are not cases: a 404 is the usual answer, not a failure.
    retry: false,
  });
};

/** Read the case behind ``taskId`` again: its conversation moved. */
export const refreshTaskCase = (taskId: number, communityId?: number) =>
  queryClient.invalidateQueries({
    predicate: (query) => {
      const [path] = query.queryKey as [unknown];
      return (
        typeof path === "string" &&
        (communityId == null
          ? path.endsWith(`/tasks/${taskId}/case`)
          : path === getReadTaskCaseQueryKey(communityId, taskId)[0])
      );
    },
  });

/** Whether the reader has filed anything worth a page of its own. */
export const useHasFiledTickets = () => {
  const { data } = useFiledTickets({ staleTime: 5 * 60 * 1000 });
  return (data?.items.length ?? 0) > 0;
};

const FILED_TICKET = /^\/api\/v1\/me\/tickets\/\d+$/;

/**
 * Read the reader's tickets again: the list, and any one of them open on a
 * page. What the account socket's ticket frame asks for — it names nothing,
 * so everything of theirs is read again through the filer routes.
 */
export const refreshFiledTickets = () =>
  Promise.all([
    invalidate(q.filedTickets()),
    queryClient.invalidateQueries({
      predicate: (query) => {
        const [path] = query.queryKey as [unknown];
        return typeof path === "string" && FILED_TICKET.test(path);
      },
    }),
  ]);
