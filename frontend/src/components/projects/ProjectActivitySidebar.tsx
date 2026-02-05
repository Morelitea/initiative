import { useMemo, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { ChevronRight, MessageSquare } from "lucide-react";
import { Link } from "@tanstack/react-router";

import { apiClient } from "@/api/client";
import type { ProjectActivityEntry, ProjectActivityResponse } from "@/types/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { guildPath } from "@/lib/guildUrl";
import { useGuilds } from "@/hooks/useGuilds";

interface ProjectActivitySidebarProps {
  projectId: number | null;
}

export const ProjectActivitySidebar = ({ projectId }: ProjectActivitySidebarProps) => {
  const { activeGuildId } = useGuilds();
  const [collapsed, setCollapsed] = useState(true);
  const isEnabled = Boolean(projectId && !collapsed);

  // Helper to create guild-scoped paths
  const gp = (path: string) => (activeGuildId ? guildPath(activeGuildId, path) : path);

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
        "sticky top-0 right-0 z-20 hidden h-screen shrink-0 transition-all duration-200 xl:flex",
        collapsed ? "w-15" : "w-80"
      )}
    >
      <div className="bg-card flex h-full w-full flex-col border-l shadow-sm">
        <div className="flex h-[calc(4rem+1px)] items-center justify-between border-b px-3 py-3">
          {!collapsed && (
            <div className="flex items-center gap-2">
              <MessageSquare className="text-muted-foreground h-4 w-4" aria-hidden="true" />
              <p className="text-sm font-semibold">Project activity</p>
            </div>
          )}
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="icon"
              className="h-8 w-8"
              onClick={toggleCollapsed}
            >
              {collapsed ? (
                <MessageSquare className="text-muted-foreground h-4 w-4" aria-hidden="true" />
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
          <div className="text-muted-foreground flex-1 px-2 py-4 text-center text-xs">Activity</div>
        ) : (
          <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
            {activityQuery.isLoading ? (
              <p className="text-muted-foreground text-sm">Loading activity…</p>
            ) : entries.length === 0 ? (
              <p className="text-muted-foreground text-sm">No comments yet.</p>
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
                      className="border-border/60 bg-background rounded-lg border px-3 py-2"
                    >
                      <div className="text-muted-foreground flex items-center justify-between text-xs">
                        <span className="text-foreground font-medium">{authorName}</span>
                        <span>
                          {formatDistanceToNow(new Date(entry.created_at), {
                            addSuffix: true,
                          })}
                        </span>
                      </div>
                      <p className="text-foreground text-sm">
                        commented on{" "}
                        <Link
                          to={gp(`/tasks/${entry.task_id}`)}
                          className="font-medium hover:underline"
                        >
                          {entry.task_title}
                        </Link>
                      </p>
                      <p className="text-muted-foreground mt-1 line-clamp-3 text-sm">
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
