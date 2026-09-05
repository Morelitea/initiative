/**
 * My Messages, as React sees it.
 *
 * The ratchet has to advance in a defined order, so the work itself lives in
 * `@/crypto/messaging` and this file only schedules it. Two things are worth
 * knowing about the shape:
 *
 * * **The local log is the source of truth for a thread.** The server deletes a
 *   message the moment it is collected, so React Query caches what this device
 *   decrypted, not what an endpoint would return.
 * * **Collection is triggered by the socket, not a poll.** A `dm` frame carries
 *   nothing; it says there is something to fetch.
 */

import { skipToken, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import {
  createConversationApiV1MeDmConversationsPost as createConversation,
  listConversationsApiV1MeDmConversationsGet as listConversations,
} from "@/api/generated/direct-messages/direct-messages";
import type { StoredMessage } from "@/crypto/messaging";
import {
  collect,
  ensureDevice,
  markRead,
  messageLog,
  registeredDevice,
  sendText,
  unreadIn,
} from "@/crypto/messaging";
import { useDmSettings, usePendingContactRequests } from "@/hooks/useDirectMessages";

export const messageKeys = {
  conversations: ["dm", "conversations"] as const,
  // Deliberately outside the `["dm", …]` family a socket frame invalidates:
  // registering is a once-per-browser answer, and re-asking it on every frame
  // would cost a round trip to be told the same device id again.
  device: ["dm-device"] as const,
  // A separate key from `device`, because it is a different question with a
  // different answer: *is* there one, versus make sure there is. Sharing one
  // would let whichever asked first decide what the other one got back.
  registered: ["dm-device-registered"] as const,
  inbox: ["dm", "inbox"] as const,
  thread: (conversationId: string) => ["dm", "thread", conversationId] as const,
  // Keyed on the conversations it counts, so a new one is a new question
  // rather than a stale answer waiting for something to invalidate it.
  unread: (conversationIds: string[]) => ["dm", "unread", conversationIds.join(",")] as const,
};

/** Register this browser's device, once, before anything else can work. */
export function useDmDevice() {
  return useQuery({
    queryKey: messageKeys.device,
    queryFn: async () => {
      try {
        return await ensureDevice();
      } catch (error) {
        // The page can only say that it failed. What failed is worth having
        // when somebody has to work out why.
        console.error("[messages] this device could not be set up", error);
        throw error;
      }
    },
    staleTime: Number.POSITIVE_INFINITY,
    retry: false,
  });
}

export function useConversations() {
  return useQuery({
    queryKey: messageKeys.conversations,
    queryFn: () => listConversations(),
    staleTime: 30_000,
  });
}

/** One thread, read out of this device's own store. */
export function useThread(conversationId: string | undefined) {
  return useQuery({
    queryKey: messageKeys.thread(conversationId ?? ""),
    queryFn: (): Promise<StoredMessage[]> =>
      conversationId ? messageLog.get(conversationId) : Promise.resolve([]),
    enabled: Boolean(conversationId),
    staleTime: 0,
  });
}

export function useSendMessage(conversationId: string, otherUserId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: string) => sendText(conversationId, otherUserId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: messageKeys.thread(conversationId),
      });
    },
  });
}

export function useStartConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (userId: number) => createConversation({ user_id: userId }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: messageKeys.conversations });
    },
  });
}

/**
 * Fetch and decrypt whatever is waiting, then refresh the threads it touched.
 *
 * This is a *query*, not an effect, and that is what makes the socket work: a
 * `dm` frame invalidates everything under `["dm"]`, which includes this key, so
 * the frame re-runs the collection. An effect would have needed its own
 * subscription to the same signal.
 *
 * It never invalidates its own key — only the threads and the conversation
 * list — so a collection cannot re-trigger itself.
 */
