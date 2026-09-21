import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import type { CookieConsentRead, UserRead } from "@/api/generated/initiativeAPI.schemas";
import { ConsentCategory, getConsentState, recordConsent } from "@/lib/consent";
import { removeItem, setItem } from "@/lib/storage";

const mocks = vi.hoisted(() => ({
  user: null as UserRead | null,
  put: vi.fn(),
}));

vi.mock("@/hooks/useAuth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useAuth")>()),
  useAuth: () => ({ user: mocks.user }),
}));

vi.mock("@/api/generated/users/users", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/generated/users/users")>()),
  setCookieConsentApiV1UsersMeCookieConsentPut: (body: unknown) => mocks.put(body),
}));

import { useConsentSync } from "./useConsentSync";

const accountAnswer = (
  granted: string[],
  decidedAt = "2026-09-20T10:00:00.000Z"
): CookieConsentRead => ({ granted, version: 1, decided_at: decidedAt });

const signedInWith = (consent: CookieConsentRead | null) => {
  mocks.user = { ...buildUser(), cookie_consent: consent } as UserRead;
};

/** An answer given in this browser and not yet sent anywhere. */
const answeredHere = (granted: ConsentCategory[]) => recordConsent(granted);

/** An answer this browser took from the account and is in step with. */
const inStepWith = (granted: string[], decidedAt: string) =>
  setItem(
    "cookie-consent",
    JSON.stringify({ version: 1, decidedAt, granted, syncedAt: decidedAt })
  );

describe("useConsentSync", () => {
  beforeEach(() => {
    removeItem("cookie-consent");
    mocks.user = null;
    mocks.put = vi.fn().mockResolvedValue(accountAnswer([], "2026-09-20T12:00:00.000Z"));
  });

  it("does nothing for somebody who has not signed in", () => {
    answeredHere([ConsentCategory.analytics]);

    renderHook(() => useConsentSync());

    expect(mocks.put).not.toHaveBeenCalled();
  });

  it("spares a browser the question where the account has already answered", async () => {
    signedInWith(accountAnswer(["analytics"]));

    renderHook(() => useConsentSync());

    await waitFor(() => {
      expect(getConsentState().record?.granted).toEqual(["analytics"]);
    });
    expect(mocks.put).not.toHaveBeenCalled();
  });

  it("tells the account about an answer given before signing in", async () => {
    answeredHere([ConsentCategory.marketing]);
    signedInWith(null);

    renderHook(() => useConsentSync());

    await waitFor(() => {
      expect(mocks.put).toHaveBeenCalledWith({ granted: ["marketing"], version: 1 });
    });
  });

  it("does not let a stale account answer overwrite one just given here", async () => {
    // Answered in this browser, unsent; the account holds something else.
    answeredHere([]);
    signedInWith(accountAnswer(["analytics", "marketing"]));

    renderHook(() => useConsentSync());

    await waitFor(() => {
      expect(mocks.put).toHaveBeenCalledWith({ granted: [], version: 1 });
    });
    expect(getConsentState().record?.granted).toEqual([]);
  });

  it("carries a change made on another device back to this one", async () => {
    inStepWith(["analytics", "marketing"], "2026-09-20T10:00:00.000Z");
    // Same account, answered again elsewhere since.
    signedInWith(accountAnswer(["analytics"], "2026-09-20T11:00:00.000Z"));

    renderHook(() => useConsentSync());

    await waitFor(() => {
      expect(getConsentState().record?.granted).toEqual(["analytics"]);
    });
    expect(mocks.put).not.toHaveBeenCalled();
  });

  it("leaves a browser alone when it is already in step", () => {
    inStepWith(["analytics"], "2026-09-20T10:00:00.000Z");
    signedInWith(accountAnswer(["analytics"], "2026-09-20T10:00:00.000Z"));

    renderHook(() => useConsentSync());

    expect(mocks.put).not.toHaveBeenCalled();
    expect(getConsentState().record?.granted).toEqual(["analytics"]);
  });

  it("ignores an account answer to an older question", async () => {
    // The categories changed since; that answer was to a different question,
    // so this browser asks rather than adopting it.
    signedInWith({ granted: ["analytics"], version: 0, decided_at: "2026-09-20T10:00:00.000Z" });

    renderHook(() => useConsentSync());

    await waitFor(() => expect(mocks.put).not.toHaveBeenCalled());
    expect(getConsentState().record).toBeNull();
  });

  it("keeps this browser's answer in force when the account cannot be told", async () => {
    mocks.put = vi.fn().mockRejectedValue(new Error("offline"));
    answeredHere([ConsentCategory.analytics]);
    signedInWith(null);

    renderHook(() => useConsentSync());

    await waitFor(() => expect(mocks.put).toHaveBeenCalled());
    expect(getConsentState().record?.granted).toEqual(["analytics"]);
  });
});
