/**
 * Which answer about who is signed in wins.
 *
 * Reading the account is not instant and several reads can be in the air at
 * once — two signals arriving together, a signal beside the catch-up a
 * reconnect does. Responses arrive in whatever order the network gives them,
 * so "last to arrive" is not "last asked for". These pin the orderings that
 * matter, including the one where a slow read must not undo a sign-out.
 */
import { act, render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";

const get = vi.fn();
const post = vi.fn();

vi.mock("@/api/client", () => ({
  apiClient: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
    defaults: { baseURL: "" },
  },
  AUTH_UNAUTHORIZED_EVENT: "initiative:auth:unauthorized",
  AUTH_STEP_UP_EVENT: "initiative:auth:step-up",
  setApiBaseUrl: vi.fn(),
  setHasActiveSession: vi.fn(),
  setAuthToken: vi.fn(),
  getAuthToken: () => null,
  clearUploadToken: vi.fn(),
}));

vi.mock("@/lib/storage", () => ({
  getItem: () => null,
  setItem: vi.fn(),
  removeItem: vi.fn(),
}));

const forgetMessages = vi.fn();
vi.mock("@/crypto/messaging", () => ({
  forgetMessagesOnThisDevice: () => forgetMessages(),
}));

import { AuthProvider, useAuth } from "./useAuth";

/** Resolvable on demand, so response order can be chosen rather than hoped for. */
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
};

let auth: ReturnType<typeof useAuth>;

const Probe = () => {
  auth = useAuth();
  return null;
};

const renderAuth = () =>
  render(
    <AuthProvider>
      <Probe />
    </AuthProvider>
  );

describe("useAuth identity ordering", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset().mockResolvedValue({ data: {} });
  });

  it("keeps the newer account when an older read finishes last", async () => {
    // Boot, so the provider settles before the interesting part.
    get.mockResolvedValueOnce({ data: buildUser({ full_name: "At boot" }) });
    renderAuth();
    await waitFor(() => expect(auth.user?.full_name).toBe("At boot"));

    const older = deferred<{ data: unknown }>();
    const newer = deferred<{ data: unknown }>();
    get.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);

    let firstDone: Promise<void>;
    let secondDone: Promise<void>;
    act(() => {
      firstDone = auth.refreshUser();
      secondDone = auth.refreshUser();
    });

    // The newer request answers first; the older one straggles in behind it.
    await act(async () => {
      newer.resolve({ data: buildUser({ full_name: "Newer" }) });
      await secondDone;
      older.resolve({ data: buildUser({ full_name: "Older" }) });
      await firstDone;
    });

    expect(auth.user?.full_name).toBe("Newer");
  });

  it("keeps the newer account when the older read finishes first", async () => {
    // The other order, and the one a turn-counter gets wrong: the older read
    // lands first, and must not make the newer answer look stale.
    get.mockResolvedValueOnce({ data: buildUser({ full_name: "At boot" }) });
    renderAuth();
    await waitFor(() => expect(auth.user?.full_name).toBe("At boot"));

    const older = deferred<{ data: unknown }>();
    const newer = deferred<{ data: unknown }>();
    get.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);

    let firstDone: Promise<void>;
    let secondDone: Promise<void>;
    act(() => {
      firstDone = auth.refreshUser();
      secondDone = auth.refreshUser();
    });

    await act(async () => {
      older.resolve({ data: buildUser({ full_name: "Older" }) });
      await firstDone;
      newer.resolve({ data: buildUser({ full_name: "Newer" }) });
      await secondDone;
    });

    expect(auth.user?.full_name).toBe("Newer");
  });

  it("hands back the same account object when the re-read says nothing new", async () => {
    // The account is re-read whenever the server says it might have moved, and
    // most of those answers are identical. A fresh object for one of them
    // re-runs every effect keyed on the user — including the socket that asked
    // for the read, which would then ask again, forever.
    const account = buildUser({ full_name: "Unchanged" });
    get.mockResolvedValue({ data: account });
    renderAuth();
    await waitFor(() => expect(auth.user?.full_name).toBe("Unchanged"));
    const before = auth.user;

    await act(async () => {
      await auth.refreshUser();
    });

    expect(auth.user).toBe(before);
  });

  it("still swaps the object when the account actually moved", async () => {
    get.mockResolvedValueOnce({ data: buildUser({ full_name: "Before" }) });
    renderAuth();
    await waitFor(() => expect(auth.user?.full_name).toBe("Before"));
    const before = auth.user;

    get.mockResolvedValueOnce({ data: buildUser({ full_name: "After" }) });
    await act(async () => {
      await auth.refreshUser();
    });

    expect(auth.user).not.toBe(before);
    expect(auth.user?.full_name).toBe("After");
  });

  it("does not let a read in flight undo a sign-out", async () => {
    get.mockResolvedValueOnce({ data: buildUser({ full_name: "Signed in" }) });
    renderAuth();
    await waitFor(() => expect(auth.user).not.toBeNull());

    const slow = deferred<{ data: unknown }>();
    get.mockReturnValueOnce(slow.promise);

    let reading: Promise<void>;
    act(() => {
      reading = auth.refreshUser();
    });
    await act(async () => {
      await auth.logout();
    });
    expect(auth.user).toBeNull();

    // The read it never got to finish comes back after the sign-out.
    await act(async () => {
      slow.resolve({ data: buildUser({ full_name: "Signed in" }) });
      await reading;
    });

    expect(auth.user).toBeNull();
  });

  it("takes the messages on this device with it when signing out", async () => {
    // A decrypted conversation must not outlive the session that read it, and
    // the sign-out itself must not depend on that going through.
    forgetMessages.mockRejectedValueOnce(new Error("offline"));
    get.mockResolvedValueOnce({ data: buildUser({ full_name: "Signed in" }) });
    renderAuth();
    await waitFor(() => expect(auth.user).not.toBeNull());

    await act(async () => {
      await auth.logout();
    });

    expect(forgetMessages).toHaveBeenCalled();
    expect(auth.user).toBeNull();
  });

  it("applies a read that nothing overtook", async () => {
    get.mockResolvedValueOnce({ data: buildUser({ full_name: "At boot" }) });
    renderAuth();
    await waitFor(() => expect(auth.user?.full_name).toBe("At boot"));

    get.mockResolvedValueOnce({ data: buildUser({ full_name: "Fresh" }) });
    await act(async () => {
      await auth.refreshUser();
    });

    expect(auth.user?.full_name).toBe("Fresh");
  });
});
