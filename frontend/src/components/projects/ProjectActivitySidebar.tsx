import { useInfiniteQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { formatDistanceToNow } from "date-fns";
import { ChevronRight, MessageSquare } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  ProjectActivityEntry,
  ProjectActivityResponse,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getProjectActivityFeedApiV1GGuildIdProjectsProjectIdActivityGetQueryKey,
  projectActivityFeedApiV1GGuildIdProjectsProjectIdActivityGet,
} from "@/api/generated/projects/projects";
import { Button } from "@/components/ui/button";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useDateLocale } from "@/hooks/useDateLocale";
import { useGuilds } from "@/hooks/useGuilds";
import { guildPath } from "@/lib/guildUrl";
import { cn } from "@/lib/utils";

interface ProjectActivitySidebarProps {
  projectId: number | null;
}

export const ProjectActivitySidebar = ({ projectId }: ProjectActivitySidebarProps) => {
  const { activeGuildId } = useGuilds();
  const guildId = useActiveGuildId();
  const { t } = useTranslation(["projects", "common"]);
  const dateLocale = useDateLocale();
  const [collapsed, setCollapsed] = useState(true);
  const isEnabled = Boolean(projectId && !collapsed);

  // Helper to create guild-scoped paths
  const gp = (path: string) => (activeGuildId ? guildPath(activeGuildId, path) : path);

  const activityQuery = useInfiniteQuery<ProjectActivityResponse>({
    queryKey: getProjectActivityFeedApiV1GGuildIdProjectsProjectIdActivityGetQueryKey(
      guildId,
      projectId!
    ),
    queryFn: async ({ pageParam = 1 }) => {
      if (!projectId) {
        throw new Error("Project id required");
      }
      return projectActivityFeedApiV1GGuildIdProjectsProjectIdActivityGet(guildId, projectId, {
        page: pageParam as number,
      }) as unknown as Promise<ProjectActivityResponse>;
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
      <div className="flex h-full w-full flex-col border-l bg-card shadow-sm">
        <div
          className="flex flex-col border-b"
          style={{ paddingTop: "var(--safe-area-inset-top)" }}
        >
          <div className="flex h-12 items-center justify-between px-3">
            {!collapsed && (
              <div className="flex items-center gap-2">
                <MessageSquare className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                <p className="font-semibold text-sm">{t("activitySidebar.title")}</p>
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
                  <MessageSquare className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                ) : (
                  <ChevronRight className="h-4 w-4" aria-hidden="true" />
                )}
                <span className="sr-only">
                  {collapsed ? t("activitySidebar.expand") : t("activitySidebar.collapse")}
                </span>
              </Button>
            </div>
          </div>
        </div>
        {collapsed ? (
          <div className="flex-1 px-2 py-4 text-center text-muted-foreground text-xs">
            {t("activitySidebar.activity")}
          </div>
        ) : (
          <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
            {activityQuery.isLoading ? (
              <p className="text-muted-foreground text-sm">{t("activitySidebar.loading")}</p>
            ) : entries.length === 0 ? (
              <p className="text-muted-foreground text-sm">{t("activitySidebar.noComments")}</p>
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
                      <div className="flex items-center justify-between text-muted-foreground text-xs">
                        <span className="font-medium text-foreground">{authorName}</span>
                        <span>
                          {formatDistanceToNow(new Date(entry.created_at), {
                            addSuffix: true,
                            locale: dateLocale,
                          })}
                        </span>
                      </div>
                      <p className="text-foreground text-sm">
                        {t("activitySidebar.commentedOn")}{" "}
                        <Link
                          to={gp(`/tasks/${entry.task_id}`)}
                          className="font-medium hover:underline"
                        >
                          {entry.task_title}
                        </Link>
                      </p>
                      <p className="mt-1 line-clamp-3 text-muted-foreground text-sm">
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
                {activityQuery.isFetchingNextPage
                  ? t("common:loading")
                  : t("activitySidebar.loadMore")}
              </Button>
            ) : null}
          </div>
        )}
      </div>
    </aside>
  );
};
