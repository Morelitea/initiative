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

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createConversationApiV1MeDmConversationsPost as createConversation,
  listConversationsApiV1MeDmConversationsGet as listConversations,
} from "@/api/generated/direct-messages/direct-messages";
import type { StoredMessage } from "@/crypto/messaging";
import { collect, ensureDevice, messageLog, sendText } from "@/crypto/messaging";

export const messageKeys = {
  conversations: ["dm", "conversations"] as const,
  // Deliberately outside the `["dm", …]` family a socket frame invalidates:
  // registering is a once-per-browser answer, and re-asking it on every frame
  // would cost a round trip to be told the same device id again.
  device: ["dm-device"] as const,
  inbox: ["dm", "inbox"] as const,
  thread: (conversationId: string) => ["dm", "thread", conversationId] as const,
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

  return useQuery({
    queryKey: messageKeys.inbox,
    queryFn: async () => {
      const touched = await collect();
      for (const conversationId of touched) {
        void queryClient.invalidateQueries({
          queryKey: messageKeys.thread(conversationId),
        });
      }
      if (touched.length > 0) {
        void queryClient.invalidateQueries({ queryKey: messageKeys.conversations });
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
