import { useState } from "react";
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
          <h1 className="text-3xl font-bold">My Stats</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Track your productivity and task completion metrics
          </p>
        </div>
        <div className="w-full sm:w-[200px]">
          <Select value={selectedGuildId} onValueChange={handleGuildChange}>
            <SelectTrigger>
              <SelectValue placeholder="Select guild" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={GUILD_FILTER_ALL}>All Guilds</SelectItem>
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
          Loading stats...
        </div>
      )}

      {/* Error state */}
      {error && (
        <Alert variant="destructive">
          <AlertDescription>Failed to load stats. Please try again later.</AlertDescription>
        </Alert>
      )}

      {/* Stats content */}
      {stats && (
        <>
          {/* Top Metrics Row - 4 cards */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
            <StatsMetricCard
              icon={Flame}
              title="Current Streak"
              value={stats.streak}
              unit="days"
              subtitle="Consecutive work days"
              variant={stats.streak >= 7 ? "success" : stats.streak >= 3 ? "warning" : "default"}
            />
            <StatsMetricCard
              icon={Target}
              title="On-Time Rate"
              value={stats.on_time_rate.toFixed(1)}
              unit="%"
              subtitle="Tasks completed before due date"
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
              title="Avg Completion"
              value={stats.avg_completion_days?.toFixed(1) ?? null}
              unit={stats.avg_completion_days !== null ? "days" : undefined}
              subtitle="From start to completion"
            />
            <StatsMetricCard
              icon={stats.backlog_trend === "Growing" ? TrendingUp : TrendingDown}
              title="Backlog Trend"
              value={stats.backlog_trend}
              subtitle="This week"
              variant={stats.backlog_trend === "Shrinking" ? "success" : "warning"}
            />
          </div>

          {/* Tasks Completed Card */}
          <Card>
            <CardHeader>
              <CardTitle>Tasks Completed</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-col gap-6 sm:flex-row sm:gap-12">
                <div>
                  <div className="text-3xl font-bold">{stats.tasks_completed_total}</div>
                  <div className="text-muted-foreground mt-1 text-sm">All time</div>
                </div>
                <div>
                  <div className="text-3xl font-bold">{stats.tasks_completed_this_week}</div>
                  <div className="text-muted-foreground mt-1 text-sm">This week</div>
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
