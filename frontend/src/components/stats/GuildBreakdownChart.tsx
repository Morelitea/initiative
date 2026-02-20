import { useTranslation } from "react-i18next";
import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ChartContainer, ChartTooltipContent } from "@/components/ui/chart";
import type { GuildTaskBreakdown } from "@/api/generated/initiativeAPI.schemas";

interface GuildBreakdownChartProps {
  data: GuildTaskBreakdown[];
}

const COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];

export function GuildBreakdownChart({ data }: GuildBreakdownChartProps) {
  const { t } = useTranslation("stats");
  if (data.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("guildBreakdown.title")}</CardTitle>
          <CardDescription>{t("guildBreakdown.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="text-muted-foreground flex h-[300px] items-center justify-center text-sm">
            {t("guildBreakdown.noData")}
          </div>
        </CardContent>
      </Card>
    );
  }

  const chartConfig = data.reduce(
    (acc, guild, index) => {
      acc[`guild_${guild.guild_id}`] = {
        label: guild.guild_name,
        color: COLORS[index % COLORS.length],
      };
      return acc;
    },
    {} as Record<string, { label: string; color: string }>
  );

  // Format data for pie chart
  const pieData = data.map((guild) => ({
    name: guild.guild_name,
    value: guild.completed_count,
    guild_id: guild.guild_id,
  }));

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("guildBreakdown.title")}</CardTitle>
        <CardDescription>{t("guildBreakdown.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <ChartContainer config={chartConfig} className="h-[300px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={pieData}
                cx="50%"
                cy="50%"
                labelLine={false}
                label={({ name, percent }) => `${name}: ${(percent * 100).toFixed(0)}%`}
                outerRadius={80}
                fill="#8884d8"
                dataKey="value"
              >
                {pieData.map((entry, index) => (
                  <Cell key={`cell-${entry.guild_id}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip content={<ChartTooltipContent />} />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </ChartContainer>
      </CardContent>
    </Card>
  );
}
