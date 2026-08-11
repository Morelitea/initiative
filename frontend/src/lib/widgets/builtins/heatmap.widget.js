/**
 * What this widget calls itself, in every language it supports.
 *
 * Names and option labels live in the module rather than in the app's locale
 * files: a marketplace widget has to be able to name itself without an app
 * release, and the built-ins get no special treatment. Binding *source* labels
 * stay app-owned — they name our endpoints and are shared by every widget.
 */
const meta = {
  name: {
    en: "Heatmap",
    de: "Heatmap",
    es: "Mapa de calor",
    fr: "Carte thermique",
  },
  description: {
    en: "Daily activity as a calendar grid, one column per week.",
    de: "Tägliche Aktivität als Kalenderraster, eine Spalte pro Woche.",
    es: "La actividad diaria como una cuadrícula de calendario, una columna por semana.",
    fr: "L'activité quotidienne sous forme de grille calendaire, une colonne par semaine.",
  },
};

/**
 * Built-in: heatmap — activity density over a calendar grid.
 *
 * Lays days out the way a contribution graph does: one column per week, one row
 * per weekday. All date maths is UTC, because the sandbox has no timezone and
 * the grid only needs to be self-consistent.
 *
 * @param {import("../dataShapes").WidgetData} data
 * @param {import("../dataShapes").WidgetConfig} config
 */
function render(data, config) {
  const DAY = 86400000;
  const empty = (message) => ({ v: 1, scene: { kind: "empty", message } });

  const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

  /** @param {{date: number, count: number}[]} days */
  const grid = (days) => {
    if (!days.length) return empty("Nothing recorded yet");

    const sorted = [...days].sort((a, b) => a.date - b.date);
    // Anchor on the Sunday at or before the first day, so column 0 is a whole
    // week and every later date lands on a stable column.
    const first = new Date(sorted[0].date);
    const anchor =
      Date.UTC(first.getUTCFullYear(), first.getUTCMonth(), first.getUTCDate()) -
      first.getUTCDay() * DAY;

    const cells = [];
    let max = 0;
    for (const day of sorted) {
      const at = new Date(day.date);
      const midnight = Date.UTC(at.getUTCFullYear(), at.getUTCMonth(), at.getUTCDate());
      const offset = Math.floor((midnight - anchor) / DAY);
      if (offset < 0) continue;
      if (day.count > max) max = day.count;
      cells.push({
        x: Math.floor(offset / 7),
        y: at.getUTCDay(),
        value: day.count,
        label: day.count + " on " + at.toISOString().slice(0, 10),
      });
    }
    if (!cells.length) return empty("Nothing recorded yet");

    return {
      v: 1,
      scene: {
        kind: "matrix",
        cells,
        max: max || 1,
        yLabels: WEEKDAYS,
        tone: config.tone === "positive" ? "positive" : "accent",
      },
    };
  };

  switch (data.source) {
    case "task_counts": {
      const rows = data.rows || [];
      // Only a date-bucketed count has a calendar shape; anything else has no
      // day to place, and a made-up placement would be a lie.
      const dated = rows.filter((row) => typeof row.date === "number");
      if (!dated.length) return empty("This binding has no dates to plot");
      return grid(dated.map((row) => ({ date: row.date, count: row.count })));
    }

    default:
      return empty("This widget cannot draw " + data.source);
  }
}
