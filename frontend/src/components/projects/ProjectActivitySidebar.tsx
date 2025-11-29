import { useMemo, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { ChevronLeft, ChevronRight, MessageSquare, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";

import { apiClient } from "@/api/client";
import type { ProjectActivityEntry, ProjectActivityResponse } from "@/types/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ProjectActivitySidebarProps {
  projectId: number | null;
}

export const ProjectActivitySidebar = ({ projectId }: ProjectActivitySidebarProps) => {
  const [collapsed, setCollapsed] = useState(true);
  const isEnabled = Boolean(projectId && !collapsed);

  const activityQuery = useInfiniteQuery<ProjectActivityResponse>({
    queryKey: ["projects", projectId, "activity"],
    queryFn: async ({ pageParam = 1 }) => {
      if (!projectId) {
        throw new Error("Project id required");
      }
      const response = await apiClient.get<ProjectActivityResponse>(
        `/projects/${projectId}/activity`,
        {
          params: { page: pageParam },
        }
      );
      return response.data;
    },
    getNextPageParam: (lastPage) => lastPage.next_page ?? undefined,
    initialPageParam: 1,
    enabled: isEnabled,
    staleTime: 30_000,
    refetchInterval: isEnabled ? 30_000 : false,
  });

  const entries = useMemo<ProjectActivityEntry[]>(() => {
    if (!activityQuery.data) {
      return [];
    }
    return activityQuery.data.pages.flatMap((page) => page.items);
  }, [activityQuery.data]);

  if (!projectId) {
    return null;
  }

  const toggleCollapsed = () => {
    setCollapsed((prev) => !prev);
  };

  return (
    <aside
      className={cn(
        "hidden lg:flex transition-all duration-200",
        collapsed ? "w-15" : "w-80",
        "shrink-0"
      )}
    >
      <div className="sticky top-0 flex h-screen w-full flex-col border-l bg-card shadow-sm">
        <div className="flex items-center justify-between border-b px-3 py-3">
          {!collapsed && (
            <div className="flex items-center gap-2">
              <MessageSquare className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
              <p className="text-sm font-semibold">Project activity</p>
            </div>
          )}
          <div className="flex items-center gap-2">
            {!collapsed ? (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => activityQuery.refetch()}
                disabled={activityQuery.isFetching}
              >
                <RefreshCw
                  className={cn("h-4 w-4", activityQuery.isFetching && "animate-spin")}
                  aria-hidden="true"
                />
                <span className="sr-only">Refresh activity</span>
              </Button>
            ) : null}
            <Button
              type="button"
              variant="outline"
              size="icon"
              className="h-8 w-8"
              onClick={toggleCollapsed}
            >
              {collapsed ? (
                <ChevronLeft className="h-4 w-4" aria-hidden="true" />
              ) : (
                <ChevronRight className="h-4 w-4" aria-hidden="true" />
              )}
              <span className="sr-only">
                {collapsed ? "Expand activity sidebar" : "Collapse activity sidebar"}
              </span>
            </Button>
          </div>
        </div>
        {collapsed ? (
          <div className="flex-1 px-2 py-4 text-center text-xs text-muted-foreground">Activity</div>
        ) : (
          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
            {activityQuery.isLoading ? (
              <p className="text-sm text-muted-foreground">Loading activity…</p>
            ) : entries.length === 0 ? (
              <p className="text-sm text-muted-foreground">No comments yet.</p>
            ) : (
              <ul className="space-y-3">
                {entries.map((entry) => {
                  const authorName =
                    entry.author?.full_name?.trim() ||
                    entry.author?.email ||
                    `User #${entry.author?.id ?? "?"}`;
                  return (
                    <li
                      key={entry.comment_id}
                      className="rounded-lg border border-border/60 bg-background px-3 py-2"
                    >
                      <div className="flex items-center justify-between text-xs text-muted-foreground">
                        <span className="font-medium text-foreground">{authorName}</span>
                        <span>
                          {formatDistanceToNow(new Date(entry.created_at), {
                            addSuffix: true,
                          })}
                        </span>
                      </div>
                      <p className="text-sm text-foreground">
                        commented on{" "}
                        <Link
                          to={`/tasks/${entry.task_id}/edit`}
                          className="font-medium hover:underline"
                        >
                          {entry.task_title}
                        </Link>
                      </p>
                      <p className="mt-1 text-sm text-muted-foreground line-clamp-3">
                        “{entry.content}”
                      </p>
                    </li>
                  );
                })}
              </ul>
            )}
            {activityQuery.hasNextPage ? (
              <Button
                type="button"
                variant="secondary"
                className="w-full"
                onClick={() => activityQuery.fetchNextPage()}
                disabled={activityQuery.isFetchingNextPage}
              >
                {activityQuery.isFetchingNextPage ? "Loading…" : "Load more"}
              </Button>
            ) : null}
          </div>
        )}
      </div>
    </aside>
  );
};
