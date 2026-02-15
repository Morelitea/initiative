import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Flame, Target, Clock, TrendingUp, TrendingDown } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useUserStats } from "@/hooks/useUserStats";
import { useGuilds } from "@/hooks/useGuilds";
import { StatsMetricCard } from "@/components/stats/StatsMetricCard";
import { VelocityChart } from "@/components/stats/VelocityChart";
import { GuildBreakdownChart } from "@/components/stats/GuildBreakdownChart";
import { HeatmapChart } from "@/components/stats/HeatmapChart";

const GUILD_FILTER_ALL = "all";

export function UserStatsPage() {
  const { t } = useTranslation("stats");
  const [selectedGuildId, setSelectedGuildId] = useState<string>(GUILD_FILTER_ALL);
  const { guilds } = useGuilds();

  const guildIdParam = selectedGuildId === GUILD_FILTER_ALL ? null : Number(selectedGuildId);
  const { data: stats, isLoading, error } = useUserStats(guildIdParam);

  const handleGuildChange = (value: string) => {
    setSelectedGuildId(value);
  };

  return (
    <div className="container mx-auto space-y-6 p-6">
      {/* Header with Guild filter */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold">{t("page.title")}</h1>
          <p className="text-muted-foreground mt-1 text-sm">{t("page.subtitle")}</p>
        </div>
        <div className="w-full sm:w-[200px]">
          <Select value={selectedGuildId} onValueChange={handleGuildChange}>
            <SelectTrigger>
              <SelectValue placeholder={t("page.guildFilterPlaceholder")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={GUILD_FILTER_ALL}>{t("page.allGuilds")}</SelectItem>
              {guilds.map((guild) => (
                <SelectItem key={guild.id} value={String(guild.id)}>
                  {guild.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Loading state */}
      {isLoading && (
        <div className="text-muted-foreground flex items-center gap-2 text-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("page.loading")}
        </div>
      )}

      {/* Error state */}
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{t("page.error")}</AlertDescription>
        </Alert>
      )}

      {/* Stats content */}
      {stats && (
        <>
          {/* Top Metrics Row - 4 cards */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
            <StatsMetricCard
              icon={Flame}
              title={t("metrics.currentStreak")}
              value={stats.streak}
              unit={t("metrics.days")}
              subtitle={t("metrics.consecutiveDays")}
              variant={stats.streak >= 7 ? "success" : stats.streak >= 3 ? "warning" : "default"}
            />
            <StatsMetricCard
              icon={Target}
              title={t("metrics.onTimeRate")}
              value={stats.on_time_rate.toFixed(1)}
              unit="%"
              subtitle={t("metrics.onTimeSubtitle")}
              variant={
                stats.on_time_rate >= 80
                  ? "success"
                  : stats.on_time_rate >= 60
                    ? "warning"
                    : "danger"
              }
            />
            <StatsMetricCard
              icon={Clock}
              title={t("metrics.avgCompletion")}
              value={stats.avg_completion_days?.toFixed(1) ?? null}
              unit={stats.avg_completion_days !== null ? t("metrics.days") : undefined}
              subtitle={t("metrics.avgCompletionSubtitle")}
            />
            <StatsMetricCard
              icon={stats.backlog_trend === "Growing" ? TrendingUp : TrendingDown}
              title={t("metrics.backlogTrend")}
              value={
                stats.backlog_trend === "Growing" ? t("metrics.growing") : t("metrics.shrinking")
              }
              subtitle={t("metrics.thisWeek")}
              variant={stats.backlog_trend === "Shrinking" ? "success" : "warning"}
            />
          </div>

          {/* Tasks Completed Card */}
          <Card>
            <CardHeader>
              <CardTitle>{t("tasksCompleted.title")}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-col gap-6 sm:flex-row sm:gap-12">
                <div>
                  <div className="text-3xl font-bold">{stats.tasks_completed_total}</div>
                  <div className="text-muted-foreground mt-1 text-sm">
                    {t("tasksCompleted.allTime")}
                  </div>
                </div>
                <div>
                  <div className="text-3xl font-bold">{stats.tasks_completed_this_week}</div>
                  <div className="text-muted-foreground mt-1 text-sm">
                    {t("tasksCompleted.thisWeek")}
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Charts Row */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <VelocityChart data={stats.velocity_data} />
            <GuildBreakdownChart data={stats.guild_breakdown} />
          </div>

          {/* Heatmap Full Width */}
          <HeatmapChart data={stats.heatmap_data} />
        </>
      )}
    </div>
  );
}
