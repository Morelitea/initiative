/**
 * Built-in: chart — a series drawn as bars, lines, an area, or slices.
 *
 * The workhorse: the `bar_chart`/`line_chart`/`area_chart`/`pie_chart`/
 * `stacked_bar_chart` presets are all this module with a fixed `mark`.
 *
 * @param {import("../dataShapes").WidgetData} data
 * @param {import("../dataShapes").WidgetConfig} config
 */
function render(data, config) {
  const mark = config.mark || "bar";
  const stacked = config.stacked === "true";

  const chart = (series, xLabel, yLabel) => ({
    v: 1,
    scene: {
      kind: "series",
      mark,
      series,
      stacked: stacked || undefined,
      xLabel: xLabel || undefined,
      yLabel: yLabel || undefined,
      // A legend earns its space only once there is more than one series.
      showLegend: series.length > 1,
    },
  });

  const empty = (message) => ({ v: 1, scene: { kind: "empty", message } });

  // Pie slices read as a share of a whole, so the largest belongs first;
  // everything else keeps the order the source gave it, which is usually
  // meaningful (a day sequence, a workflow order).
  const order = (points) => (mark === "pie" ? [...points].sort((a, b) => b.y - a.y) : points);

  switch (data.source) {
    case "task_counts": {
      const rows = data.rows || [];
      if (!rows.length) return empty("No tasks match");
      return chart([
        {
          name: "Tasks",
          points: order(rows.map((row) => ({ x: row.bucket, y: row.count }))),
        },
      ]);
    }

    case "counter_group": {
      const counters = data.counters || [];
      if (!counters.length) return empty("No counters in this group");
      return chart(
        [
          {
            name: data.name || "Counters",
            points: order(counters.map((c) => ({ x: c.name, y: c.value }))),
          },
        ],
        undefined,
        counters[0].unit || undefined
      );
    }

    case "my_stats": {
      const days = data.days || [];
      if (!days.length) return empty("Nothing recorded yet");
      return chart([
        { name: "Activity", points: days.map((day) => ({ x: day.date, y: day.count })) },
      ]);
    }

    case "projects": {
      const rows = data.rows || [];
      if (!rows.length) return empty("No projects match");
      // Done against outstanding reads as a stack; separately it reads as two
      // comparable series. Either way the same two series serve.
      return chart([
        {
          name: "Done",
          points: order(rows.map((row) => ({ x: row.name, y: row.doneCount }))),
          tone: "positive",
        },
        {
          name: "Remaining",
          points: order(
            rows.map((row) => ({
              x: row.name,
              y: Math.max(0, row.taskCount - row.doneCount),
            }))
          ),
          tone: "muted",
        },
      ]);
    }

    case "sheet_range": {
      const range = data.range;
      if (!range?.rows.length) return empty("Range is empty");
      const [firstRow] = range.rows;
      // First non-numeric column labels the axis; every numeric column becomes
      // a series. A range with no labels falls back to row ordinals.
      const labelIndex = firstRow.findIndex((cell) => typeof cell !== "number");
      const valueIndexes = firstRow
        .map((cell, index) => (typeof cell === "number" ? index : -1))
        .filter((index) => index >= 0);
      if (!valueIndexes.length) return empty("No numeric values in range");

      const series = valueIndexes.slice(0, 12).map((index) => ({
        name: range.columns[index] || "Series " + (index + 1),
        points: order(
          range.rows.map((row, rowIndex) => ({
            x: labelIndex >= 0 && row[labelIndex] !== null ? String(row[labelIndex]) : rowIndex + 1,
            y: typeof row[index] === "number" ? row[index] : 0,
          }))
        ),
      }));
      return chart(series, labelIndex >= 0 ? range.columns[labelIndex] : undefined);
    }

    default:
      return empty("This widget cannot draw " + data.source);
  }
}
