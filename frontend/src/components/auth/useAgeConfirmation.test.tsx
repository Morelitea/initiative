/**
 * Answering the age question changes what the rest of the page may show.
 *
 * The answer is a gate: before it, this account can reach nobody and nobody
 * can reach it; after it, it has a messaging policy, a roster and requests.
 * Anything still holding the old answer would leave the surface that asked
 * looking exactly as it did before it was answered.
 */

import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const post = vi.fn();
const refreshUser = vi.fn();
const invalidations = vi.hoisted(() => vi.fn());

vi.mock("@/api/client", () => ({
  apiClient: { post: (...args: unknown[]) => post(...args) },
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ refreshUser }),
}));

// One entry point now, so the assertion is on WHAT was named rather than on
// which of three helpers ran. `q` stays real: the specs are the comparison.
vi.mock("@/api/query-keys", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/query-keys")>()),
  invalidate: (...specs: unknown[]) => invalidations(...specs),
}));

import { q } from "@/api/query-keys";

import { useAgeConfirmation } from "./useAgeConfirmation";

beforeEach(() => {
  vi.clearAllMocks();
  post.mockResolvedValue({ data: {} });
  refreshUser.mockResolvedValue(undefined);
});

describe("confirming an age", () => {
  it("drops everything that was answered under the old one", async () => {
    const { result } = renderHook(() => useAgeConfirmation());

    result.current.setBirthdate("1990-01-01");
    await waitFor(() => expect(result.current.birthdate).toBe("1990-01-01"));
    await result.current.confirm();

    expect(post).toHaveBeenCalledWith("/users/me/age-confirmation", {
      birthdate: "1990-01-01",
    });
    expect(refreshUser).toHaveBeenCalled();
    expect(invalidations).toHaveBeenCalledWith(q.dmSettings(), q.contacts(), q.contactGrants());
  });

  it("keeps what is on screen when the answer was refused", async () => {
    // A refusal changes nothing, and re-reading everything would only make the
    // page flicker on its way back to what it already said.
    post.mockRejectedValue(new Error("too young"));
    const { result } = renderHook(() => useAgeConfirmation());

    result.current.setBirthdate("2020-01-01");
    await waitFor(() => expect(result.current.birthdate).toBe("2020-01-01"));
    await result.current.confirm();

    expect(invalidations).not.toHaveBeenCalled();
  });
});
