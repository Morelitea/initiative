import { QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { createTestQueryClient } from "@/__tests__/helpers/render";

import { useUnreadTree } from "./useUnreadTree";

const places = (...rows: Array<Record<string, unknown>>) =>
  server.use(http.get("/api/v1/notifications/unread", () => HttpResponse.json({ places: rows })));

const wrapper = () => {
  const client = createTestQueryClient();
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
};

const tree = async () => {
  const { result } = renderHook(() => useUnreadTree(), { wrapper: wrapper() });
  await waitFor(() => expect(result.current.hasAny).toBe(true));
  return result;
};

describe("useUnreadTree", () => {
  it("lights every level a place names", async () => {
    places({ guild_id: 7, initiative_id: 9, tool: "project" });
    const result = await tree();

    expect(result.current.hasGuild(7)).toBe(true);
    expect(result.current.hasInitiative(9)).toBe(true);
    expect(result.current.hasTool(9, "project")).toBe(true);
  });

  it("lights nothing a place does not name", async () => {
    places({ guild_id: 7, initiative_id: 9, tool: "project" });
    const result = await tree();

    expect(result.current.hasGuild(8)).toBe(false);
    expect(result.current.hasInitiative(10)).toBe(false);
    expect(result.current.hasTool(9, "document")).toBe(false);
    // The same tool in a different initiative is a different row.
    expect(result.current.hasTool(10, "project")).toBe(false);
  });

  it("lights a community for something belonging to nothing inside it", async () => {
    // A membership notice: it has a community and no initiative, so the
    // community lights and nothing below it does.
    places({ guild_id: 7, initiative_id: null, tool: null });
    const result = await tree();

    expect(result.current.hasGuild(7)).toBe(true);
    expect(result.current.hasInitiative(9)).toBe(false);
  });

  it("counts a place naming nowhere as unread all the same", async () => {
    // A direct message names no community at all, which is why "is anything
    // unread" is the set being non-empty rather than a separate question.
    places({ guild_id: null, initiative_id: null, tool: null });
    const result = await tree();

    expect(result.current.hasAny).toBe(true);
    expect(result.current.hasGuild(7)).toBe(false);
  });

  it("lights nothing at all when there is nothing unread", async () => {
    places();
    const { result } = renderHook(() => useUnreadTree(), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.hasAny).toBe(false));
    expect(result.current.hasGuild(7)).toBe(false);
  });
});
