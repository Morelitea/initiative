/**
 * Adding an option answers with the option the server kept, under the label
 * that was asked for — or refuses when it did not keep one.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import { HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { buildPropertyDefinition } from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { useAppendPropertyOption } from "@/hooks/useProperties";

vi.mock("@/hooks/useActiveGuildId", () => ({ useActiveGuildId: () => 1 }));

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
);

describe("useAppendPropertyOption", () => {
  const definition = buildPropertyDefinition({
    id: 7,
    type: "select",
    options: [{ value: "todo", label: "To do", color: null }],
  });

  const answering = (options: { value: string; label: string; color: null }[]) =>
    server.use(
      guildHttp.patch("/property-definitions/:id", () =>
        HttpResponse.json({
          definition: { ...definition, options },
          orphaned_value_count: 0,
        })
      )
    );

  it("answers with the option the server kept", async () => {
    answering([
      { value: "todo", label: "To do", color: null },
      { value: "done", label: "Done", color: null },
    ]);
    const { result } = renderHook(() => useAppendPropertyOption(), { wrapper });

    const added = await result.current.appendOption(definition, "Done");

    expect(added.option).toMatchObject({ value: "done", label: "Done" });
  });

  it("refuses when the value was already taken by another label", async () => {
    answering([
      { value: "todo", label: "To do", color: null },
      { value: "done", label: "done!", color: null },
    ]);
    const { result } = renderHook(() => useAppendPropertyOption(), { wrapper });

    await expect(result.current.appendOption(definition, "Done")).rejects.toThrow();
  });
});
