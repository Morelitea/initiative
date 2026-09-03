/**
 * What every contacts mutation does when it fails.
 *
 * These are ordinary conflicts, not bugs — accepting a request that was
 * withdrawn a moment ago, removing a connection somebody else already removed.
 * The lists refresh either way, so with nothing said the row just changes under
 * the reader. There is no global mutation error handler, so this is the only
 * thing standing between a failed action and silence.
 */
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn() }));

vi.mock("@/lib/chesterToast", () => ({
  toast: { error: mocks.error, success: mocks.success },
}));

const failing = { response: { status: 409, data: { detail: "CONTACT_GRANT_CANNOT_REACH" } } };

vi.mock("@/api/generated/direct-messages/direct-messages", () => {
  const make = (options?: { mutation?: { onError?: (e: unknown) => void } }) => ({
    mutate: () => options?.mutation?.onError?.(failing),
    isPending: false,
  });
  return {
    useAcceptConnectionApiV1MeConnectionsUserIdAcceptPost: make,
    useAcceptMessageRequestApiV1MeMessageRequestsUserIdAcceptPost: make,
    useIgnoreAccountApiV1MeIgnoredUserIdPut: make,
    useRemoveConnectionApiV1MeConnectionsUserIdDelete: make,
    useRemoveMessageRequestApiV1MeMessageRequestsUserIdDelete: make,
    useRequestConnectionApiV1MeConnectionsPost: make,
    useRequestMessageApiV1MeMessageRequestsPost: make,
    useStopIgnoringAccountApiV1MeIgnoredUserIdDelete: make,
    useUpdateDmSettingsApiV1MeDmSettingsPatch: make,
    useListConnectionsApiV1MeConnectionsGet: () => ({ data: undefined }),
    useListIgnoredAccountsApiV1MeIgnoredGet: () => ({ data: undefined }),
    useListMessageRequestsApiV1MeMessageRequestsGet: () => ({ data: undefined }),
    useReadDmSettingsApiV1MeDmSettingsGet: () => ({ data: undefined }),
  };
});

import {
  parseHandle,
  useAcceptConnection,
  useRemoveConnection,
  useRequestConnection,
  useStopIgnoring,
} from "./useDirectMessages";

describe("contacts mutations", () => {
  beforeEach(() => vi.clearAllMocks());

  it.each([
    ["accepting a connection", useAcceptConnection],
    ["removing a connection", useRemoveConnection],
    ["stopping ignoring", useStopIgnoring],
  ])("says so when %s fails", async (_label, useMutation) => {
    const { result } = renderHook(() => useMutation());

    result.current.mutate({ userId: 1 });

    await waitFor(() => expect(mocks.error).toHaveBeenCalledTimes(1));
  });

  it("leaves the connect-by-handle field to report its own", () => {
    const { result } = renderHook(() => useRequestConnection());

    result.current.mutate({ data: { username: "nobody", discriminator: 1 } });

    // Reported next to the input instead, where the mistake usually is.
    expect(mocks.error).not.toHaveBeenCalled();
  });
});

describe("parseHandle", () => {
  it.each([
    ["ada#1234", { username: "ada", discriminator: 1234 }],
    ["@ada#1234", { username: "ada", discriminator: 1234 }],
    ["  ada#0007  ", { username: "ada", discriminator: 7 }],
  ])("reads %s", (raw, expected) => {
    expect(parseHandle(raw)).toEqual(expected);
  });

  it.each(["ada", "ada#", "#1234", "ada#12345", "ada 1234"])("refuses %s", (raw) => {
    expect(parseHandle(raw)).toBeNull();
  });
});
