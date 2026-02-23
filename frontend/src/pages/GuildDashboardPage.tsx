import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import {
  CheckCircle2,
  Clock,
  Flame,
  ListTodo,
  Users,
  ScrollText,
  TrendingDown,
  TrendingUp,
} from "lucide-react";

import { useGuilds } from "@/hooks/useGuilds";
import { useUserStats } from "@/hooks/useUserStats";
import { useProjects } from "@/hooks/useProjects";
import { useInitiatives } from "@/hooks/useInitiatives";
import { useTasks } from "@/hooks/useTasks";
import { useRecentComments } from "@/hooks/useComments";
import { useGuildPath } from "@/lib/guildUrl";
import { StatsMetricCard } from "@/components/stats/StatsMetricCard";
import { VelocityChart } from "@/components/stats/VelocityChart";
import { ProjectHealthList } from "@/components/dashboard/ProjectHealthList";
import { UpcomingTasksList } from "@/components/dashboard/UpcomingTasksList";
import { InitiativeOverview } from "@/components/dashboard/InitiativeOverview";
import { RecentCommentsList } from "@/components/dashboard/RecentCommentsList";
import { ProgressCircle } from "@/components/ui/progress-circle";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { FavoriteProjectButton } from "@/components/projects/FavoriteProjectButton";
import {
  TaskStatusCategory,
  ListTasksApiV1TasksGetParams,
} from "@/api/generated/initiativeAPI.schemas";

const DASHBOARD_TASK_PARAMS: ListTasksApiV1TasksGetParams = {
  conditions: [
    {
      field: "status_category",
      op: "in_",
      value: [TaskStatusCategory.backlog, TaskStatusCategory.todo, TaskStatusCategory.in_progress],
    },
  ],
  sorting: [{ field: "due_date", dir: "asc" }],
  page_size: 10,
};

const RECENT_COMMENTS_PARAMS = { limit: 10 };

export function GuildDashboardPage() {
  const { t } = useTranslation("dashboard");
  const { activeGuildId, activeGuild } = useGuilds();
  const gp = useGuildPath();

  const statsQuery = useUserStats(activeGuildId);

  const projectsQuery = useProjects(undefined, {
    staleTime: 60_000,
    enabled: Boolean(activeGuild),
  });

  const initiativesQuery = useInitiatives({
    staleTime: 60_000,
    enabled: Boolean(activeGuild),
  });

  const upcomingTasksQuery = useTasks(DASHBOARD_TASK_PARAMS, {
    staleTime: 60_000,
    enabled: Boolean(activeGuild),
  });

  const recentCommentsQuery = useRecentComments(RECENT_COMMENTS_PARAMS, {
    staleTime: 60_000,
    enabled: Boolean(activeGuild),
  });

  const stats = statsQuery.data;

  const onTimeVariant =
    stats?.on_time_rate == null
      ? "default"
      : stats.on_time_rate >= 80
        ? "success"
        : stats.on_time_rate >= 50
          ? "warning"
          : "danger";

  // Recent projects sorted by updated_at
  const recentProjects = [...(projectsQuery.data?.items ?? [])]
    .filter((p) => !p.is_archived)
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
    .slice(0, 6);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight md:text-3xl">
            {activeGuild?.name ?? t("title")}
          </h1>
          <p className="text-muted-foreground">{t("subtitle")}</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" asChild>
            <Link to={gp("/initiatives")}>
              <Users className="h-4 w-4" />
              {t("quickActions.initiatives")}
            </Link>
          </Button>
          <Button variant="outline" size="sm" asChild>
            <Link to={gp("/projects")}>
              <ListTodo className="h-4 w-4" />
              {t("quickActions.projects")}
            </Link>
          </Button>
          <Button variant="outline" size="sm" asChild>
            <Link to={gp("/documents")}>
              <ScrollText className="h-4 w-4" />
              {t("quickActions.documents")}
            </Link>
          </Button>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        <StatsMetricCard
          icon={CheckCircle2}
          title={t("metrics.tasksThisWeek")}
          value={stats?.tasks_completed_this_week ?? null}
        />
        <StatsMetricCard
          icon={Clock}
          title={t("metrics.onTimeRate")}
          value={stats?.on_time_rate != null ? Math.round(stats.on_time_rate) : null}
          unit="%"
          variant={onTimeVariant as "default" | "success" | "warning" | "danger"}
        />
        <StatsMetricCard
          icon={Flame}
          title={t("metrics.currentStreak")}
          value={stats?.streak ?? null}
          unit={t("metrics.days")}
        />
        <StatsMetricCard
          icon={stats?.backlog_trend === "Growing" ? TrendingUp : TrendingDown}
          title={t("metrics.backlogTrend")}
          value={
            stats?.backlog_trend
              ? stats.backlog_trend === "Growing"
                ? t("metrics.growing")
                : t("metrics.shrinking")
              : null
          }
          variant={stats?.backlog_trend === "Growing" ? "warning" : "success"}
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <VelocityChart data={stats?.velocity_data ?? []} />
        <ProjectHealthList
          projects={projectsQuery.data?.items ?? []}
          isLoading={projectsQuery.isLoading}
        />
      </div>

      {/* Activity Row */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <UpcomingTasksList
          tasks={upcomingTasksQuery.data?.items ?? []}
          isLoading={upcomingTasksQuery.isLoading}
        />

        {/* Recent Projects */}
        <Card>
          <CardHeader>
            <CardTitle>{t("recentProjects.title")}</CardTitle>
            <CardDescription>{t("recentProjects.description")}</CardDescription>
          </CardHeader>
          <CardContent>
            {projectsQuery.isLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <Skeleton className="h-10 w-10 rounded-full" />
                    <Skeleton className="h-4 flex-1" />
                  </div>
                ))}
              </div>
            ) : recentProjects.length === 0 ? (
              <div className="text-muted-foreground flex h-[200px] items-center justify-center text-sm">
                <div className="flex flex-col items-center gap-2">
                  <ListTodo className="h-8 w-8 opacity-50" />
                  <span>{t("recentProjects.noProjects")}</span>
                </div>
              </div>
            ) : (
              <div className="space-y-1">
                {recentProjects.map((project) => {
                  const percent =
                    project.task_summary && project.task_summary.total > 0
                      ? Math.round(
                          (project.task_summary.completed / project.task_summary.total) * 100
                        )
                      : 0;
                  return (
                    <div
                      key={project.id}
                      className="hover:bg-accent flex items-center gap-3 rounded-md px-2 py-2 transition-colors"
                    >
                      <Link
                        to={gp(`/projects/${project.id}`)}
                        className="flex min-w-0 flex-1 items-center gap-3"
                      >
                        <ProgressCircle value={percent} className="h-10 w-10 shrink-0" />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium">
                            {project.icon && <span className="mr-1">{project.icon}</span>}
                            {project.name}
                          </p>
                        </div>
                      </Link>
                      <FavoriteProjectButton
                        projectId={project.id}
                        isFavorited={project.is_favorited ?? false}
                        suppressNavigation
                      />
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Initiatives & Comments Row */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <InitiativeOverview
          initiatives={initiativesQuery.data ?? []}
          projects={projectsQuery.data?.items ?? []}
          isLoading={initiativesQuery.isLoading}
        />
        <RecentCommentsList
          comments={recentCommentsQuery.data ?? []}
          isLoading={recentCommentsQuery.isLoading}
        />
      </div>
    </div>
  );
}
