/**
 * Built-in: funnel — staged counts, widest first.
 *
 * @param {import("../dataShapes").WidgetData} data
 * @param {import("../dataShapes").WidgetConfig} config
 */
function render(data, config) {
  const empty = (message) => ({ v: 1, scene: { kind: "empty", message } });

  const funnel = (stages) => {
    if (!stages.length) return empty("No stages to show");
    // A funnel is read top-down as narrowing, so the widest stage leads
    // regardless of the order the source happened to return.
    const ordered = [...stages].sort((a, b) => b.value - a.value);
    return {
      v: 1,
      scene: {
        kind: "funnel",
        stages: ordered,
        format: config.format || undefined,
      },
    };
  };

  switch (data.source) {
    case "task_counts": {
      const rows = data.rows || [];
      if (!rows.length) return empty("No tasks match");
      return funnel(rows.map((row) => ({ label: row.bucket, value: row.count })));
    }

    case "sheet_range": {
      const range = data.range;
      if (!range?.rows.length) return empty("Range is empty");
      const [firstRow] = range.rows;
      const labelIndex = firstRow.findIndex((cell) => typeof cell !== "number");
      const valueIndex = firstRow.findIndex((cell) => typeof cell === "number");
      if (valueIndex < 0) return empty("No numeric values in range");
      return funnel(
        range.rows.map((row, index) => ({
          label:
            labelIndex >= 0 && row[labelIndex] !== null
              ? String(row[labelIndex])
              : "Stage " + (index + 1),
          value: typeof row[valueIndex] === "number" ? row[valueIndex] : 0,
        }))
      );
    }

    default:
      return empty("This widget cannot draw " + data.source);
  }
}