export function useCollectMessages(enabled: boolean) {
  const queryClient = useQueryClient();
  const receipts = useSendsReceipts();

  return useQuery({
    queryKey: messageKeys.inbox,
    queryFn: async () => {
      const touched = await collect({ receipts });
      for (const conversationId of touched) {
        void queryClient.invalidateQueries({
          queryKey: messageKeys.thread(conversationId),
        });
      }
      if (touched.length > 0) {
        void queryClient.invalidateQueries({ queryKey: messageKeys.conversations });
        void queryClient.invalidateQueries({ queryKey: ["dm", "unread"] });
      }
      return touched;
    },
    enabled,
    // A collection that fails leaves the queue intact; the next frame or the
    // next visit tries again.
    retry: false,
    staleTime: 0,
    gcTime: 0,
  });
}

/**
 * Collect anywhere in the app, but only for a browser already set up.
 *
 * What makes a mark on My Messages mean anything is that the mail is fetched
 * while you are somewhere else — otherwise nothing new is ever noticed until
 * you go and look, which is the one thing the mark is there to save you. It
 * deliberately does *not* register a device: setting one up is what visiting
 * the page does, and a browser that never has stays as it was.
 */
export function useCollectMessagesWhereRegistered() {
  const registered = useQuery({
    queryKey: messageKeys.registered,
    queryFn: () => registeredDevice().then((id) => id ?? null),
    staleTime: Number.POSITIVE_INFINITY,
    retry: false,
  });
  // Watching the answer to the *other* question rather than fetching anything:
  // this browser may be set up while the app is running, by the one page that
  // does it, and collection should start then rather than on the next load.
  const device = useQuery({ queryKey: messageKeys.device, queryFn: skipToken });
  return useCollectMessages(Boolean(registered.data ?? device.data));
}

/**
 * How many things are waiting in My Messages, as one number.
 *
 * Two kinds, and they mean the same thing to the person seeing the mark:
 * something is there that you have not dealt with. Counted in one place because
 * more than one surface draws it -- the sidebar item, and the logo above the
 * whole rail, which is the only mark visible from inside a community.
 */
export function useMessagesWaiting(): number {
  const pending = usePendingContactRequests();
  const conversations = useConversations();
  const unread = useUnreadMessages((conversations.data?.conversations ?? []).map((row) => row.id));
  const unreadTotal = [...(unread.data?.values() ?? [])].reduce((total, count) => total + count, 0);
  return pending + unreadTotal;
}

/**
 * How many messages are waiting in each conversation, on this device.
 *
 * Read from the local log, because that is where a thread is — the server
 * deletes a message once it has been collected and could not answer this even
 * if it were asked.
 */
export function useUnreadMessages(conversationIds: string[]) {
  return useQuery({
    queryKey: messageKeys.unread(conversationIds),
    queryFn: async () => {
      const counts = new Map<string, number>();
      for (const id of conversationIds) {
        counts.set(id, await unreadIn(id));
      }
      return counts;
    },
    enabled: conversationIds.length > 0,
    staleTime: 0,
  });
}

/** Mark a thread as looked at, whenever what is in it changes. */
export function useMarkThreadRead(
  conversationId: string,
  messageCount: number,
  otherUserId: number
) {
  const queryClient = useQueryClient();
  const receipts = useSendsReceipts();
  useEffect(() => {
    void markRead(conversationId, { otherUserId, receipts }).then(() =>
      queryClient.invalidateQueries({ queryKey: ["dm", "unread"] })
    );
  }, [conversationId, messageCount, otherUserId, receipts, queryClient]);
}

/**
 * Whether this account tells a sender their message arrived and was read.
 *
 * Read where the receipts are sent rather than passed down from a page: the
 * collection loop runs whether or not anything is on screen, and the switch has
 * to reach it there too.
 *
 * Quiet until the answer is actually in. Assuming the friendlier default while
 * the setting is on its way would report on behalf of somebody who had turned
 * reporting off, on every load, and nothing can take that back. A receipt that
 * was never sent costs a tick.
 */
export function useSendsReceipts(): boolean {
  const { data, isSuccess } = useDmSettings();
  return isSuccess && (data?.send_receipts ?? true);
}
