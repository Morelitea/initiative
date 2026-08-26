/**
 * The preset list carries `can_manage`, which gates every curation control, so
 * it must never be answered with another project's data.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { buildDefaultFilterPresets } from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { useFilterPresets } from "@/hooks/useFilterPresets";

vi.mock("@/hooks/useActiveGuildId", () => ({ useActiveGuildId: () => 1 }));

const wrapper = (client: QueryClient) => {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
};

describe("useFilterPresets", () => {
  it("does not answer one project with another project's presets", async () => {
    // The app-wide default is `placeholderData: (prev) => prev`, which applies
    // across query keys — including a change of project.
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false, placeholderData: (prev: unknown) => prev },
      },
    });
    server.use(
      guildHttp.get("/projects/:projectId/filter-presets/", async ({ params }) => {
        const projectId = Number(params.projectId);
        if (projectId === 2) await new Promise((resolve) => setTimeout(resolve, 50));
        return HttpResponse.json({
          items: buildDefaultFilterPresets(projectId),
          can_manage: projectId === 1,
        });
      })
    );

    const { result, rerender } = renderHook(({ projectId }) => useFilterPresets(projectId), {
      initialProps: { projectId: 1 },
      wrapper: wrapper(client),
    });
    await waitFor(() => expect(result.current.data?.can_manage).toBe(true));

    rerender({ projectId: 2 });

    // While project 2 is in flight it must report nothing, not project 1's
    // answer — `can_manage: true` here would render controls this viewer may
    // not have.
    expect(result.current.data).toBeUndefined();
    await waitFor(() => expect(result.current.data?.can_manage).toBe(false));
    expect(result.current.data?.items[0].project_id).toBe(2);
  });
});
