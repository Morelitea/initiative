/**
 * Who may reach this account, and who it has agreed something with.
 *
 * Three lists that move together — accepting a connection opens a channel,
 * leaving a community closes one — so every mutation here invalidates all of
 * them, the same set the `contacts` realtime frame invalidates. A tab that
 * acted and a tab that only watched end up saying the same thing.
 */

import { useCallback } from "react";

import {
  useAcceptConnectionApiV1MeConnectionsUserIdAcceptPost,
  useAcceptMessageRequestApiV1MeMessageRequestsUserIdAcceptPost,
  useIgnoreAccountApiV1MeIgnoredUserIdPut,
  useListConnectionsApiV1MeConnectionsGet,
  useListIgnoredAccountsApiV1MeIgnoredGet,
  useListMessageRequestsApiV1MeMessageRequestsGet,
  useReadDmSettingsApiV1MeDmSettingsGet,
  useRemoveConnectionApiV1MeConnectionsUserIdDelete,
  useRemoveMessageRequestApiV1MeMessageRequestsUserIdDelete,
  useRequestConnectionApiV1MeConnectionsPost,
  useRequestMessageApiV1MeMessageRequestsPost,
  useStopIgnoringAccountApiV1MeIgnoredUserIdDelete,
  useUpdateDmSettingsApiV1MeDmSettingsPatch,
} from "@/api/generated/direct-messages/direct-messages";
import {
  invalidateContactGrants,
  invalidateDmSettings,
  invalidateIgnoredAccounts,
} from "@/api/query-keys";

/** Everything a change to one of these lists can affect. */
export const refreshContactLists = () => {
  void invalidateContactGrants();
  void invalidateIgnoredAccounts();
  void invalidateDmSettings();
};

const onSettled = { mutation: { onSettled: refreshContactLists } };

// ── Reads ───────────────────────────────────────────────────────────────────

export const useDmSettings = () => useReadDmSettingsApiV1MeDmSettingsGet();
export const useConnections = () => useListConnectionsApiV1MeConnectionsGet();
export const useMessageRequests = () => useListMessageRequestsApiV1MeMessageRequestsGet();
export const useIgnoredAccounts = () => useListIgnoredAccountsApiV1MeIgnoredGet();

// ── Writes ──────────────────────────────────────────────────────────────────

export const useUpdateDmSettings = () => useUpdateDmSettingsApiV1MeDmSettingsPatch(onSettled);

export const useRequestConnection = () => useRequestConnectionApiV1MeConnectionsPost(onSettled);
export const useAcceptConnection = () =>
  useAcceptConnectionApiV1MeConnectionsUserIdAcceptPost(onSettled);
export const useRemoveConnection = () =>
  useRemoveConnectionApiV1MeConnectionsUserIdDelete(onSettled);

export const useRequestMessage = () => useRequestMessageApiV1MeMessageRequestsPost(onSettled);
export const useAcceptMessageRequest = () =>
  useAcceptMessageRequestApiV1MeMessageRequestsUserIdAcceptPost(onSettled);
export const useRemoveMessageRequest = () =>
  useRemoveMessageRequestApiV1MeMessageRequestsUserIdDelete(onSettled);

export const useIgnoreAccount = () => useIgnoreAccountApiV1MeIgnoredUserIdPut(onSettled);
export const useStopIgnoring = () => useStopIgnoringAccountApiV1MeIgnoredUserIdDelete(onSettled);

/**
 * A handle typed as `name#1234`, split for the connection endpoint.
 *
 * A connection is addressed by handle whatever the target's policy: it is the
 * only shape that reaches an account on Private, which is never offered from a
 * roster or a picker.
 */
export const parseHandle = (raw: string): { username: string; discriminator: number } | null => {
  const match = /^@?([^#\s]{1,32})#(\d{1,4})$/.exec(raw.trim());
  if (!match) return null;
  return { username: match[1], discriminator: Number(match[2]) };
};

/** Whether this account has answered the age question, which gates everything. */
export const useCanUseDirectMessages = (): boolean => {
  const { data } = useDmSettings();
  return Boolean(data?.age_confirmed_at);
};

/** One place for "these lists moved", for callers outside a mutation. */
export const useRefreshContacts = () => useCallback(refreshContactLists, []);
