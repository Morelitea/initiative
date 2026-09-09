/**
 * Opening the app with no signal.
 *
 * The distinction these pin down is the whole safety property of offline
 * reading: a server that answered — with anything, a 401 included — ends the
 * session, and only a request that got no answer at all falls back to the
 * stored snapshot. See `history/offline-reading-design.md`.
 */
import { render, waitFor } from "@testing-library/react";
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

vi.mock("@/crypto/messaging", () => ({
  forgetMessagesOnThisDevice: vi.fn(),
}));

const clearWhiteboards = vi.fn();
vi.mock("@/components/documents/whiteboardSceneCache", () => ({
  clearAllWhiteboardSceneCaches: () => clearWhiteboards(),
}));

const purgeOfflineCache = vi.fn();
const setOfflineWritesAllowed = vi.fn();

vi.mock("@/lib/offlineCache", () => ({
  isOfflineCacheEnabled: () => true,
  purgeOfflineCache: () => purgeOfflineCache(),
  restoredIdentityMismatch: () => false,
  setOfflineWritesAllowed: (allowed: boolean) => setOfflineWritesAllowed(allowed),
}));

let snapshot: ReturnType<typeof buildUser> | null = null;
const clearOfflineSession = vi.fn(() => {
  snapshot = null;
});
const saveOfflineSession = vi.fn();

vi.mock("@/lib/offlineSession", () => ({
  currentServerKey: () => "https://initiative.example",
  clearOfflineSession: () => clearOfflineSession(),
  saveOfflineSession: (...args: unknown[]) => saveOfflineSession(...args),
  readOfflineSession: () => snapshot,
  isNoAnswerError: (error: unknown) =>
    typeof error === "object" && error !== null && !("response" in error),
}));

import { AuthProvider, useAuth } from "./useAuth";

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

beforeEach(() => {
  vi.clearAllMocks();
  snapshot = null;
  get.mockReset();
});

describe("bootstrapping with no answer from the server", () => {
  it("keeps the last-known user, marked unverified", async () => {
    snapshot = buildUser({ full_name: "Alice" });
    const stored = snapshot;
    get.mockRejectedValue({ request: {}, message: "Network Error" });

    renderAuth();

    await waitFor(() => expect(auth.loading).toBe(false));
    expect(auth.user?.id).toBe(stored.id);
    expect(auth.sessionUnverified).toBe(true);
  });

  it("writes nothing to disk while the session is unverified", async () => {
    snapshot = buildUser();
    get.mockRejectedValue({ request: {} });

    renderAuth();

    await waitFor(() => expect(auth.loading).toBe(false));
    // The restore path must not go through the remembering path: re-saving
    // would push the snapshot's expiry out on every offline launch.
    expect(saveOfflineSession).not.toHaveBeenCalled();
    expect(setOfflineWritesAllowed).not.toHaveBeenCalledWith(true);
  });

  it("signs out anyway when there is no snapshot to fall back to", async () => {
    snapshot = null;
    get.mockRejectedValue({ request: {} });

    renderAuth();

    await waitFor(() => expect(auth.loading).toBe(false));
    expect(auth.user).toBeNull();
    expect(auth.sessionUnverified).toBe(false);
  });
});

describe("bootstrapping when the server does answer", () => {
  it("signs out on a rejection, even with a snapshot sitting there", async () => {
    snapshot = buildUser();
    get.mockRejectedValue({ request: {}, response: { status: 401 } });

    renderAuth();

    await waitFor(() => expect(auth.loading).toBe(false));
    expect(auth.user).toBeNull();
    expect(auth.sessionUnverified).toBe(false);
    expect(clearOfflineSession).toHaveBeenCalled();
    expect(setOfflineWritesAllowed).toHaveBeenCalledWith(false);
    // Session content goes however the session ended — a rejected bootstrap is
    // an ending too, not only a deliberate sign-out.
    expect(clearWhiteboards).toHaveBeenCalled();
  });

  it("keeps whiteboards on the device when nothing answered", async () => {
    snapshot = buildUser();
    get.mockRejectedValue({ request: {} });

    renderAuth();

    await waitFor(() => expect(auth.sessionUnverified).toBe(true));
    // No signal is not the end of a session, and the unsaved work is the whole
    // reason those scenes are held.
    expect(clearWhiteboards).not.toHaveBeenCalled();
  });

  it("records the confirmed identity and opens the cache for writing", async () => {
    const user = buildUser();
    get.mockResolvedValue({ data: user });

    renderAuth();

    await waitFor(() => expect(auth.user?.id).toBe(user.id));
    expect(auth.sessionUnverified).toBe(false);
    expect(saveOfflineSession).toHaveBeenCalledWith(user, "https://initiative.example");
    expect(setOfflineWritesAllowed).toHaveBeenCalledWith(true);
  });
});
