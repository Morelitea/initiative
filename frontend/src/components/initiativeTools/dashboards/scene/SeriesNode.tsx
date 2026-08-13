import { useMemo } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatAxisValue, formatValue } from "@/lib/widgets/format";
import type { SceneNode } from "@/lib/widgets/sceneSpec";
import { seriesColor } from "@/lib/widgets/tone";

type Node = Extract<SceneNode, { kind: "series" }>;

/** Recharts wants one row per x with a column per series; a scene carries one
 *  list of points per series. Merging on x keeps series aligned even when they
 *  don't cover the same categories. */
const toRows = (node: Node) => {
  const byX = new Map<string | number, Record<string, string | number>>();
  const order: (string | number)[] = [];

  node.series.forEach((series, index) => {
    const key = `s${index}`;
    for (const point of series.points) {
      let row = byX.get(point.x);
      if (!row) {
        row = { x: point.x };
        byX.set(point.x, row);
        order.push(point.x);
      }
      row[key] = point.y;
    }
  });

  return order.map((x) => byX.get(x) as Record<string, string | number>);
};

const axisProps = {
  stroke: "var(--muted-foreground)",
  fontSize: 11,
  tickLine: false,
  axisLine: false,
} as const;

const tooltipProps = {
  contentStyle: {
    background: "var(--popover)",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius-md)",
    color: "var(--popover-foreground)",
    fontSize: 12,
  },
} as const;

export function SeriesNode({ node }: { node: Node }) {
  const rows = useMemo(() => toRows(node), [node]);
  const names = node.series.map((series, index) => series.name ?? `Series ${index + 1}`);
  const stackId = node.stacked ? "stack" : undefined;

  // Recharts hands its callbacks loosely-typed values, so these take `unknown`
  // and narrow, rather than asserting a shape the library does not promise.
  const tickFormatter = (value: unknown) =>
    typeof value === "string" || typeof value === "number"
      ? formatAxisValue(value, node.format)
      : "";
  const valueFormatter = (value: unknown) =>
    typeof value === "number" ? formatValue(value, node.format) : String(value ?? "");

  if (!rows.length) return null;

  // A pie shows a single series as parts of a whole; extra series have no
  // meaning in that shape, so only the first is drawn.
  if (node.mark === "pie") {
    const slices = node.series[0]?.points ?? [];
    return (
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Tooltip {...tooltipProps} formatter={valueFormatter} />
          {node.showLegend && <Legend wrapperStyle={{ fontSize: 11 }} />}
          <Pie
            data={slices.map((point) => ({ name: String(point.x), value: point.y }))}
            dataKey="value"
            nameKey="name"
            innerRadius="45%"
            outerRadius="80%"
            paddingAngle={2}
          >
            {slices.map((point, index) => (
              <Cell key={String(point.x)} fill={seriesColor(index)} />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
    );
  }

  const shared = (
    <>
      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
      <XAxis dataKey="x" {...axisProps} tickFormatter={tickFormatter} />
      <YAxis {...axisProps} width={44} tickFormatter={tickFormatter} />
      <Tooltip
        {...tooltipProps}
        labelFormatter={tickFormatter}
        formatter={(value: unknown, name: unknown) => [valueFormatter(value), String(name ?? "")]}
      />
      {node.showLegend && <Legend wrapperStyle={{ fontSize: 11 }} />}
    </>
  );

  if (node.mark === "line") {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows}>
          {shared}
          {node.series.map((series, index) => (
            <Line
              key={names[index]}
              type="monotone"
              dataKey={`s${index}`}
              name={names[index]}
              stroke={seriesColor(index, series.tone)}
              strokeWidth={2}
              dot={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    );
  }

  if (node.mark === "area") {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={rows}>
          {shared}
          {node.series.map((series, index) => (
            <Area
              key={names[index]}
              type="monotone"
              dataKey={`s${index}`}
              name={names[index]}
              stackId={stackId}
              stroke={seriesColor(index, series.tone)}
              fill={seriesColor(index, series.tone)}
              fillOpacity={0.2}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    );
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={rows}>
        {shared}
        {node.series.map((series, index) => (
          <Bar
            key={names[index]}
            dataKey={`s${index}`}
            name={names[index]}
            stackId={stackId}
            fill={seriesColor(index, series.tone)}
            radius={[2, 2, 0, 0]}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}
