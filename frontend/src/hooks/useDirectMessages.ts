/**
 * Who may reach this account, and who it has agreed something with.
 *
 * Three lists that move together — accepting a connection opens a channel,
 * leaving a community closes one — so every mutation here invalidates all of
 * them, the same set the `contacts` realtime frame invalidates. A tab that
 * acted and a tab that only watched end up saying the same thing.
 */

import { useQueries } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";

import {
  readDmPermissionsApiV1MeDmPermissionsPost,
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
import type { DirectMessagePermissionsResponse } from "@/api/generated/initiativeAPI.schemas";
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
/** The most accounts one question may name, which the server enforces. */
const PERMISSION_LIMIT = 100;

/**
 * One object out of however many questions it took to answer for everybody.
 *
 * All of them or none: half an answer set is indistinguishable from a complete
 * one at the call site, and the two surfaces reading it disagree about what a
 * missing entry means -- the actions menu leaves an item out, the picker lets
 * the row be clicked. Publishing a partial map would make that disagreement
 * outlive the loading it belongs to. Absent, both behave the way they do
 * before any answer has arrived, which is what is true.
 */
const mergePermissions = (
  results: { data?: DirectMessagePermissionsResponse; isPending: boolean }[]
) => ({
  data:
    results.length > 0 && results.every((result) => result.data)
      ? {
          permissions: Object.assign(
            {},
            ...results.map((result) => result.data?.permissions ?? {})
          ) as DirectMessagePermissionsResponse["permissions"],
        }
      : undefined,
  isPending: results.some((result) => result.isPending),
});

/**
 * The same two answers, for a page of people at once.
 *
 * A surface listing members draws a control per row, and asking per row is a
 * request per row -- up to a hundred when a roster page is full. One question
 * about many subjects instead, cached under the ids it was asked about.
 *
 * A POST that reads: the subjects are a list rather than an address, so
 * `useQuery` rather than a mutation, with the ids in the key.
 *
 * Past the server's limit it asks again rather than answering for fewer people
 * than it was given. A caller that dropped the remainder would leave a control
 * built on a missing answer -- which reads as a refusal on one surface and as
 * consent on another -- so nobody handed to this goes unanswered.
 */
export const useDmPermissions = (userIds: number[]) => {
  const batches = useMemo(() => {
    const ids = [...new Set(userIds)].sort((a, b) => a - b);
    const out: number[][] = [];
    for (let at = 0; at < ids.length; at += PERMISSION_LIMIT) {
      out.push(ids.slice(at, at + PERMISSION_LIMIT));
    }
    return out;
  }, [userIds]);

  return useQueries({
    queries: batches.map((ids) => ({
      queryKey: ["dm", "permissions", ids],
      queryFn: () => readDmPermissionsApiV1MeDmPermissionsPost({ user_ids: ids }),
      staleTime: 30_000,
    })),
    combine: mergePermissions,
  });
};

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
 * How many people are waiting on an answer from this account.
 *
 * Both kinds, because both are answered in the same place: the requests
 * section of My Messages takes a connection request and a message request
 * alike, so a mark that counted only one of them would send somebody to a
 * screen with more on it than the mark admitted. Only incoming — an ask you
 * sent is waiting on them, not on you.
 */
export const usePendingContactRequests = (): number => {
  const messages = useMessageRequests();
  const connections = useConnections();
  return (messages.data?.incoming?.length ?? 0) + (connections.data?.incoming?.length ?? 0);
};

/** Whether this account has answered the age question, which gates everything. */
export const useCanUseDirectMessages = (): boolean => {
  const { data } = useDmSettings();
  return Boolean(data?.age_confirmed_at);
};

/** One place for "these lists moved", for callers outside a mutation. */
export const useRefreshContacts = () => useCallback(refreshContactLists, []);
