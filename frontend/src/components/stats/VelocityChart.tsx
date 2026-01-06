import { format, parseISO } from "date-fns";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ChartContainer, ChartTooltipContent } from "@/components/ui/chart";
import type { VelocityWeekData } from "@/types/api";

interface VelocityChartProps {
  data: VelocityWeekData[];
}

const chartConfig = {
  assigned: {
    label: "Assigned",
    color: "var(--chart-1)",
  },
  completed: {
    label: "Completed",
    color: "var(--chart-2)",
  },
};

export function VelocityChart({ data }: VelocityChartProps) {
  // Format data for display
  const formattedData = data.map((week) => ({
    ...week,
    weekLabel: format(parseISO(week.week_start), "MMM d"),
  }));

  if (data.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Velocity</CardTitle>
          <CardDescription>Tasks assigned vs completed per week</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="text-muted-foreground flex h-[300px] items-center justify-center text-sm">
            No velocity data available
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Velocity</CardTitle>
        <CardDescription>Tasks assigned vs completed per week (last 12 weeks)</CardDescription>
      </CardHeader>
      <CardContent>
        <ChartContainer config={chartConfig} className="h-[300px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={formattedData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="weekLabel"
                tick={{ fontSize: 12 }}
                tickLine={false}
                axisLine={false}
              />
              <YAxis tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
              <Tooltip content={<ChartTooltipContent />} />
              <Legend />
              <Bar dataKey="assigned" fill="var(--color-assigned)" radius={[4, 4, 0, 0]} />
              <Bar dataKey="completed" fill="var(--color-completed)" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartContainer>
      </CardContent>
    </Card>
  );
}
