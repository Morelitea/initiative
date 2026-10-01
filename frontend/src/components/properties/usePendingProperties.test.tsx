/**
 * Adding properties one after another keeps every one of them: each write
 * replaces the row's values, so it has to carry the ones added before it.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { buildPropertyDefinition } from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { PropertyTarget } from "@/api/generated/initiativeAPI.schemas";

import { usePendingProperties } from "./usePendingProperties";

vi.mock("@/hooks/useActiveGuildId", () => ({ useActiveGuildId: () => 1 }));

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
);

describe("usePendingProperties", () => {
  it("writes every property added so far, before the first comes back", async () => {
    const bodies: number[][] = [];
    server.use(
      guildHttp.put("/properties/:target/:entityId", async ({ request }) => {
        const body = (await request.json()) as { values: { property_id: number }[] };
        bodies.push(body.values.map((value) => value.property_id));
        return HttpResponse.json([]);
      })
    );
    const first = buildPropertyDefinition({ id: 1 });
    const second = buildPropertyDefinition({ id: 2 });
    const { result } = renderHook(
      () => usePendingProperties(PropertyTarget.calendar_event, 9, []),
      { wrapper }
    );

    act(() => {
      result.current.add(first);
      result.current.add(second);
    });

    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies).toEqual([[1], [1, 2]]);
    expect(result.current.propertyIds).toEqual([1, 2]);
  });
});
