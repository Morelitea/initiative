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
  useReadDmPermissionApiV1UsersUserIdDmPermissionGet,
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
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

/** Everything a change to one of these lists can affect. */
export const refreshContactLists = () => {
  void invalidateContactGrants();
  void invalidateIgnoredAccounts();
  void invalidateDmSettings();
};

/**
 * What every one of these mutations does on the way out.
 *
 * `onSettled` refreshes all three lists; `onError` says so out loud. These are
 * ordinary conflicts rather than bugs — accepting a request that was withdrawn
 * a moment ago, removing a connection somebody else already removed — and the
 * lists refresh either way, so without a word the row simply changes under the
 * reader with nothing to explain it. There is no global mutation error handler
 * to fall back on, so it lives here rather than at each call site.
 */
const reportAndRefresh = {
  mutation: {
    onSettled: refreshContactLists,
    onError: (error: unknown) =>
      toast.error(getErrorMessage(error, "errors:CONTACT_GRANT_CANNOT_REACH")),
  },
};

/**
 * The same, minus the toast: the connect-by-handle field reports next to the
 * input, where the mistake usually is.
 */
const refreshOnly = { mutation: { onSettled: refreshContactLists } };

// ── Reads ───────────────────────────────────────────────────────────────────

export const useDmSettings = () => useReadDmSettingsApiV1MeDmSettingsGet();

/**
 * What the reader may do about one account: ``open``, ``may_request`` or
 * ``denied``.
 *
 * One value with nothing beside it — the server collapses every refusal into
 * ``denied`` on purpose, so a menu built from this cannot tell the reasons
 * apart either.
 */
export const useDmPermission = (userId: number | undefined) =>
  useReadDmPermissionApiV1UsersUserIdDmPermissionGet(userId as number, {
    query: { enabled: typeof userId === "number" },
  });
export const useConnections = () => useListConnectionsApiV1MeConnectionsGet();
export const useMessageRequests = () => useListMessageRequestsApiV1MeMessageRequestsGet();
export const useIgnoredAccounts = () => useListIgnoredAccountsApiV1MeIgnoredGet();

// ── Writes ──────────────────────────────────────────────────────────────────

export const useUpdateDmSettings = () =>
  useUpdateDmSettingsApiV1MeDmSettingsPatch(reportAndRefresh);

export const useRequestConnection = () => useRequestConnectionApiV1MeConnectionsPost(refreshOnly);
export const useAcceptConnection = () =>
  useAcceptConnectionApiV1MeConnectionsUserIdAcceptPost(reportAndRefresh);
export const useRemoveConnection = () =>
  useRemoveConnectionApiV1MeConnectionsUserIdDelete(reportAndRefresh);

export const useRequestMessage = () =>
  useRequestMessageApiV1MeMessageRequestsPost(reportAndRefresh);
export const useAcceptMessageRequest = () =>
  useAcceptMessageRequestApiV1MeMessageRequestsUserIdAcceptPost(reportAndRefresh);
export const useRemoveMessageRequest = () =>
  useRemoveMessageRequestApiV1MeMessageRequestsUserIdDelete(reportAndRefresh);

export const useIgnoreAccount = () => useIgnoreAccountApiV1MeIgnoredUserIdPut(reportAndRefresh);
export const useStopIgnoring = () =>
  useStopIgnoringAccountApiV1MeIgnoredUserIdDelete(reportAndRefresh);

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

/**
 * How many people have asked to message this account and are still waiting.
 *
 * Message requests only. A connection is a separate agreement between two
 * accounts — made, answered and unmade on My Contacts — and counting it here
 * would put a mark about connections on a page about conversations.
 */
export const usePendingMessageRequests = (): number => {
  const { data } = useMessageRequests();
  return data?.incoming?.length ?? 0;
};

/** Whether this account has answered the age question, which gates everything. */
export const useCanUseDirectMessages = (): boolean => {
  const { data } = useDmSettings();
  return Boolean(data?.age_confirmed_at);
};

/** One place for "these lists moved", for callers outside a mutation. */
export const useRefreshContacts = () => useCallback(refreshContactLists, []);
