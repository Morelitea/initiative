/**
 * Opening a tool records it for the header's tabs bar. The bar is read across
 * every community the reader is in, so a reopen moves the tab rather than
 * reading the bar again. Opening something inside a tool is recorded too, and
 * never touches the bar.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { useParams } from "@tanstack/react-router";
import { renderHook, waitFor } from "@testing-library/react";
import { HttpResponse } from "msw";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { buildRecentItem } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { RecentItemRead } from "@/api/generated/initiativeAPI.schemas";
import { getListRecentsQueryKey } from "@/api/generated/recents/recents";
import { useRecordOpen, useRecordRecentView } from "@/hooks/useRecents";
import { queryClient } from "@/lib/queryClient";
import { FROM_SEARCH } from "@/lib/searchResults";

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

  it("records something inside a tool with where it was opened from, leaving the bar alone", async () => {
    const opened: URL[] = [];
    server.use(
      communityHttp.post("/recents/:entityType/:entityId", ({ request, params }) => {
        const url = new URL(request.url);
        opened.push(url);
        return HttpResponse.json({
          entity_type: params.entityType,
          entity_id: Number(params.entityId),
          last_viewed_at: VIEWED_AT,
          source: url.searchParams.get("source") ?? "direct",
        });
      })
    );
    const TaskPage = () => {
      const { taskId } = useParams({ strict: false }) as { taskId: string };
      useRecordOpen("task", Number(taskId));
      return null;
    };
    const key = getListRecentsQueryKey();
    const bar = [buildRecentItem()];
    queryClient.setQueryData(key, bar);
    const { router } = renderPage(TaskPage, {
      queryClient,
      initialRoute: "/c/$communityId/tasks/$taskId",
      routeParams: { communityId: "3", taskId: "7" },
    });

    await waitFor(() => expect(opened).toHaveLength(1));
    expect(opened[0].pathname).toBe("/api/v1/c/3/recents/task/7");
    expect(opened[0].searchParams.get("source")).toBeNull();

    await router.navigate({ href: "/c/3/tasks/8", state: FROM_SEARCH });
    await waitFor(() => expect(opened).toHaveLength(2));
    expect(opened[1].pathname).toBe("/api/v1/c/3/recents/task/8");
    expect(opened[1].searchParams.get("source")).toBe("search");
    expect(queryClient.getQueryData(key)).toBe(bar);
    expect(queryClient.getQueryState(key)?.isInvalidated).toBe(false);
  });
});
