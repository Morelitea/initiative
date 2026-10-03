/**
 * Opening a tool records it for the header's tabs bar. The bar is read across
 * every community the reader is in, so a reopen moves the tab rather than
 * reading the bar again.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { HttpResponse } from "msw";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { buildRecentItem } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import type { RecentItemRead } from "@/api/generated/initiativeAPI.schemas";
import { getListRecentsQueryKey } from "@/api/generated/recents/recents";
import { useRecordRecentView } from "@/hooks/useRecents";
import { queryClient } from "@/lib/queryClient";

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
);

const VIEWED_AT = "2026-09-30T12:00:00.000Z";

describe("useRecordRecentView", () => {
  afterEach(() => queryClient.clear());

  it("moves a reopened tab to the front, and reads the bar again only for a new one", async () => {
    const key = getListRecentsQueryKey();
    const [first, reopened] = [
      buildRecentItem({ last_viewed_at: "2026-09-30T11:00:00.000Z" }),
      buildRecentItem({ last_viewed_at: "2026-09-30T10:00:00.000Z" }),
    ];
    queryClient.setQueryData<RecentItemRead[]>(key, [first, reopened]);
    server.use(
      communityHttp.post("/recents/:entityType/:entityId", ({ params }) =>
        HttpResponse.json({
          entity_type: "project",
          entity_id: Number(params.entityId),
          last_viewed_at: VIEWED_AT,
        })
      )
    );
    const { result } = renderHook(() => useRecordRecentView("project", reopened.community_id), {
      wrapper,
    });

    result.current.mutate(reopened.entity_id);

    await waitFor(() =>
      expect(queryClient.getQueryData(key)).toEqual([
        { ...reopened, last_viewed_at: VIEWED_AT },
        first,
      ])
    );
    expect(queryClient.getQueryState(key)?.isInvalidated).toBe(false);

    // An answer for an earlier view, arriving last, does not jump the queue.
    server.use(
      communityHttp.post("/recents/:entityType/:entityId", ({ params }) =>
        HttpResponse.json({
          entity_type: "project",
          entity_id: Number(params.entityId),
          last_viewed_at: "2026-09-30T11:30:00.000Z",
        })
      )
    );
    result.current.mutate(first.entity_id);

    await waitFor(() =>
      expect(queryClient.getQueryData(key)).toEqual([
        { ...reopened, last_viewed_at: VIEWED_AT },
        { ...first, last_viewed_at: "2026-09-30T11:30:00.000Z" },
      ])
    );

    result.current.mutate(reopened.entity_id + 100);

    await waitFor(() => expect(queryClient.getQueryState(key)?.isInvalidated).toBe(true));
  });
});
