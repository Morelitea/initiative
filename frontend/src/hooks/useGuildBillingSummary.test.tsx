import { QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildGuild, guildCan } from "@/__tests__/factories";
import { createTestQueryClient } from "@/__tests__/helpers/render";

const state = vi.hoisted(() => ({ billing: null as { url: string } | null }));
vi.mock("@/hooks/useAppConfig", () => ({ useAppConfig: () => ({ billing: state.billing }) }));
const read = vi.hoisted(() => vi.fn());
vi.mock("@/api/generated/communities/communities", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/generated/communities/communities")>()),
  readCommunityBillingSummary: read,
}));

import { useGuildBillingSummary } from "./useGuildBillingSummary";

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={createTestQueryClient()}>{children}</QueryClientProvider>
);

// The summary route is the seat's, and there is nothing to ask without a
// billing portal — so the hook asks in exactly that case.
describe("useGuildBillingSummary", () => {
  beforeEach(() => {
    state.billing = { url: "https://billing.example.com" };
    read.mockReset();
    read.mockResolvedValue({ available: true, payment_failed: false });
  });

  it("asks for the seat of a hosted install", async () => {
    const guild = buildGuild({ id: 42, role: "superadmin" });
    const { result } = renderHook(() => useGuildBillingSummary(guild), { wrapper });
    await waitFor(() => expect(result.current.data?.available).toBe(true));
    expect(read).toHaveBeenCalledWith(42);
  });

  it("never asks for an ordinary admin", () => {
    const guild = buildGuild({ id: 42, role: "admin" });
    renderHook(() => useGuildBillingSummary(guild), { wrapper });
    expect(read).not.toHaveBeenCalled();
  });

  it("asks for support holding the seat with write access", async () => {
    const guild = {
      ...buildGuild({
        id: 42,
        role: "superadmin",
        can: guildCan("superadmin", { configure: true }),
      }),
      accessType: "grant" as const,
      grantSettingsLevel: "superadmin" as const,
    };
    renderHook(() => useGuildBillingSummary(guild), { wrapper });
    await waitFor(() => expect(read).toHaveBeenCalledWith(42));
  });

  it("never asks for support whose grant only reads", () => {
    const guild = {
      ...buildGuild({
        id: 42,
        role: "superadmin",
        can: guildCan("superadmin", { configure: false }),
      }),
      accessType: "grant" as const,
      grantSettingsLevel: "superadmin" as const,
    };
    renderHook(() => useGuildBillingSummary(guild), { wrapper });
    expect(read).not.toHaveBeenCalled();
  });

  it("never asks on a self-hosted install", () => {
    state.billing = null;
    const guild = buildGuild({ id: 42, role: "superadmin" });
    renderHook(() => useGuildBillingSummary(guild), { wrapper });
    expect(read).not.toHaveBeenCalled();
  });
});
