/**
 * Where a ceremony runs: the app's own credential manager on Android, the
 * browser everywhere else, and the browser again for a server the phone would
 * not let the app act for.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  platform: "android",
  getPasskey: vi.fn(),
  finishPasskeyStepUp: vi.fn(),
}));

vi.mock("@capacitor/core", () => ({
  Capacitor: {
    isNativePlatform: () => false,
    getPlatform: () => mocks.platform,
    isPluginAvailable: (name: string) => name === "Passkeys",
  },
}));

vi.mock("@capawesome/capacitor-passkeys", () => ({
  Passkeys: { getPasskey: (options: unknown) => mocks.getPasskey(options) },
}));

vi.mock("@/api/generated/auth/auth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/generated/auth/auth")>()),
  beginPasskeyStepUp: () => Promise.resolve({ options: { challenge: "c", rpId: "example.com" } }),
  finishPasskeyStepUp: (body: unknown) => mocks.finishPasskeyStepUp(body),
}));

import { setStoredServerUrl } from "@/lib/serverStorage";

import { appRunsPasskeys, PasskeyNeedsBrowserError, stepUpWithPasskey } from "./passkeys";

beforeEach(() => {
  mocks.platform = "android";
  localStorage.clear();
  setStoredServerUrl("https://one.example.com/api/v1");
});

describe("appRunsPasskeys", () => {
  it("is the Android app's, not a browser's or iOS's", () => {
    expect(appRunsPasskeys()).toBe(true);
    mocks.platform = "ios";
    expect(appRunsPasskeys()).toBe(false);
    mocks.platform = "web";
    expect(appRunsPasskeys()).toBe(false);
  });
});

describe("a ceremony in the app", () => {
  it("hands the server's options to the plugin and its answer back", async () => {
    mocks.getPasskey.mockResolvedValue({ id: "cred", rawId: "cred", type: "public-key" });
    mocks.finishPasskeyStepUp.mockResolvedValue({ access_token: "t" });

    await stepUpWithPasskey();

    expect(mocks.getPasskey).toHaveBeenCalledWith({ challenge: "c", rpId: "example.com" });
    expect(mocks.finishPasskeyStepUp).toHaveBeenCalledWith({
      credential: { id: "cred", rawId: "cred", type: "public-key" },
    });
  });

  it("sends a server the phone refused to the browser, and only that server", async () => {
    mocks.getPasskey.mockRejectedValue({ code: "DOMAIN_NOT_ASSOCIATED" });

    await expect(stepUpWithPasskey()).rejects.toBeInstanceOf(PasskeyNeedsBrowserError);
    expect(appRunsPasskeys()).toBe(false);

    setStoredServerUrl("https://two.example.com/api/v1");
    expect(appRunsPasskeys()).toBe(true);
  });

  it("gives a put-down prompt the browser's name for it", async () => {
    mocks.getPasskey.mockRejectedValue({ code: "CANCELED" });

    await expect(stepUpWithPasskey()).rejects.toMatchObject({ name: "NotAllowedError" });
    expect(appRunsPasskeys()).toBe(true);
  });
});
