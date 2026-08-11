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
    en: "Chart",
    de: "Diagramm",
    es: "Gráfico",
    fr: "Graphique",
  },
  description: {
    en: "A series drawn as bars, a line, a filled area, or slices of a whole.",
    de: "Eine Datenreihe als Balken, Linie, gefüllte Fläche oder Kreisdiagramm.",
    es: "Una serie dibujada como barras, línea, área rellena o porciones de un total.",
    fr: "Une série affichée en barres, en courbe, en aire remplie ou en parts d'un tout.",
  },
  options: {
    mark: {
      label: {
        en: "Chart type",
        de: "Diagrammtyp",
        es: "Tipo de gráfico",
        fr: "Type de graphique",
      },
      values: {
        bar: {
          en: "Bar",
          de: "Balken",
          es: "Barras",
          fr: "Barres",
        },
        line: {
          en: "Line",
          de: "Linie",
          es: "Líneas",
          fr: "Courbe",
        },
        area: {
          en: "Area",
          de: "Fläche",
          es: "Área",
          fr: "Aire",
        },
        pie: {
          en: "Pie",
          de: "Kreis",
          es: "Circular",
          fr: "Secteurs",
        },
      },
    },
    stacked: {
      label: {
        en: "Stacked",
        de: "Gestapelt",
        es: "Apilado",
        fr: "Empilé",
      },
      values: {
        true: {
          en: "Stacked",
          de: "Gestapelt",
          es: "Apilado",
          fr: "Empilé",
        },
        false: {
          en: "Side by side",
          de: "Nebeneinander",
          es: "Lado a lado",
          fr: "Côte à côte",
        },
      },
    },
  },
};

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
