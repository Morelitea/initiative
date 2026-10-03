import { QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildCommunity, communityCan } from "@/__tests__/factories";
import { createTestQueryClient } from "@/__tests__/helpers/render";

const state = vi.hoisted(() => ({ billing: null as { url: string } | null }));
vi.mock("@/hooks/useAppConfig", () => ({ useAppConfig: () => ({ billing: state.billing }) }));
const read = vi.hoisted(() => vi.fn());
vi.mock("@/api/generated/communities/communities", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/generated/communities/communities")>()),
  readCommunityBillingSummary: read,
}));

import { useCommunityBillingSummary } from "./useCommunityBillingSummary";

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={createTestQueryClient()}>{children}</QueryClientProvider>
);

// The summary route is the seat's, and there is nothing to ask without a
// billing portal — so the hook asks in exactly that case.
describe("useCommunityBillingSummary", () => {
  beforeEach(() => {
    state.billing = { url: "https://billing.example.com" };
    read.mockReset();
    read.mockResolvedValue({ available: true, payment_failed: false });
  });

  it("asks for the seat of a hosted install", async () => {
    const community = buildCommunity({ id: 42, role: "superadmin" });
    const { result } = renderHook(() => useCommunityBillingSummary(community), { wrapper });
    await waitFor(() => expect(result.current.data?.available).toBe(true));
    expect(read).toHaveBeenCalledWith(42);
  });

  it("never asks for an ordinary admin", () => {
    const community = buildCommunity({ id: 42, role: "admin" });
    renderHook(() => useCommunityBillingSummary(community), { wrapper });
    expect(read).not.toHaveBeenCalled();
  });

  it("asks for support holding the seat with write access", async () => {
    const community = {
      ...buildCommunity({
        id: 42,
        role: "superadmin",
        can: communityCan("superadmin", { configure: true }),
      }),
      accessType: "grant" as const,
      grantSettingsLevel: "superadmin" as const,
    };
    renderHook(() => useCommunityBillingSummary(community), { wrapper });
    await waitFor(() => expect(read).toHaveBeenCalledWith(42));
  });

  it("never asks for support whose grant only reads", () => {
    const community = {
      ...buildCommunity({
        id: 42,
        role: "superadmin",
        can: communityCan("superadmin", { configure: false }),
      }),
      accessType: "grant" as const,
      grantSettingsLevel: "superadmin" as const,
    };
    renderHook(() => useCommunityBillingSummary(community), { wrapper });
    expect(read).not.toHaveBeenCalled();
  });

  it("never asks on a self-hosted install", () => {
    state.billing = null;
    const community = buildCommunity({ id: 42, role: "superadmin" });
    renderHook(() => useCommunityBillingSummary(community), { wrapper });
    expect(read).not.toHaveBeenCalled();
  });
});
