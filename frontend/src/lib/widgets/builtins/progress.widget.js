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
    en: "Progress",
    de: "Fortschritt",
    es: "Progreso",
    fr: "Progression",
  },
  description: {
    en: "How far a value has come against its own range.",
    de: "Wie weit ein Wert innerhalb seines Wertebereichs fortgeschritten ist.",
    es: "Cuánto ha avanzado un valor dentro de su propio rango.",
    fr: "La progression d'une valeur au sein de sa propre plage.",
  },
};

/**
 * Built-in: progress — a value against its range.
 *
 * Shows completion; never offers to change it. A counter-bound progress bar
 * displays the count, and the counter's own increment control stays where it
 * belongs, on the counter.
 *
 * @param {import("../dataShapes").WidgetData} data
 * @param {import("../dataShapes").WidgetConfig} config
 */
function render(data, config) {
  const empty = (message) => ({ v: 1, scene: { kind: "empty", message } });

  const progress = (value, min, max, label, caption) => ({
    v: 1,
    scene: {
      kind: "progress",
      value,
      min,
      max,
      label: label || undefined,
      caption: caption || undefined,
      tone: max > 0 && value >= max ? "positive" : "accent",
      format: config.format || undefined,
    },
  });

  switch (data.source) {
    case "counter": {
      const counter = data.counter;
      if (!counter) return empty("No counter selected");
      // A counter with no ceiling has no completion to show; the number itself
      // is a KPI's job, so say so rather than inventing a denominator.
      if (counter.max === null || counter.max === undefined) {
        return empty("This counter has no maximum");
      }
      const min = counter.min === null || counter.min === undefined ? 0 : counter.min;
      return progress(
        counter.value,
        min,
        counter.max,
        counter.name,
        counter.value + " of " + counter.max + (counter.unit ? " " + counter.unit : "")
      );
    }

    case "task_counts": {
      const rows = data.rows || [];
      if (!rows.length) return empty("No tasks match");
      const total = rows.reduce((sum, row) => sum + row.count, 0);
      const doneRow = rows.find((row) => row.bucket === "done");
      const done = doneRow ? doneRow.count : 0;
      return progress(done, 0, total, "Complete", done + " of " + total + " tasks");
    }

    case "projects": {
      const rows = data.rows || [];
      if (!rows.length) return empty("No projects match");
      const done = rows.reduce((sum, row) => sum + row.doneCount, 0);
      const total = rows.reduce((sum, row) => sum + row.taskCount, 0);
      return progress(
        done,
        0,
        total,
        rows.length === 1 ? rows[0].name : rows.length + " projects",
        done + " of " + total + " tasks"
      );
    }

    default:
      return empty("This widget cannot draw " + data.source);
  }
}
